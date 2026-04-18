FROM eclipse-mosquitto:2

USER root

RUN apk add --no-cache openssl

COPY docker/mosquitto/docker-entrypoint.sh /usr/local/bin/transitflow-mosquitto-entrypoint.sh
RUN chmod +x /usr/local/bin/transitflow-mosquitto-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/transitflow-mosquitto-entrypoint.sh"]
