#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-halloween-party}"
APP_USER="${APP_USER:-halloween}"
APP_GROUP="${APP_GROUP:-halloween}"
APP_ROOT="${APP_ROOT:-/opt/halloween}"
APP_REPO_DIR="${APP_REPO_DIR:-${APP_ROOT}/app}"
RELEASES_DIR="${RELEASES_DIR:-${APP_ROOT}/releases}"
CURRENT_LINK="${CURRENT_LINK:-${APP_ROOT}/current}"
LOG_DIR="${LOG_DIR:-/var/log/halloween-party}"
DEPLOY_SHA="${DEPLOY_SHA:?DEPLOY_SHA is required}"
REPO_REF="${REPO_REF:-main}"
REPO_URL="${REPO_URL:-https://github.com/tgio-goodvines/halloween-karaoke-costume-contest.git}"
APP_PORT="${APP_PORT:-8081}"
VAULT_ADDR="${VAULT_ADDR:-http://172.31.118.0:8200}"
VAULT_AWS_AUTH_ROLE="${VAULT_AWS_AUTH_ROLE:-goodvines-api}"
GITHUB_SECRET_PATH="${GITHUB_SECRET_PATH:-appsecrets/halloween_github}"
GOODVINES_HOST="${GOODVINES_HOST:-appg-v.com}"
GOODVINES_HEALTH_URL="${GOODVINES_HEALTH_URL:-http://127.0.0.1/health}"
HALLOWEEN_LOCAL_HEALTH_URL="${HALLOWEEN_LOCAL_HEALTH_URL:-http://127.0.0.1:${APP_PORT}/live-display}"
NGINX_CONF_PATH="${NGINX_CONF_PATH:-/etc/nginx/conf.d/halloween.conf}"
LOCK_FILE="${LOCK_FILE:-/var/lock/halloween-deploy.lock}"

log() {
  printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"
}

require_command() {
  local command_name="$1"
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Required command not found: ${command_name}" >&2
    exit 1
  fi
}

goodvines_health_check() {
  curl -fsS --max-time 10 -H "Host: ${GOODVINES_HOST}" "${GOODVINES_HEALTH_URL}" >/dev/null
}

rollback() {
  local failed_line="${1:-unknown}"
  set +e
  log "Deployment failed at line ${failed_line}; rolling back Halloween only."

  if [ -n "${PREVIOUS_CURRENT:-}" ] && [ -d "${PREVIOUS_CURRENT}" ]; then
    ln -sfn "${PREVIOUS_CURRENT}" "${CURRENT_LINK}"
    systemctl restart "${APP_NAME}" || true
  fi

  if [ "${HAD_NGINX_CONF:-false}" = "true" ] && [ -f "${NGINX_BACKUP:-}" ]; then
    cp -f "${NGINX_BACKUP}" "${NGINX_CONF_PATH}"
  elif [ "${HAD_NGINX_CONF:-false}" = "false" ]; then
    rm -f "${NGINX_CONF_PATH}"
  fi

  if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx || true
  else
    log "nginx config is invalid after rollback attempt; leaving nginx unreloaded."
  fi

  if goodvines_health_check; then
    log "GoodVines health check passed after rollback."
  else
    log "GoodVines health check failed after rollback."
  fi

  exit 1
}

main() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "This deploy script must run as root through SSM." >&2
    exit 1
  fi

  require_command curl
  require_command git
  require_command nginx
  require_command python3.11
  require_command systemctl
  require_command vault
  require_command ssh-keyscan
  require_command ss

  exec 9>"${LOCK_FILE}"
  if ! flock -n 9; then
    echo "Another Halloween deployment is already running." >&2
    exit 1
  fi

  PREVIOUS_CURRENT=""
  if [ -L "${CURRENT_LINK}" ]; then
    PREVIOUS_CURRENT="$(readlink -f "${CURRENT_LINK}" || true)"
  fi

  HAD_NGINX_CONF=false
  NGINX_BACKUP="$(mktemp /tmp/halloween-nginx.XXXXXX.conf)"
  if [ -f "${NGINX_CONF_PATH}" ]; then
    HAD_NGINX_CONF=true
    cp -f "${NGINX_CONF_PATH}" "${NGINX_BACKUP}"
  fi

  trap 'rollback "$LINENO"' ERR

  log "Checking shared nginx and GoodVines health before Halloween deploy."
  systemctl is-active --quiet nginx
  goodvines_health_check

  if ss -ltnp "sport = :${APP_PORT}" | grep -q LISTEN; then
    if ! systemctl is-active --quiet "${APP_NAME}"; then
      echo "Port ${APP_PORT} is already listening but ${APP_NAME} is not active; aborting." >&2
      ss -ltnp "sport = :${APP_PORT}" || true
      exit 1
    fi
  fi

  if ! getent group "${APP_GROUP}" >/dev/null 2>&1; then
    groupadd --system "${APP_GROUP}"
  fi

  if ! id "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --home-dir "${APP_ROOT}" --gid "${APP_GROUP}" --shell /sbin/nologin "${APP_USER}"
  fi

  install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${APP_ROOT}" "${APP_REPO_DIR}" "${RELEASES_DIR}" "${LOG_DIR}"

  log "Fetching GitHub deploy credentials from Vault path ${GITHUB_SECRET_PATH}."
  vault_token="$(VAULT_ADDR="${VAULT_ADDR}" vault login -method=aws -token-only role="${VAULT_AWS_AUTH_ROLE}")"
  github_token="$(VAULT_ADDR="${VAULT_ADDR}" VAULT_TOKEN="${vault_token}" vault kv get -field=token "${GITHUB_SECRET_PATH}" 2>/dev/null || true)"
  deploy_key="$(VAULT_ADDR="${VAULT_ADDR}" VAULT_TOKEN="${vault_token}" vault kv get -field=private_key "${GITHUB_SECRET_PATH}" 2>/dev/null || true)"
  vault_repo_url="$(VAULT_ADDR="${VAULT_ADDR}" VAULT_TOKEN="${vault_token}" vault kv get -field=repo_url "${GITHUB_SECRET_PATH}" 2>/dev/null || true)"
  github_username="$(VAULT_ADDR="${VAULT_ADDR}" VAULT_TOKEN="${vault_token}" vault kv get -field=username "${GITHUB_SECRET_PATH}" 2>/dev/null || true)"
  known_hosts_from_vault="$(VAULT_ADDR="${VAULT_ADDR}" VAULT_TOKEN="${vault_token}" vault kv get -field=known_hosts "${GITHUB_SECRET_PATH}" 2>/dev/null || true)"

  if [ -n "${vault_repo_url}" ] && [ "${REPO_URL}" = "https://github.com/tgio-goodvines/halloween-karaoke-costume-contest.git" ]; then
    REPO_URL="${vault_repo_url}"
  fi

  if [ -z "${github_token}" ] && [ -z "${deploy_key}" ]; then
    echo "Vault path ${GITHUB_SECRET_PATH} must contain either token or private_key." >&2
    exit 1
  fi

  git_credential_dir="$(mktemp -d /tmp/halloween-git-credentials.XXXXXX)"
  cleanup_git_credentials() {
    rm -rf "${git_credential_dir}"
  }
  trap 'cleanup_git_credentials' EXIT
  trap 'rollback "$LINENO"' ERR

  git_auth_mode="token"
  if [ -n "${github_token}" ]; then
    github_username="${github_username:-x-access-token}"
    printf '%s' "${github_token}" >"${git_credential_dir}/token"
    chmod 0600 "${git_credential_dir}/token"
    cat >"${git_credential_dir}/askpass" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  *Username*) echo "${GITHUB_USERNAME:-x-access-token}" ;;
  *Password*) cat "${GITHUB_TOKEN_FILE}" ;;
  *) echo "" ;;
esac
EOF
    chmod 0700 "${git_credential_dir}/askpass"
  else
    git_auth_mode="ssh"
    printf '%s\n' "${deploy_key}" >"${git_credential_dir}/deploy_key"
    chmod 0600 "${git_credential_dir}/deploy_key"

    if [ -n "${known_hosts_from_vault}" ]; then
      printf '%s\n' "${known_hosts_from_vault}" >"${git_credential_dir}/known_hosts"
    else
      ssh-keyscan github.com >"${git_credential_dir}/known_hosts" 2>/dev/null
    fi
    chmod 0644 "${git_credential_dir}/known_hosts"
  fi

  chown -R "${APP_USER}:${APP_GROUP}" "${git_credential_dir}"

  run_git_with_auth() {
    if [ "${git_auth_mode}" = "token" ]; then
      sudo -u "${APP_USER}" env \
        GIT_ASKPASS="${git_credential_dir}/askpass" \
        GIT_TERMINAL_PROMPT=0 \
        GITHUB_USERNAME="${github_username}" \
        GITHUB_TOKEN_FILE="${git_credential_dir}/token" \
        git "$@"
      return
    fi

    sudo -u "${APP_USER}" env \
      GIT_SSH_COMMAND="ssh -i ${git_credential_dir}/deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=${git_credential_dir}/known_hosts" \
      GIT_TERMINAL_PROMPT=0 \
      git "$@"
  }

  if [ ! -d "${APP_REPO_DIR}/.git" ]; then
    log "Cloning Halloween repo."
    find "${APP_REPO_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    run_git_with_auth clone "${REPO_URL}" "${APP_REPO_DIR}"
  fi

  log "Fetching ${REPO_REF} and checking out ${DEPLOY_SHA}."
  run_git_with_auth -C "${APP_REPO_DIR}" fetch origin "${REPO_REF}"
  sudo -u "${APP_USER}" git -C "${APP_REPO_DIR}" cat-file -e "${DEPLOY_SHA}^{commit}"
  sudo -u "${APP_USER}" git -C "${APP_REPO_DIR}" checkout --detach "${DEPLOY_SHA}"

  release_dir="${RELEASES_DIR}/${DEPLOY_SHA}"
  rm -rf "${release_dir}"
  install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${release_dir}"
  sudo -u "${APP_USER}" git -C "${APP_REPO_DIR}" archive "${DEPLOY_SHA}" | tar -x -C "${release_dir}"
  chown -R "${APP_USER}:${APP_GROUP}" "${release_dir}"
  chmod 0755 "${release_dir}/deploy/ec2_deploy_from_github.sh" "${release_dir}/deploy/start_halloween.sh" "${release_dir}/deploy/validate_goodvines_health.sh"

  log "Creating Python virtual environment for ${DEPLOY_SHA}."
  sudo -u "${APP_USER}" python3.11 -m venv "${release_dir}/.venv"
  sudo -u "${APP_USER}" "${release_dir}/.venv/bin/python" -m pip install --upgrade pip wheel
  sudo -u "${APP_USER}" "${release_dir}/.venv/bin/python" -m pip install -r "${release_dir}/requirements.txt"

  log "Installing Halloween systemd and nginx config."
  install -m 0644 "${release_dir}/deploy/halloween-party.service" /etc/systemd/system/halloween-party.service
  install -m 0644 "${release_dir}/deploy/nginx-halloween.conf" "${NGINX_CONF_PATH}"

  ln -sfn "${release_dir}" "${CURRENT_LINK}"
  chown -h "${APP_USER}:${APP_GROUP}" "${CURRENT_LINK}"

  systemctl daemon-reload
  systemctl enable "${APP_NAME}"
  systemctl restart "${APP_NAME}"

  log "Waiting for Halloween local app response."
  for _ in $(seq 1 24); do
    if curl -fsS --max-time 10 "${HALLOWEEN_LOCAL_HEALTH_URL}" >/dev/null; then
      break
    fi
    sleep 5
  done
  curl -fsS --max-time 10 "${HALLOWEEN_LOCAL_HEALTH_URL}" >/dev/null

  nginx -t
  systemctl reload nginx

  log "Checking Halloween host routing and GoodVines health after nginx reload."
  for _ in $(seq 1 12); do
    if curl -fsS --max-time 10 -H 'Host: tnq-halloween.com' "http://127.0.0.1/live-display" >/dev/null; then
      break
    fi
    sleep 2
  done
  curl -fsS --max-time 10 -H 'Host: tnq-halloween.com' "http://127.0.0.1/live-display" >/dev/null
  goodvines_health_check

  actual_sha="$(sudo -u "${APP_USER}" git -C "${APP_REPO_DIR}" rev-parse HEAD)"
  test "${actual_sha}" = "${DEPLOY_SHA}"
  log "Halloween deploy complete: ${actual_sha}"

  trap - ERR
  cleanup_git_credentials
}

main "$@"
