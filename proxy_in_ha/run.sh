#!/usr/bin/with-contenv bashio

###############################################################################
# ProxyInHA — Entrypoint script
# Reads add-on options, generates Nginx config, starts Nginx + API server
###############################################################################

bashio::log.info "========================================="
bashio::log.info " ProxyInHA — Reverse Proxy for HA"
bashio::log.info "========================================="

# ---------------------------------------------------------------------------
# 1. Read configuration from /data/options.json
# ---------------------------------------------------------------------------
CONFIG_PATH="/data/options.json"
SERVICES_DB="/data/services.json"
NGINX_CONF_DIR="/etc/nginx/conf.d"
TEMPLATE="/etc/nginx/proxy.conf.template"

CHECK_INTERVAL=$(bashio::config 'check_interval')
bashio::log.info "Health check interval: ${CHECK_INTERVAL}s"

# ---------------------------------------------------------------------------
# 2. Initialize services database if it doesn't exist
# ---------------------------------------------------------------------------
if [ ! -f "${SERVICES_DB}" ]; then
    bashio::log.info "Initializing services database..."
    # Read services from add-on options
    SERVICES=$(bashio::config 'services')
    if [ "${SERVICES}" == "null" ] || [ -z "${SERVICES}" ]; then
        echo '[]' > "${SERVICES_DB}"
    else
        jq '.services' "${CONFIG_PATH}" > "${SERVICES_DB}"
    fi
fi

bashio::log.info "Services database: ${SERVICES_DB}"

# ---------------------------------------------------------------------------
# 3. Generate Nginx proxy configuration from services
# ---------------------------------------------------------------------------
generate_nginx_config() {
    bashio::log.info "Generating Nginx proxy configuration..."

    # Clear existing proxy configs
    rm -f "${NGINX_CONF_DIR}"/*.conf

    # Read the ingress entry path
    INGRESS_ENTRY=$(bashio::addon.ingress_entry)
    bashio::log.info "Ingress entry: ${INGRESS_ENTRY}"

    # Generate a location block for each enabled service
    local idx=0
    while read -r service; do
        local name
        local url
        local enabled

        name=$(echo "${service}" | jq -r '.name')
        url=$(echo "${service}" | jq -r '.url')
        enabled=$(echo "${service}" | jq -r '.enabled')

        if [ "${enabled}" == "true" ]; then
            local slug
            slug=$(echo "${name}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')

            bashio::log.info "  → Configuring proxy for '${name}' → ${url} (slug: ${slug})"

            # Generate Nginx location block
            cat > "${NGINX_CONF_DIR}/proxy_${slug}.conf" <<NGINX_EOF
# Proxy configuration for: ${name}
location ${INGRESS_ENTRY}proxy/${slug}/ {
    proxy_pass ${url}/;
    proxy_http_version 1.1;

    # WebSocket support
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";

    # Standard proxy headers
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Forwarded-Host \$host;

    # Timeouts
    proxy_connect_timeout 10s;
    proxy_send_timeout 86400s;
    proxy_read_timeout 86400s;

    # Buffering
    proxy_buffering off;
    proxy_request_buffering off;
}
NGINX_EOF
        else
            bashio::log.info "  → Skipping disabled service '${name}'"
        fi

        idx=$((idx + 1))
    done < <(jq -c '.[]' "${SERVICES_DB}")

    bashio::log.info "Nginx proxy configuration generated (${idx} services processed)"
}

# ---------------------------------------------------------------------------
# 4. Generate config and validate
# ---------------------------------------------------------------------------
generate_nginx_config

# Update the ingress path in the main nginx config
INGRESS_ENTRY=$(bashio::addon.ingress_entry)
sed -i "s|%%INGRESS_ENTRY%%|${INGRESS_ENTRY}|g" /etc/nginx/nginx.conf

bashio::log.info "Validating Nginx configuration..."
if nginx -t 2>&1; then
    bashio::log.info "Nginx configuration is valid ✓"
else
    bashio::log.error "Nginx configuration is INVALID!"
    bashio::log.error "$(nginx -t 2>&1)"
fi

# ---------------------------------------------------------------------------
# 5. Start Nginx
# ---------------------------------------------------------------------------
bashio::log.info "Starting Nginx..."
nginx

# ---------------------------------------------------------------------------
# 6. Start the API server in the background
# ---------------------------------------------------------------------------
bashio::log.info "Starting API server..."
export SERVICES_DB="${SERVICES_DB}"
export NGINX_CONF_DIR="${NGINX_CONF_DIR}"
export INGRESS_ENTRY="${INGRESS_ENTRY}"
export CHECK_INTERVAL="${CHECK_INTERVAL}"
python3 /opt/api/server.py &
API_PID=$!

bashio::log.info "API server started (PID: ${API_PID})"

# ---------------------------------------------------------------------------
# 7. Health check loop
# ---------------------------------------------------------------------------
bashio::log.info "Starting health check loop (interval: ${CHECK_INTERVAL}s)..."

health_check() {
    while true; do
        while read -r service; do
            local name url enabled
            name=$(echo "${service}" | jq -r '.name')
            url=$(echo "${service}" | jq -r '.url')
            enabled=$(echo "${service}" | jq -r '.enabled')

            if [ "${enabled}" == "true" ]; then
                if curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 5 "${url}" | grep -qE "^[23]"; then
                    bashio::log.debug "Health OK: ${name} (${url})"
                else
                    bashio::log.warning "Health FAIL: ${name} (${url})"
                fi
            fi
        done < <(jq -c '.[]' "${SERVICES_DB}")

        sleep "${CHECK_INTERVAL}"
    done
}

health_check &
HEALTH_PID=$!

# ---------------------------------------------------------------------------
# 8. Wait for processes
# ---------------------------------------------------------------------------
bashio::log.info "ProxyInHA is running!"

# Wait for API server (main process)
wait "${API_PID}"
