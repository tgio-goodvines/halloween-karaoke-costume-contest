#!/usr/bin/env bash
set -euo pipefail

GOODVINES_HOST="${GOODVINES_HOST:-appg-v.com}"
GOODVINES_HEALTH_URL="${GOODVINES_HEALTH_URL:-http://127.0.0.1/health}"

curl -fsS --max-time 10 -H "Host: ${GOODVINES_HOST}" "${GOODVINES_HEALTH_URL}" >/dev/null
