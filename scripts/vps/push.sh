#!/usr/bin/env bash
# Run on your computer: copies the lab to the VPS of the trading bot and installs the daily plan there.
#
#   VPS=user@host bash scripts/vps/push.sh
#
# What goes to the server (REMOTE_DIR, default /opt/ResearchAssetsManagement):
#   * the code of the last commit (git archive: the server needs no GitHub access);
#   * data/user (the settings of «Мой счёт», the stop list) and data/cache (TQBR weeks, ISS/Yahoo/CBR series, the ML
#     forecasts: the first plan then takes seconds, and a source the server cannot reach falls back to these copies);
#   * the part of server-analytic-system's data the plan reads (dividends, smart-lab reports, the share snapshots,
#     the bond portfolios, T-Invest's bond list with the broker's risk levels) into REMOTE_DIR/sas-data.
# Then it runs scripts/vps/install.sh on the server with sudo (it asks for the password there unless sudoers lets the
# user run `bash REMOTE_DIR/scripts/vps/install.sh`, `mkdir -p REMOTE_DIR` and `chown <user> REMOTE_DIR` without one).
# Run it again after a change in the lab or to refresh the dividends and reports.
set -Eeuo pipefail

VPS="${VPS:?set VPS=user@host}"
REMOTE_DIR="${REMOTE_DIR:-/opt/ResearchAssetsManagement}"
SAS_DATA="${SAS_DATA:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/../server-analytic-system/data}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SSH="${SSH:-ssh}"

log() { printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }

cd "${ROOT}"
git diff --quiet HEAD -- src pyproject.toml scripts || log "WARNING: uncommitted changes in src/, scripts/ or pyproject.toml are NOT sent (only the last commit)"

log "Code of $(git rev-parse --short HEAD) -> ${VPS}:${REMOTE_DIR}"
"${SSH}" "${VPS}" "sudo mkdir -p '${REMOTE_DIR}' && sudo chown \"\$(id -un)\" '${REMOTE_DIR}'"
git archive --format=tar HEAD src pyproject.toml scripts README.md | "${SSH}" "${VPS}" "tar -x -C '${REMOTE_DIR}'"
git rev-parse HEAD | "${SSH}" "${VPS}" "cat > '${REMOTE_DIR}/COMMIT'"

log "Settings and cache (data/user, data/cache)"
"${SSH}" "${VPS}" "mkdir -p '${REMOTE_DIR}/data/user' '${REMOTE_DIR}/data/cache' '${REMOTE_DIR}/sas-data'"
[[ -d data/user ]] && rsync -az data/user/ "${VPS}:${REMOTE_DIR}/data/user/"
rsync -az data/cache/ "${VPS}:${REMOTE_DIR}/data/cache/"

if [[ -d "${SAS_DATA}" ]]; then
  log "server-analytic-system data (${SAS_DATA})"
  rsync -az --prune-empty-dirs \
    --include='tbank_dividends.csv' --include='smartlab_financials.csv' --include='smartlab_quarterly.csv' \
    --include='shares.json' --include='bonds_data.json' --include='stock_snapshot_*/' --include='stock_snapshot_*/**' \
    --include='notebook_reports/' --include='notebook_reports/bonds/' --include='notebook_reports/bonds/portfolios/' \
    --include='notebook_reports/bonds/portfolios/*.csv' --exclude='*' \
    "${SAS_DATA}/" "${VPS}:${REMOTE_DIR}/sas-data/"
else
  log "WARNING: no ${SAS_DATA}: the plan runs without the dividends and reports (price returns, no E/P and FCF/P)"
fi

log "Installing on the server (sudo)"
"${SSH}" -t "${VPS}" "sudo bash '${REMOTE_DIR}/scripts/vps/install.sh'"  # it finds REMOTE_DIR from its own path
