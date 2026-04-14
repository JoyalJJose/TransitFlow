#!/usr/bin/env bash
#
# Generate self-signed TLS certificates for Mosquitto MQTT broker (dev/testing).
# Outputs: ca.crt, ca.key, server.crt, server.key, client.crt, client.key
#
# Usage:  cd docker/mosquitto/certs && bash generate_certs.sh

set -euo pipefail

DAYS=3650
SUBJ_CA="/CN=TransitFlow MQTT CA"
SUBJ_SERVER="/CN=mosquitto"
SUBJ_CLIENT="/CN=mqtt-client"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> Generating CA key + certificate..."
openssl genrsa -out ca.key 2048
openssl req -x509 -new -nodes -key ca.key -sha256 -days $DAYS \
    -subj "$SUBJ_CA" -out ca.crt

echo "==> Generating server key + CSR + certificate..."
openssl genrsa -out server.key 2048
openssl req -new -key server.key -subj "$SUBJ_SERVER" -out server.csr
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -days $DAYS -sha256 -out server.crt
rm -f server.csr

echo "==> Generating client key + CSR + certificate..."
openssl genrsa -out client.key 2048
openssl req -new -key client.key -subj "$SUBJ_CLIENT" -out client.csr
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -days $DAYS -sha256 -out client.crt
rm -f client.csr

rm -f ca.srl

echo ""
echo "Certificates generated in: $SCRIPT_DIR"
echo "  CA:     ca.crt, ca.key"
echo "  Server: server.crt, server.key"
echo "  Client: client.crt, client.key"
