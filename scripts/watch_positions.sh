#!/bin/bash
set -euo pipefail

REPO="/home/ubuntu/my-crypto-bot"
LOG_DIR="${REPO}/logs"
LOG_FILE="${LOG_DIR}/watch.log"
LOCK_FILE="/tmp/my-crypto-bot-watch.lock"

mkdir -p "${LOG_DIR}"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  exit 0
fi

{
  cd "${REPO}"
  . "${REPO}/env.sh"
  "${REPO}/venv/bin/python" "${REPO}/position_watcher.py"
} >> "${LOG_FILE}" 2>&1
