#!/bin/bash
set -euo pipefail

REPO="/home/ubuntu/my-crypto-bot"
LOG_DIR="${REPO}/logs"
LOG_FILE="${LOG_DIR}/trade.log"
LOCK_FILE="/tmp/my-crypto-bot-trade.lock"

mkdir -p "${LOG_DIR}"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "[SKIP] $(date -Is) trade run in progress" >> "${LOG_FILE}"
  exit 0
fi

{
  echo "========== TRADE $(date -Is) =========="
  cd "${REPO}"
  git pull --ff-only origin main
  . "${REPO}/env.sh"
  "${REPO}/venv/bin/pip" install -q -r requirements.txt
  "${REPO}/venv/bin/python" "${REPO}/bitcoin_trade.py"
  echo "[DONE] $(date -Is)"
} >> "${LOG_FILE}" 2>&1
