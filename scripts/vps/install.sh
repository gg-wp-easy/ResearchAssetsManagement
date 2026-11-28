#!/usr/bin/env bash
# Runs on the VPS (scripts/vps/push.sh calls it with sudo): the lab's environment and the daily plan for the bot.
#
#   * REMOTE_DIR/.venv with the lab (pip install -e .);
#   * ram-plan.service: `ram account --trend main_guard --export <the bot's state>/book_plan.json` as the bot's user,
#     with RAM_SAS_DATA=REMOTE_DIR/sas-data; ram-plan.timer runs it every day at 07:30 MSK and after a boot;
#   * a first run now, so the bot has a plan at once.
# The bot (trade-t-bot) reads the file named in its config.toml: [portfolio] plan_file.
set -Eeuo pipefail

REMOTE_DIR="${REMOTE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"  # the lab this script came with
BOT_SERVICE="${BOT_SERVICE:-trade-t-bot}"
PLAN_ARGS="${PLAN_ARGS:---trend main_guard --limit 0.25}"

log() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[[ "${EUID}" -eq 0 ]] || fail "run with sudo"
BOT_DIR="$(systemctl show "${BOT_SERVICE}" -p WorkingDirectory --value 2>/dev/null || true)"
[[ -n "${BOT_DIR}" && -d "${BOT_DIR}" ]] || fail "the ${BOT_SERVICE} service has no WorkingDirectory: set BOT_SERVICE=..."
RUN_USER="$(systemctl show "${BOT_SERVICE}" -p User --value 2>/dev/null || true)"
RUN_USER="${RUN_USER:-$(stat -c '%U' "${BOT_DIR}")}"
PLAN_FILE="${PLAN_FILE:-${BOT_DIR}/state/book_plan.json}"
PYTHON="${PYTHON:-python3}"
"${PYTHON}" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail "the lab needs Python 3.11+: set PYTHON=python3.12"

log "Environment in ${REMOTE_DIR}/.venv (user ${RUN_USER})"
chown -R "${RUN_USER}:$(id -gn "${RUN_USER}")" "${REMOTE_DIR}"
sudo -u "${RUN_USER}" "${PYTHON}" -m venv "${REMOTE_DIR}/.venv"
sudo -u "${RUN_USER}" "${REMOTE_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip
sudo -u "${RUN_USER}" "${REMOTE_DIR}/.venv/bin/python" -m pip install --quiet -e "${REMOTE_DIR}"

log "ram-plan.service and ram-plan.timer -> ${PLAN_FILE}"
cat > /etc/systemd/system/ram-plan.service <<EOF
[Unit]
Description=The book of sleeves' plan for the trading bot (ResearchAssetsManagement)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${REMOTE_DIR}
Environment=RAM_SAS_DATA=${REMOTE_DIR}/sas-data
ExecStart=${REMOTE_DIR}/.venv/bin/ram account ${PLAN_ARGS} --export ${PLAN_FILE}
TimeoutStartSec=1800
Nice=10
EOF
cat > /etc/systemd/system/ram-plan.timer <<EOF
[Unit]
Description=The book of sleeves' plan every day at 07:30 MSK

[Timer]
OnCalendar=*-*-* 07:30:00 Europe/Moscow
OnBootSec=10min
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now ram-plan.timer

log "First plan (up to a few minutes without a warm cache)"
if systemctl start ram-plan.service; then
  journalctl -u ram-plan.service -n 5 --no-pager || true
  log "Done. In ${BOT_DIR}/config.toml:"
  printf '  [portfolio]\n  plan_file = "%s"\n  broker_account = "<the IIS id from /accounts>"\n' "${PLAN_FILE}"
  printf 'then restart %s. Logs: journalctl -u ram-plan.service; the next runs: systemctl list-timers ram-plan.timer\n' "${BOT_SERVICE}"
else
  journalctl -u ram-plan.service -n 40 --no-pager || true
  fail "the first plan failed (see above); the timer will try again at 07:30 MSK"
fi
