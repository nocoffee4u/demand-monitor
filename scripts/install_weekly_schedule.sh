#!/usr/bin/env bash
# Install a macOS launchd job that runs the demand pipeline weekly.
# Default: Sundays at 09:15 local time.
#
# Usage:
#   ./scripts/install_weekly_schedule.sh
#   ./scripts/install_weekly_schedule.sh --uninstall
#   WEEKDAY=1 HOUR=8 MINUTE=30 ./scripts/install_weekly_schedule.sh
#
# Weekday: 0=Sunday … 6=Saturday (launchd convention).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.demandmonitor.weekly"
PLIST_DIR="${HOME}/Library/LaunchAgents"
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"
LOG_DIR="${ROOT}/out/logs"
PYTHON_BIN="${ROOT}/venv/bin/python3"
RUN_SCRIPT="${ROOT}/run_all.sh"

WEEKDAY="${WEEKDAY:-0}"
HOUR="${HOUR:-9}"
MINUTE="${MINUTE:-15}"

uninstall() {
  if launchctl list 2>/dev/null | grep -q "${LABEL}"; then
    launchctl unload "${PLIST_PATH}" 2>/dev/null || true
  fi
  # modern macOS
  launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
  rm -f "${PLIST_PATH}"
  echo "Removed ${LABEL}"
  exit 0
}

if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall
fi

if [[ ! -x "${RUN_SCRIPT}" ]]; then
  echo "ERROR: ${RUN_SCRIPT} not executable"
  exit 1
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "WARN: ${PYTHON_BIN} missing — plist will use /usr/bin/env bash + system python via run_all.sh"
fi

mkdir -p "${PLIST_DIR}" "${LOG_DIR}"

# Prefer project venv by putting it first on PATH inside the job.
cat > "${PLIST_PATH}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${RUN_SCRIPT}</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${ROOT}/venv/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>REDDIT_BACKEND</key>
    <string>pullpush</string>
    <key>REDDIT_DELAY</key>
    <string>5</string>
    <key>WAIT_FOR_PULLPUSH</key>
    <string>0</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>${WEEKDAY}</integer>
    <key>Hour</key>
    <integer>${HOUR}</integer>
    <key>Minute</key>
    <integer>${MINUTE}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/weekly.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/weekly.stderr.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
EOF

# Reload
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl unload "${PLIST_PATH}" 2>/dev/null || true
if launchctl bootstrap "gui/$(id -u)" "${PLIST_PATH}" 2>/dev/null; then
  :
elif launchctl load "${PLIST_PATH}" 2>/dev/null; then
  :
else
  echo "ERROR: could not load launch agent. Try: launchctl load ${PLIST_PATH}"
  exit 1
fi

echo "Installed weekly schedule: ${LABEL}"
echo "  when: weekday=${WEEKDAY} (0=Sun) at ${HOUR}:$(printf '%02d' "${MINUTE}")"
echo "  runs: ${RUN_SCRIPT}"
echo "  logs: ${LOG_DIR}/weekly.*.log"
echo "  plist: ${PLIST_PATH}"
echo
echo "Uninstall: ./scripts/install_weekly_schedule.sh --uninstall"
echo "Test now:  launchctl start ${LABEL}"
echo "           (or: cd \"${ROOT}\" && ./run_all.sh)"
echo
echo "Sheets export: ensure GOOGLE_SERVICE_ACCOUNT_JSON and"
echo "GOOGLE_SHEETS_SPREADSHEET_ID are set in ${ROOT}/.env"
echo "(see docs/sheets_setup.md). run_all.sh loads .env automatically."
