#!/usr/bin/with-contenv bashio

###############################################################################
# ProxyInHA v1.1.0 — Entrypoint
# - Génère les locations Nginx pour les services internes (ingress)
# - Génère les server blocks mTLS pour les services publics
###############################################################################

bashio::log.info "========================================="
bashio::log.info " ProxyInHA v1.1.0 — Reverse Proxy + mTLS"
bashio::log.info "========================================="

SERVICES_DB="/data/services.json"
NGINX_CONF_DIR="/etc/nginx/conf.d"
MTLS_CONF_DIR="/etc/nginx/mtls.d"
CERTS_DIR="/etc/nginx/certs"
CHECK_INTERVAL=$(bashio::config 'check_interval')

# ---------------------------------------------------------------------------
# 1. Lire la config globale mTLS
# ---------------------------------------------------------------------------
DOMAIN=$(bashio::config 'domain' 2>/dev/null || echo "")
CERT_PATH=$(bashio::config 'cert_path' 2>/dev/null || echo "")
CERT_KEY_PATH=$(bashio::config 'cert_key_path' 2>/dev/null || echo "")
MTLS_CA_PATH=$(bashio::config 'mtls_ca_path' 2>/dev/null || echo "")

bashio::log.info "Domain: ${DOMAIN:-'(non configuré)'}"
bashio::log.info "Cert: ${CERT_PATH:-'(non configuré)'}"

# ---------------------------------------------------------------------------
# 2. Copier les certificats si configurés
# ---------------------------------------------------------------------------
setup_certs() {
    local cert_ok=false

    if [ -n "${CERT_PATH}" ] && [ -f "${CERT_PATH}" ]; then
        cp "${CERT_PATH}" "${CERTS_DIR}/server.crt"
        bashio::log.info "Certificat serveur copié : ${CERT_PATH}"
        cert_ok=true
    fi

    if [ -n "${CERT_KEY_PATH}" ] && [ -f "${CERT_KEY_PATH}" ]; then
        cp "${CERT_KEY_PATH}" "${CERTS_DIR}/server.key"
        chmod 600 "${CERTS_DIR}/server.key"
        bashio::log.info "Clé serveur copiée : ${CERT_KEY_PATH}"
    fi

    if [ -n "${MTLS_CA_PATH}" ] && [ -f "${MTLS_CA_PATH}" ]; then
        cp "${MTLS_CA_PATH}" "${CERTS_DIR}/ca.crt"
        bashio::log.info "CA mTLS copié : ${MTLS_CA_PATH}"
    fi

    echo "${cert_ok}"
}

CERTS_READY=$(setup_certs)

# ---------------------------------------------------------------------------
# 3. Initialiser la base de données services
# ---------------------------------------------------------------------------
if [ ! -f "${SERVICES_DB}" ]; then
    bashio::log.info "Initialisation base de données services..."
    echo '[]' > "${SERVICES_DB}"
fi

# ---------------------------------------------------------------------------
# 4. Générer les configs Nginx (ingress interne)
# ---------------------------------------------------------------------------
generate_internal_proxy() {
    bashio::log.info "Génération des locations proxy internes..."
    rm -f "${NGINX_CONF_DIR}"/proxy_*.conf

    local idx=0
    while IFS= read -r service; do
        local name url enabled slug
        name=$(echo "${service}" | jq -r '.name')
        url=$(echo "${service}"  | jq -r '.url')
        enabled=$(echo "${service}" | jq -r '.enabled')

        if [ "${enabled}" == "true" ]; then
            slug=$(echo "${name}" | tr '[:upper:]' '[:lower:]' \
                | sed 's/[^a-z0-9]/-/g;s/--*/-/g;s/^-//;s/-$//')
            bashio::log.info "  → [interne] ${name} → ${url}"

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

    bashio::log.info "  ${idx} location(s) interne(s) générée(s)"
}

# ---------------------------------------------------------------------------
# 5. Générer les server blocks mTLS (publics)
# ---------------------------------------------------------------------------
generate_mtls_servers() {
    bashio::log.info "Génération des serveurs mTLS publics..."
    rm -f "${MTLS_CONF_DIR}"/*.conf

    # Vérifier que les certs sont disponibles
    if [ ! -f "${CERTS_DIR}/server.crt" ] || [ ! -f "${CERTS_DIR}/server.key" ]; then
        bashio::log.warning "Certificats TLS manquants — aucun serveur mTLS généré"
        bashio::log.warning "Configurez cert_path et cert_key_path dans les options de l'add-on"
        return
    fi

    local mtls_available=false
    if [ -f "${CERTS_DIR}/ca.crt" ]; then
        mtls_available=true
        bashio::log.info "CA mTLS disponible — authentification client activée"
    else
        bashio::log.warning "CA mTLS absent — TLS sans vérification client (mode dégradé)"
    fi

    local idx=0
    while IFS= read -r service; do
        local name url enabled public public_port slug
        name=$(echo "${service}" | jq -r '.name')
        url=$(echo "${service}"  | jq -r '.url')
        enabled=$(echo "${service}" | jq -r '.enabled')
        public=$(echo "${service}" | jq -r '.public // false')
        public_port=$(echo "${service}" | jq -r '.public_port // empty')

        if [ "${enabled}" == "true" ] && [ "${public}" == "true" ] && [ -n "${public_port}" ]; then
            slug=$(echo "${name}" | tr '[:upper:]' '[:lower:]' \
                | sed 's/[^a-z0-9]/-/g;s/--*/-/g;s/^-//;s/-$//')
            bashio::log.info "  → [mTLS public] ${name} → port ${public_port} → ${url}"

            # Construire le bloc ssl_client_certificate selon disponibilité CA
            local client_auth_block=""
            if [ "${mtls_available}" == "true" ]; then
                client_auth_block="
    # mTLS — vérification certificat client
    ssl_client_certificate ${CERTS_DIR}/ca.crt;
    ssl_verify_client on;"
            fi

            cat > "${MTLS_CONF_DIR}/mtls_${slug}.conf" <<EOF
server {
    listen ${public_port} ssl;
    server_name ${DOMAIN:-_};

    # Certificats TLS serveur (Let's Encrypt via Caddy)
    ssl_certificate     ${CERTS_DIR}/server.crt;
    ssl_certificate_key ${CERTS_DIR}/server.key;

    # Protocoles et ciphers sécurisés
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
${client_auth_block}

    # Reverse proxy vers le service local
    location / {
        proxy_pass ${url}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host \$host:\$server_port;
        # Transmettre le DN du certificat client si mTLS
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

    bashio::log.info "  ${idx} serveur(s) mTLS généré(s)"
}

# ---------------------------------------------------------------------------
# 6. Générer toutes les configs et valider
# ---------------------------------------------------------------------------
generate_internal_proxy
generate_mtls_servers

bashio::log.info "Validation de la configuration Nginx..."
if nginx -t 2>&1; then
    bashio::log.info "Configuration Nginx valide ✓"
else
    bashio::log.error "Configuration Nginx INVALIDE — voir erreurs ci-dessus"
    exit 1
fi

# ---------------------------------------------------------------------------
# 7. Démarrer Nginx
# ---------------------------------------------------------------------------
bashio::log.info "Démarrage de Nginx..."
nginx

# ---------------------------------------------------------------------------
# 8. Démarrer l'API Flask en foreground (garde le container en vie)
# ---------------------------------------------------------------------------
bashio::log.info "Démarrage de l'API Flask sur 127.0.0.1:5000..."
export SERVICES_DB="${SERVICES_DB}"
export NGINX_CONF_DIR="${NGINX_CONF_DIR}"
export MTLS_CONF_DIR="${MTLS_CONF_DIR}"
export CERTS_DIR="${CERTS_DIR}"
export CHECK_INTERVAL="${CHECK_INTERVAL}"
export DOMAIN="${DOMAIN}"

exec python3 /opt/api/server.py
