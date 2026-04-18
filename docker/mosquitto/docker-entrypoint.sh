#!/bin/sh
set -eu

CERT_DIR="/mosquitto/certs"

mkdir -p "$CERT_DIR"

if [ ! -f "$CERT_DIR/ca.crt" ] || [ ! -f "$CERT_DIR/server.crt" ] || [ ! -f "$CERT_DIR/server.key" ] || [ ! -f "$CERT_DIR/client.crt" ] || [ ! -f "$CERT_DIR/client.key" ]; then
    echo "[mosquitto-init] Generating demo TLS certificates..."

    openssl genrsa -out "$CERT_DIR/ca.key" 2048
    openssl req -x509 -new -nodes -key "$CERT_DIR/ca.key" -sha256 -days 3650 \
        -subj "/CN=TransitFlow MQTT CA" -out "$CERT_DIR/ca.crt"

    openssl genrsa -out "$CERT_DIR/server.key" 2048
    openssl req -new -key "$CERT_DIR/server.key" -subj "/CN=mosquitto" -out "$CERT_DIR/server.csr"
    openssl x509 -req -in "$CERT_DIR/server.csr" -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
        -CAcreateserial -days 3650 -sha256 -out "$CERT_DIR/server.crt"
    rm -f "$CERT_DIR/server.csr"

    openssl genrsa -out "$CERT_DIR/client.key" 2048
    openssl req -new -key "$CERT_DIR/client.key" -subj "/CN=mqtt-client" -out "$CERT_DIR/client.csr"
    openssl x509 -req -in "$CERT_DIR/client.csr" -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" \
        -CAcreateserial -days 3650 -sha256 -out "$CERT_DIR/client.crt"
    rm -f "$CERT_DIR/client.csr" "$CERT_DIR/ca.srl"

fi

# Ensure permissions are correct when the cert dir is writable (named volume).
# When certs are bind-mounted read-only (dev compose), skip the chown/chmod
# entirely – files already have usable perms from the host and mosquitto only
# needs to read them.
if [ -w "$CERT_DIR" ]; then
    chown -R mosquitto:mosquitto "$CERT_DIR" 2>/dev/null || true
    chmod 644 "$CERT_DIR/ca.crt" "$CERT_DIR/server.crt" "$CERT_DIR/client.crt" 2>/dev/null || true
    chmod 644 "$CERT_DIR/server.key" "$CERT_DIR/client.key" 2>/dev/null || true
    if [ -f "$CERT_DIR/ca.key" ]; then
        chmod 644 "$CERT_DIR/ca.key" 2>/dev/null || true
    fi
else
    echo "[mosquitto-init] Cert dir is read-only – skipping chown/chmod."
fi

exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
