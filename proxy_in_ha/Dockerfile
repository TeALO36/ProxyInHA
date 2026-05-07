FROM ghcr.io/home-assistant/base:latest

# Install deps
RUN apk add --no-cache \
    nginx \
    python3 \
    py3-pip \
    py3-flask \
    curl \
    jq \
    dos2unix \
    openssl

# Directories
RUN mkdir -p /run/nginx \
             /data \
             /var/log/nginx \
             /etc/nginx/conf.d \
             /etc/nginx/mtls.d \
             /var/www/html \
             /etc/nginx/certs

# Remove Alpine default nginx page
RUN rm -f /etc/nginx/http.d/default.conf \
    && rm -f /etc/nginx/conf.d/default.conf

# Copy configs
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY web/ /var/www/html/
COPY api/ /opt/api/
COPY run.sh /
RUN dos2unix /run.sh && chmod a+x /run.sh

CMD ["/run.sh"]
