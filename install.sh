#!/usr/bin/env bash
# SynthMK installer — puts the runner, flows, and Checkmk local-check into
# predictable locations on a monitored host. Idempotent, secret-free, and
# reversible. No build step: SynthMK is plain Python + a shell local-check.
#
#   sudo ./install.sh                 # install to /opt/synthmk + agent local dir
#   sudo ./install.sh --uninstall     # remove both
#   ./install.sh --dry-run            # print actions, change nothing
#   DESTDIR=/tmp/stage ./install.sh   # stage into a prefix (for testing/packaging)
#
# Layout created:
#   $SYNTHMK_HOME/{runner,flows,checkmk,docs,README.md,VERSION}
#   $CMK_LOCAL_DIR/synthmk_check.sh  (executable; the runner output IS the protocol)
set -uo pipefail

SYNTHMK_HOME="${SYNTHMK_HOME:-/opt/synthmk}"
# 300/ = Checkmk agent runs the check every 300s. Bare local/ = default interval.
CMK_LOCAL_DIR="${CMK_LOCAL_DIR:-/usr/lib/check_mk_agent/local/300}"
DESTDIR="${DESTDIR:-}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY=0
ACTION="install"
for arg in "$@"; do
  case "$arg" in
    --uninstall) ACTION="uninstall" ;;
    --dry-run)   DRY=1 ;;
    -h|--help)   grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

# Never copy secrets, caches, VCS metadata, or recorded screenshots.
EXCLUDES=(--exclude='.git' --exclude='__pycache__' --exclude='.ruff_cache'
          --exclude='*.pyc' --exclude='.env' --exclude='*.env'
          --exclude='screenshots' --exclude='node_modules' --exclude='dist')

run() {
  if [[ "$DRY" -eq 1 ]]; then
    echo "DRY: $*"
  else
    "$@"
  fi
}

home_path="${DESTDIR}${SYNTHMK_HOME}"
check_dir="${DESTDIR}${CMK_LOCAL_DIR}"
check_path="${check_dir}/synthmk_check.sh"

if [[ "$ACTION" == "uninstall" ]]; then
  echo "== SynthMK uninstall =="
  run rm -f "$check_path"
  run rm -rf "$home_path"
  echo "removed $check_path and $home_path"
  exit 0
fi

echo "== SynthMK install (version $(cat "$HERE/VERSION" 2>/dev/null || echo '?')) =="
echo "  home:       $home_path"
echo "  local check: $check_path"

run mkdir -p "$home_path" "$check_dir"

# Copy the runtime payload (runner, flows, checkmk skeleton, docs, top-level files).
for part in runner flows checkmk docs README.md VERSION; do
  src="$HERE/$part"
  [[ -e "$src" ]] || { echo "  skip (missing): $part"; continue; }
  if [[ -d "$src" ]]; then
    run rsync -a "${EXCLUDES[@]}" "$src" "$home_path/"
  else
    run cp "$src" "$home_path/"
  fi
done

# Install the local check pointing SYNTHMK_HOME at the installed payload.
run cp "$HERE/checkmk/synthmk_check.sh" "$check_path"
run chmod +x "$check_path"

echo "== done =="
echo "Configure flows in $SYNTHMK_HOME/checkmk/synthmk_check.sh (SYNTHMK_FLOW_FILES),"
echo "then verify:  $CMK_LOCAL_DIR/synthmk_check.sh"
