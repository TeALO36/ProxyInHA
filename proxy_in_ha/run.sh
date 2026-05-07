#!/usr/bin/with-contenv bashio

###############################################################################
# ProxyInHA v1.2.2 — Entrypoint
# Gère automatiquement les certificats TLS + mTLS et la configuration Nginx
###############################################################################

bashio::log.info "============================================"
bashio::log.info " ProxyInHA v1.2.2 — Auto TLS + mTLS"
bashio::log.info "============================================"

# ── Chemins ─────────────────────────────────────────────────────────────────
SERVICES_DB="/data/services.json"
NGINX_CONF_DIR="/etc/nginx/conf.d"
MTLS_CONF_DIR="/etc/nginx/mtls.d"
NGINX_CERTS="/etc/nginx/certs"     # certs actifs utilisés par nginx
DATA_CERTS="/data/certs"           # certs persistants générés par l'add-on
CHECK_INTERVAL=$(bashio::config 'check_interval')
DOMAIN=$(bashio::config 'domain' 2>/dev/null || echo "")
TLS_MODE=$(bashio::config 'tls_mode' 2>/dev/null || echo "auto")
CADDY_DOMAIN=$(bashio::config 'caddy_cert_domain' 2>/dev/null || echo "")

mkdir -p "${DATA_CERTS}" "${NGINX_CERTS}" "${NGINX_CONF_DIR}" "${MTLS_CONF_DIR}"

bashio::log.info "Mode TLS     : ${TLS_MODE}"
bashio::log.info "Domaine      : ${DOMAIN:-'(non configuré)'}"

# ── Initialiser la base de données ──────────────────────────────────────────
if [ ! -f "${SERVICES_DB}" ]; then
    bashio::log.info "Initialisation base de données avec services par défaut..."
    # Copier les services pré-configurés si disponibles
    if [ -f "/opt/default_services.json" ]; then
        cp /opt/default_services.json "${SERVICES_DB}"
        bashio::log.info "Services pré-configurés chargés ✓"
    else
        echo '[]' > "${SERVICES_DB}"
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════
# GESTION DES CERTIFICATS
# ═══════════════════════════════════════════════════════════════════════════

# ── Génération automatique de tous les certificats ───────────────────────────
generate_certs() {
    local dir="${DATA_CERTS}"
    local domain="${1:-proxyinha.local}"

    bashio::log.info "Génération des certificats TLS (auto)..."
    bashio::log.info "  Domaine : ${domain}"

    # 1. CA (Certificate Authority)
    bashio::log.info "  → CA (Autorité de certification)..."
    openssl genrsa -out "${dir}/ca.key" 4096 2>/dev/null
    openssl req -new -x509 -days 3650 \
        -key "${dir}/ca.key" \
        -out "${dir}/ca.crt" \
        -subj "/C=FR/ST=France/O=ProxyInHA/CN=ProxyInHA Root CA" 2>/dev/null

    # 2. Certificat serveur signé par la CA
    bashio::log.info "  → Certificat serveur..."
    openssl genrsa -out "${dir}/server.key" 2048 2>/dev/null
    openssl req -new \
        -key "${dir}/server.key" \
        -out "${dir}/server.csr" \
        -subj "/C=FR/ST=France/O=ProxyInHA/CN=${domain}" 2>/dev/null

    cat > /tmp/server_ext.cnf <<EOF
[v3_req]
subjectAltName = @alt_names
[alt_names]
DNS.1 = ${domain}
DNS.2 = localhost
IP.1 = 127.0.0.1
EOF
    openssl x509 -req -days 825 \
        -in "${dir}/server.csr" \
        -CA "${dir}/ca.crt" \
        -CAkey "${dir}/ca.key" \
        -CAcreateserial \
        -out "${dir}/server.crt" \
        -extfile /tmp/server_ext.cnf \
        -extensions v3_req 2>/dev/null

    # 3. Certificat client (pour le navigateur)
    bashio::log.info "  → Certificat client..."
    openssl genrsa -out "${dir}/client.key" 2048 2>/dev/null
    openssl req -new \
        -key "${dir}/client.key" \
        -out "${dir}/client.csr" \
        -subj "/C=FR/ST=France/O=ProxyInHA/CN=ProxyInHA Client" 2>/dev/null
    openssl x509 -req -days 825 \
        -in "${dir}/client.csr" \
        -CA "${dir}/ca.crt" \
        -CAkey "${dir}/ca.key" \
        -CAcreateserial \
        -out "${dir}/client.crt" 2>/dev/null

    # 4. Export .p12 (à installer dans le navigateur)
    bashio::log.info "  → Export client.p12 (mot de passe : proxyinha)..."
    openssl pkcs12 -export \
        -in "${dir}/client.crt" \
        -inkey "${dir}/client.key" \
        -certfile "${dir}/ca.crt" \
        -out "${dir}/client.p12" \
        -passout pass:proxyinha 2>/dev/null

    # Legacy p12 pour iOS/macOS anciens
    openssl pkcs12 -export \
        -in "${dir}/client.crt" \
        -inkey "${dir}/client.key" \
        -certfile "${dir}/ca.crt" \
        -out "${dir}/client_legacy.p12" \
        -passout pass:proxyinha \
        -legacy 2>/dev/null || true

    chmod 600 "${dir}/ca.key" "${dir}/server.key" "${dir}/client.key"
    bashio::log.info "Certificats générés avec succès ✓"
}

# ── Trouver les certs Caddy automatiquement ──────────────────────────────────
find_caddy_certs() {
    local domain="${1}"
    local caddy_base="/var/lib/docker/volumes/caddy_data/_data/caddy/certificates"
    local le_path="${caddy_base}/acme-v02.api.letsencrypt.org-directory/${domain}"

    if [ -f "${le_path}/${domain}.crt" ] && [ -f "${le_path}/${domain}.key" ]; then
        bashio::log.info "Certs Let's Encrypt Caddy trouvés pour ${domain} ✓"
        echo "${le_path}/${domain}.crt:${le_path}/${domain}.key"
        return 0
    fi
    return 1
}

# ── Copier les certs actifs vers nginx/certs ─────────────────────────────────
setup_active_certs() {
    local domain="${DOMAIN:-proxyinha.local}"
    local caddy_domain="${CADDY_DOMAIN:-${domain}}"
    local used_mode="auto"

    # ── PRIORITÉ 1 : Certs copiés via l'outil (dans /ssl/proxyinha/)
    # /ssl/ est mappé depuis /mnt/data/supervisor/ssl/ par HA
    if [ -f "/ssl/proxyinha/ca.crt" ]; then
        cp "/ssl/proxyinha/ca.crt" "${NGINX_CERTS}/ca.crt"
        bashio::log.info "CA mTLS depuis /ssl/proxyinha/ca.crt ✓ — même cert client que HA"
    elif [ -f "/root/mtls-ca/ca.crt" ]; then
        cp "/root/mtls-ca/ca.crt" "${NGINX_CERTS}/ca.crt"
        bashio::log.info "CA mTLS depuis /root/mtls-ca/ca.crt ✓"
    fi

    if [ -f "/ssl/proxyinha/server.crt" ] && [ -f "/ssl/proxyinha/server.key" ]; then
        cp "/ssl/proxyinha/server.crt" "${NGINX_CERTS}/server.crt"
        cp "/ssl/proxyinha/server.key" "${NGINX_CERTS}/server.key"
        chmod 600 "${NGINX_CERTS}/server.key"
        bashio::log.info "Cert serveur Let's Encrypt depuis /ssl/proxyinha/ ✓"
        used_mode="caddy_ssl"
    fi

    # ── PRIORITÉ 2 : Certs Caddy dans le volume Docker (si disponible)
    if [ ! -f "${NGINX_CERTS}/server.crt" ]; then
        local caddy_certs
        caddy_certs=$(find_caddy_certs "${caddy_domain}") || true
        if [ -n "${caddy_certs}" ]; then
            local cert_path key_path
            cert_path="${caddy_certs%%:*}"
            key_path="${caddy_certs##*:}"
            cp "${cert_path}" "${NGINX_CERTS}/server.crt"
            cp "${key_path}"  "${NGINX_CERTS}/server.key"
            chmod 600 "${NGINX_CERTS}/server.key"
            bashio::log.info "Cert serveur Caddy (${caddy_domain}) ✓"
            used_mode="caddy"
        fi
    fi

    # ── PRIORITÉ 3 : Auto-génération si aucun cert trouvé
    if [ ! -f "${NGINX_CERTS}/server.crt" ]; then
        if [ ! -f "${DATA_CERTS}/server.crt" ] || [ ! -f "${DATA_CERTS}/ca.crt" ]; then
            generate_certs "${domain}"
        else
            bashio::log.info "Certificats auto-générés existants ✓"
        fi
        cp "${DATA_CERTS}/server.crt" "${NGINX_CERTS}/server.crt"
        cp "${DATA_CERTS}/server.key" "${NGINX_CERTS}/server.key"
        chmod 600 "${NGINX_CERTS}/server.key"
        if [ ! -f "${NGINX_CERTS}/ca.crt" ]; then
            cp "${DATA_CERTS}/ca.crt" "${NGINX_CERTS}/ca.crt"
            bashio::log.info "CA auto-générée (cert client .p12 requis)"
        fi
        used_mode="auto"
    fi

    bashio::log.info "Mode TLS effectif : ${used_mode}"
}




setup_active_certs

# ── Vérification finale ──────────────────────────────────────────────────────
HAVE_SERVER_CERT=false
HAVE_CA_CERT=false
[ -f "${NGINX_CERTS}/server.crt" ] && [ -f "${NGINX_CERTS}/server.key" ] && HAVE_SERVER_CERT=true
[ -f "${NGINX_CERTS}/ca.crt" ] && HAVE_CA_CERT=true

bashio::log.info "Cert serveur : ${HAVE_SERVER_CERT}"
bashio::log.info "CA mTLS      : ${HAVE_CA_CERT}"

# ═══════════════════════════════════════════════════════════════════════════
# GÉNÉRATION DE LA CONFIG NGINX
# ═══════════════════════════════════════════════════════════════════════════

generate_internal_proxy() {
    rm -f "${NGINX_CONF_DIR}"/proxy_*.conf
    local idx=0

    while IFS= read -r svc; do
        local name url enabled slug
        name=$(echo "${svc}" | jq -r '.name')
        url=$(echo "${svc}"  | jq -r '.url')
        enabled=$(echo "${svc}" | jq -r '.enabled')

        if [ "${enabled}" == "true" ]; then
            slug=$(echo "${name}" | tr '[:upper:]' '[:lower:]' \
                | sed 's/[^a-z0-9]/-/g;s/--*/-/g;s/^-//;s/-$//')
            cat > "${NGINX_CONF_DIR}/proxy_${slug}.conf" <<EOF
location /proxy/${slug}/ {
    proxy_pass ${url}/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_connect_timeout 10s;
    proxy_send_timeout 86400s;
    proxy_read_timeout 86400s;
    proxy_buffering off;
}
EOF
            idx=$((idx + 1))
        fi
    done < <(jq -c '.[]' "${SERVICES_DB}" 2>/dev/null || true)

    bashio::log.info "Proxy interne : ${idx} location(s)"
}

generate_mtls_servers() {
    rm -f "${MTLS_CONF_DIR}"/*.conf
    local idx=0

    if [ "${HAVE_SERVER_CERT}" != "true" ]; then
        bashio::log.warning "Pas de certificat serveur — serveurs mTLS désactivés"
        return
    fi

    local ca_block=""
    if [ "${HAVE_CA_CERT}" == "true" ]; then
        ca_block="
    ssl_client_certificate ${NGINX_CERTS}/ca.crt;
    ssl_verify_client on;"
    fi

    local server_name="${DOMAIN:-_}"

    while IFS= read -r svc; do
        local name url enabled public public_port slug
        name=$(echo "${svc}" | jq -r '.name')
        url=$(echo "${svc}"  | jq -r '.url')
        enabled=$(echo "${svc}" | jq -r '.enabled')
        public=$(echo "${svc}" | jq -r '.public // false')
        public_port=$(echo "${svc}" | jq -r '.public_port // empty')

        if [ "${enabled}" == "true" ] && [ "${public}" == "true" ] && [ -n "${public_port}" ]; then
            slug=$(echo "${name}" | tr '[:upper:]' '[:lower:]' \
                | sed 's/[^a-z0-9]/-/g;s/--*/-/g;s/^-//;s/-$//')
            bashio::log.info "  → [mTLS :${public_port}] ${name}"

            cat > "${MTLS_CONF_DIR}/mtls_${slug}.conf" <<EOF
server {
    listen ${public_port} ssl;
    server_name ${server_name};

    ssl_certificate     ${NGINX_CERTS}/server.crt;
    ssl_certificate_key ${NGINX_CERTS}/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL_${slug}:10m;
    ssl_session_timeout 1d;
${ca_block}

    location / {
        proxy_pass ${url}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Client-Cert-DN \$ssl_client_s_dn;
        proxy_set_header X-Client-Verified \$ssl_client_verify;
        proxy_connect_timeout 10s;
        proxy_send_timeout 86400s;
        proxy_read_timeout 86400s;
        proxy_buffering off;
    }
}
EOF
            idx=$((idx + 1))
        fi
    done < <(jq -c '.[]' "${SERVICES_DB}" 2>/dev/null || true)

    bashio::log.info "Proxy mTLS : ${idx} serveur(s)"
}

generate_internal_proxy
generate_mtls_servers

# ── Validation & démarrage Nginx ─────────────────────────────────────────────
bashio::log.info "Validation Nginx..."
if nginx -t 2>&1; then
    bashio::log.info "Config Nginx valide ✓"
else
    bashio::log.error "Config Nginx INVALIDE"
    exit 1
fi

bashio::log.info "Démarrage Nginx..."
nginx

# ── Démarrage API Flask ──────────────────────────────────────────────────────
bashio::log.info "Démarrage API Flask (port 5000)..."
export SERVICES_DB NGINX_CONF_DIR MTLS_CONF_DIR NGINX_CERTS DATA_CERTS DOMAIN TLS_MODE

exec python3 /opt/api/server.py
