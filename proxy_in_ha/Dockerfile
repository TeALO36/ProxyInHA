FROM ghcr.io/home-assistant/base:latest

# Install Nginx, Python 3, Flask, and utilities
RUN apk add --no-cache \
    nginx \
    python3 \
    py3-pip \
    py3-flask \
    curl \
    jq \
    dos2unix \
    openssl

# Create required directories
RUN mkdir -p /run/nginx \
             /data \
             /var/log/nginx \
             /etc/nginx/conf.d \
             /etc/nginx/mtls.d \
             /var/www/html \
             /etc/nginx/certs

# Remove Alpine default nginx site
RUN rm -f /etc/nginx/http.d/default.conf \
    && rm -f /etc/nginx/conf.d/default.conf

# Copy Nginx configuration
COPY nginx/nginx.conf /etc/nginx/nginx.conf

# Copy web UI
COPY web/ /var/www/html/

# Copy API server
COPY api/ /opt/api/

# Copy run script and fix Windows line endings
COPY run.sh /
RUN dos2unix /run.sh && chmod a+x /run.sh

CMD [ "/run.sh" ]
