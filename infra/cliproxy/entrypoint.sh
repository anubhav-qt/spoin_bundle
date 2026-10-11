#!/bin/sh
# Writes the proxy's config from the keys in infra/.env on every start, then runs it. The proxy
# hashes the management key in the file in place, so the file is never the source of the keys.
set -eu

: "${CLIPROXY_API_KEY:?Set CLIPROXY_API_KEY in infra/.env}"
: "${CLIPROXY_MANAGEMENT_KEY:?Set CLIPROXY_MANAGEMENT_KEY in infra/.env}"

# allow-remote: the api container reads the management API across the compose network (the
# model accounts page); the host port is bound to 127.0.0.1, so nothing off this machine can.
# round-robin: parallel chats and the request path split the load over the two accounts.
cat > /app/config.yaml <<EOF
config-version: 8
server:
  host: "0.0.0.0"
  port: 8317
management:
  allow-remote: true
  secret-key: "${CLIPROXY_MANAGEMENT_KEY}"
  disable-control-panel: true
  disable-auto-update-panel: true
access:
  api-keys:
    - "${CLIPROXY_API_KEY}"
routing:
  strategy: "round-robin"
oauth:
  auth-dir: "/app/auths"
EOF
chmod 600 /app/config.yaml

exec cli-proxy-api -config /app/config.yaml
