#!/usr/bin/env bash
set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://172.31.118.0:8200}"
VAULT_AWS_AUTH_ROLE="${VAULT_AWS_AUTH_ROLE:-goodvines-api}"
HALLOWEEN_APP_SECRET_PATH="${HALLOWEEN_APP_SECRET_PATH:-appsecrets/halloween_app}"
HALLOWEEN_REDIS_SECRET_PATH="${HALLOWEEN_REDIS_SECRET_PATH:-appsecrets/halloween_redis}"
HALLOWEEN_YOUTUBE_SECRET_PATH="${HALLOWEEN_YOUTUBE_SECRET_PATH:-appsecrets/halloween_youtube}"
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

vault_optional_field() {
  local path="$1"
  local field="$2"
  local fallback="$3"
  VAULT_ADDR="${VAULT_ADDR}" VAULT_TOKEN="${vault_token}" vault kv get -field="${field}" "${path}" 2>/dev/null || printf '%s' "${fallback}"
}

export HALLOWEEN_APP_SECRET
HALLOWEEN_APP_SECRET="$(vault_field "${HALLOWEEN_APP_SECRET_PATH}" secret_key)"

export HALLOWEEN_ADMIN_PASSWORD
HALLOWEEN_ADMIN_PASSWORD="$(vault_field "${HALLOWEEN_APP_SECRET_PATH}" admin_password)"

export HALLOWEEN_EMAIL_UPDATES_ENABLED
HALLOWEEN_EMAIL_UPDATES_ENABLED="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" email_updates_enabled "false")"

export HALLOWEEN_SES_REGION
HALLOWEEN_SES_REGION="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" ses_region "us-east-1")"

export HALLOWEEN_EMAIL_FROM
HALLOWEEN_EMAIL_FROM="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" email_from "Qiana and Tony's Halloween Party <no-reply@tnq-halloween.com>")"

export HALLOWEEN_PUBLIC_BASE_URL
HALLOWEEN_PUBLIC_BASE_URL="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" public_base_url "https://tnq-halloween.com")"

# MusicKit is optional until the party display is paired. The Media Services
# private key remains in Vault and is only used by Flask to issue developer
# tokens to an authenticated live-display browser.
export HALLOWEEN_APPLE_MUSIC_DEVELOPER_TOKEN
HALLOWEEN_APPLE_MUSIC_DEVELOPER_TOKEN="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" apple_music_developer_token "")"

export HALLOWEEN_APPLE_MUSIC_TEAM_ID
HALLOWEEN_APPLE_MUSIC_TEAM_ID="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" apple_music_team_id "")"

export HALLOWEEN_APPLE_MUSIC_KEY_ID
HALLOWEEN_APPLE_MUSIC_KEY_ID="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" apple_music_key_id "")"

export HALLOWEEN_APPLE_MUSIC_PRIVATE_KEY
HALLOWEEN_APPLE_MUSIC_PRIVATE_KEY="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" apple_music_private_key "")"

export HALLOWEEN_APPLE_MUSIC_STOREFRONT
HALLOWEEN_APPLE_MUSIC_STOREFRONT="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" apple_music_storefront "us")"

export HALLOWEEN_APPLE_MUSIC_WEB_ORIGIN
HALLOWEEN_APPLE_MUSIC_WEB_ORIGIN="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" apple_music_web_origin "")"

# YouTube karaoke credentials live in a dedicated Vault path. The API key
# fallback preserves the existing production search key during migration.
export HALLOWEEN_YOUTUBE_KARAOKE_ENABLED
HALLOWEEN_YOUTUBE_KARAOKE_ENABLED="$(vault_optional_field "${HALLOWEEN_YOUTUBE_SECRET_PATH}" enabled "false")"

export HALLOWEEN_YOUTUBE_API_KEY
HALLOWEEN_YOUTUBE_API_KEY="$(vault_optional_field "${HALLOWEEN_YOUTUBE_SECRET_PATH}" api_key "")"
if [[ -z "${HALLOWEEN_YOUTUBE_API_KEY}" ]]; then
  HALLOWEEN_YOUTUBE_API_KEY="$(vault_optional_field "${HALLOWEEN_APP_SECRET_PATH}" youtube_api_key "")"
fi

export HALLOWEEN_YOUTUBE_CLIENT_ID
HALLOWEEN_YOUTUBE_CLIENT_ID="$(vault_optional_field "${HALLOWEEN_YOUTUBE_SECRET_PATH}" oauth_client_id "")"

export HALLOWEEN_YOUTUBE_CLIENT_SECRET
HALLOWEEN_YOUTUBE_CLIENT_SECRET="$(vault_optional_field "${HALLOWEEN_YOUTUBE_SECRET_PATH}" oauth_client_secret "")"

export HALLOWEEN_YOUTUBE_REFRESH_TOKEN
HALLOWEEN_YOUTUBE_REFRESH_TOKEN="$(vault_optional_field "${HALLOWEEN_YOUTUBE_SECRET_PATH}" oauth_refresh_token "")"

export HALLOWEEN_YOUTUBE_REGION_CODE
HALLOWEEN_YOUTUBE_REGION_CODE="$(vault_optional_field "${HALLOWEEN_YOUTUBE_SECRET_PATH}" region_code "US")"

export HALLOWEEN_YOUTUBE_SEARCH_DAILY_BUDGET
HALLOWEEN_YOUTUBE_SEARCH_DAILY_BUDGET="$(vault_optional_field "${HALLOWEEN_YOUTUBE_SECRET_PATH}" search_daily_budget "90")"

export HALLOWEEN_YOUTUBE_SEARCH_ACCOUNT_LIMIT
HALLOWEEN_YOUTUBE_SEARCH_ACCOUNT_LIMIT="$(vault_optional_field "${HALLOWEEN_YOUTUBE_SECRET_PATH}" search_account_limit "10")"

export HALLOWEEN_YOUTUBE_VAULT_AWS_AUTH_ROLE
HALLOWEEN_YOUTUBE_VAULT_AWS_AUTH_ROLE="${HALLOWEEN_YOUTUBE_VAULT_AWS_AUTH_ROLE:-halloween-api}"

export HALLOWEEN_YOUTUBE_VAULT_SECRET_PATH
HALLOWEEN_YOUTUBE_VAULT_SECRET_PATH="${HALLOWEEN_YOUTUBE_SECRET_PATH}"

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
