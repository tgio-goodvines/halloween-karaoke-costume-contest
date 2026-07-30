#!/usr/bin/env bash
set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/root/goodvines-vault-init.json}"
YOUTUBE_SECRET_PATH="${YOUTUBE_SECRET_PATH:-appsecrets/halloween_youtube}"
HALLOWEEN_APP_SECRET_PATH="${HALLOWEEN_APP_SECRET_PATH:-appsecrets/halloween_app}"
YOUTUBE_VAULT_ROLE="${YOUTUBE_VAULT_ROLE:-halloween-api}"
YOUTUBE_VAULT_POLICY="${YOUTUBE_VAULT_POLICY:-halloween-api-policy}"
BOUND_IAM_PRINCIPAL_ARN="${BOUND_IAM_PRINCIPAL_ARN:-arn:aws:iam::152923357640:role/GoodVinesEC2SSMRole}"

if [[ ! -r "${VAULT_INIT_FILE}" ]]; then
  echo "Vault init material is unavailable on this host." >&2
  exit 1
fi

export VAULT_ADDR
export VAULT_TOKEN
VAULT_TOKEN="$(jq -er '.root_token' "${VAULT_INIT_FILE}")"

policy_file="$(mktemp)"
secret_file="$(mktemp)"
trap 'rm -f "${policy_file}" "${secret_file}"' EXIT

cat >"${policy_file}" <<EOF
path "${YOUTUBE_SECRET_PATH}" {
  capabilities = ["create", "read", "update"]
}
EOF

vault policy write "${YOUTUBE_VAULT_POLICY}" "${policy_file}" >/dev/null
vault write "auth/aws/role/${YOUTUBE_VAULT_ROLE}" \
  auth_type=iam \
  bound_iam_principal_arn="${BOUND_IAM_PRINCIPAL_ARN}" \
  policies="${YOUTUBE_VAULT_POLICY}" \
  token_ttl=1h \
  token_max_ttl=4h >/dev/null

existing_secret="$(
  vault read -format=json "${YOUTUBE_SECRET_PATH}" 2>/dev/null \
    | jq -c '.data // {}' \
    || printf '{}'
)"
fallback_api_key="$(
  vault read -format=json "${HALLOWEEN_APP_SECRET_PATH}" \
    | jq -r '.data.youtube_api_key // empty'
)"

jq -n \
  --argjson existing "${existing_secret}" \
  --arg fallback_api_key "${fallback_api_key}" \
  '$existing
   | .enabled = (.enabled // "false")
   | .api_key = (if (.api_key // "") == "" then $fallback_api_key else .api_key end)
   | .oauth_client_id = (.oauth_client_id // "")
   | .oauth_client_secret = (.oauth_client_secret // "")
   | .oauth_refresh_token = (.oauth_refresh_token // "")
   | .region_code = (.region_code // "US")
   | .search_daily_budget = (.search_daily_budget // "90")
   | .search_account_limit = (.search_account_limit // "10")' >"${secret_file}"

vault write "${YOUTUBE_SECRET_PATH}" "@${secret_file}" >/dev/null

vault read "auth/aws/role/${YOUTUBE_VAULT_ROLE}" >/dev/null
vault read "${YOUTUBE_SECRET_PATH}" >/dev/null
echo "Halloween YouTube Vault role, policy, and dedicated secret path are ready."
