#!/usr/bin/env bash
set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://172.31.118.0:8200}"
VAULT_AWS_AUTH_ROLE="${VAULT_AWS_AUTH_ROLE:-goodvines-api}"
HALLOWEEN_APP_SECRET_PATH="${HALLOWEEN_APP_SECRET_PATH:-appsecrets/halloween_app}"
HALLOWEEN_REDIS_SECRET_PATH="${HALLOWEEN_REDIS_SECRET_PATH:-appsecrets/halloween_redis}"
HALLOWEEN_APP_PORT="${HALLOWEEN_APP_PORT:-8081}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-1}"
GUNICORN_THREADS="${GUNICORN_THREADS:-8}"

if ! command -v vault >/dev/null 2>&1; then
  echo "vault CLI is required to start halloween-party" >&2
  exit 1
fi

vault_token="$(VAULT_ADDR="${VAULT_ADDR}" vault login -method=aws -token-only role="${VAULT_AWS_AUTH_ROLE}")"

vault_field() {
  local path="$1"
  local field="$2"
  VAULT_ADDR="${VAULT_ADDR}" VAULT_TOKEN="${vault_token}" vault kv get -field="${field}" "${path}"
}

export HALLOWEEN_APP_SECRET
HALLOWEEN_APP_SECRET="$(vault_field "${HALLOWEEN_APP_SECRET_PATH}" secret_key)"

export HALLOWEEN_ADMIN_PASSWORD
HALLOWEEN_ADMIN_PASSWORD="$(vault_field "${HALLOWEEN_APP_SECRET_PATH}" admin_password)"

export HALLOWEEN_REDIS_HOST
HALLOWEEN_REDIS_HOST="$(vault_field "${HALLOWEEN_REDIS_SECRET_PATH}" host)"

export HALLOWEEN_REDIS_PORT
HALLOWEEN_REDIS_PORT="$(vault_field "${HALLOWEEN_REDIS_SECRET_PATH}" port)"

export HALLOWEEN_REDIS_DB
HALLOWEEN_REDIS_DB="$(vault_field "${HALLOWEEN_REDIS_SECRET_PATH}" db)"

export HALLOWEEN_REDIS_USERNAME
HALLOWEEN_REDIS_USERNAME="$(vault_field "${HALLOWEEN_REDIS_SECRET_PATH}" username)"

export HALLOWEEN_REDIS_PASSWORD
HALLOWEEN_REDIS_PASSWORD="$(vault_field "${HALLOWEEN_REDIS_SECRET_PATH}" password)"

export HALLOWEEN_REDIS_PREFIX
HALLOWEEN_REDIS_PREFIX="$(vault_field "${HALLOWEEN_REDIS_SECRET_PATH}" prefix)"

exec /opt/halloween/current/.venv/bin/gunicorn \
  --workers "${GUNICORN_WORKERS}" \
  --threads "${GUNICORN_THREADS}" \
  --bind "127.0.0.1:${HALLOWEEN_APP_PORT}" \
  --access-logfile - \
  --error-logfile - \
  main:app
