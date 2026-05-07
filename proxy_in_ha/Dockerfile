FROM ghcr.io/home-assistant/base:latest

# Install Nginx, Python 3, Flask, and utilities
RUN apk add --no-cache \
    nginx \
    python3 \
    py3-pip \
    py3-flask \
    curl \
    jq

# Create required directories
RUN mkdir -p /run/nginx /data /var/log/nginx /etc/nginx/conf.d

# Copy Nginx configuration
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/proxy.conf.template /etc/nginx/proxy.conf.template

# Copy web UI
COPY web/ /var/www/html/

# Copy API server
COPY api/ /opt/api/

# Copy run script
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
