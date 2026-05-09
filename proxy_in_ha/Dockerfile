FROM ghcr.io/home-assistant/base:latest

RUN apk add --no-cache nginx nginx-mod-http-sub python3 py3-pip py3-flask curl jq dos2unix openssl

RUN mkdir -p /run/nginx /data /var/log/nginx \
             /etc/nginx/conf.d /etc/nginx/mtls.d \
             /var/www/html /etc/nginx/certs

# Supprimer TOUTES les configs nginx Alpine par défaut
RUN rm -rf /etc/nginx/http.d /etc/nginx/conf.d \
    && mkdir -p /etc/nginx/conf.d /etc/nginx/mtls.d

COPY nginx/nginx.conf /etc/nginx/nginx.conf
RUN dos2unix /etc/nginx/nginx.conf

COPY web/ /var/www/html/
# Cache-bust: v1.3.3
ARG CACHE_BUST=v1.3.3
COPY api/ /opt/api/
RUN dos2unix /opt/api/*.py 2>/dev/null || true

COPY run.sh /
RUN dos2unix /run.sh && chmod +x /run.sh

CMD ["/run.sh"]
