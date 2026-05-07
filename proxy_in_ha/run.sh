#!/usr/bin/with-contenv bashio

###############################################################################
# ProxyInHA — Entrypoint script
###############################################################################

bashio::log.info "========================================="
bashio::log.info " ProxyInHA — Reverse Proxy for HA"
bashio::log.info "========================================="

SERVICES_DB="/data/services.json"
NGINX_CONF_DIR="/etc/nginx/conf.d"

CHECK_INTERVAL=$(bashio::config 'check_interval')
bashio::log.info "Health check interval: ${CHECK_INTERVAL}s"

# ---------------------------------------------------------------------------
# 1. Initialize services database
# ---------------------------------------------------------------------------
if [ ! -f "${SERVICES_DB}" ]; then
    bashio::log.info "Initializing empty services database..."
    echo '[]' > "${SERVICES_DB}"
fi

# ---------------------------------------------------------------------------
# 2. Generate Nginx proxy configs for each enabled service
# ---------------------------------------------------------------------------
generate_nginx_config() {
    bashio::log.info "Generating Nginx proxy configuration..."
    rm -f "${NGINX_CONF_DIR}"/proxy_*.conf

    local idx=0
    while IFS= read -r service; do
        local name url enabled slug
        name=$(echo "${service}" | jq -r '.name')
        url=$(echo "${service}"  | jq -r '.url')
        enabled=$(echo "${service}" | jq -r '.enabled')

        if [ "${enabled}" == "true" ]; then
            slug=$(echo "${name}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g;s/--*/-/g;s/^-//;s/-$//')
            bashio::log.info "  → ${name} (${slug}) → ${url}"

            cat > "${NGINX_CONF_DIR}/proxy_${slug}.conf" <<NGINX_EOF
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
    proxy_request_buffering off;
}
NGINX_EOF
            idx=$((idx + 1))
        fi
    done < <(jq -c '.[]' "${SERVICES_DB}" 2>/dev/null || echo "")

    bashio::log.info "Done: ${idx} proxy location(s) generated"
}

generate_nginx_config

# ---------------------------------------------------------------------------
# 3. Validate and start Nginx
# ---------------------------------------------------------------------------
bashio::log.info "Validating Nginx configuration..."
if nginx -t 2>&1; then
    bashio::log.info "Nginx config valid ✓"
else
    bashio::log.error "Nginx config INVALID — check logs above"
    exit 1
fi

bashio::log.info "Starting Nginx..."
nginx

# ---------------------------------------------------------------------------
# 4. Start Flask API server (foreground — keeps container alive)
# ---------------------------------------------------------------------------
bashio::log.info "Starting API server on 127.0.0.1:5000..."
export SERVICES_DB="${SERVICES_DB}"
export NGINX_CONF_DIR="${NGINX_CONF_DIR}"
export CHECK_INTERVAL="${CHECK_INTERVAL}"

exec python3 /opt/api/server.py
