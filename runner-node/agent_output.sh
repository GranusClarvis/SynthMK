#!/usr/bin/env bash
# SynthMK runner-node agent transport.
#
# socat execs this on every Checkmk poll. It prints a minimal-but-valid Checkmk
# agent payload: a <<<check_mk>>> identity section, an <<<uptime>>> section so the
# node looks like a healthy host, and then every fresh spool file produced by the
# scheduler (each already carries its own <<<local>>> / piggyback section headers).
#
# This is the dependency-free transport used by the appliance and the LAN lab.
# For production you can instead install the version-matched official Checkmk
# agent + cmk-agent-ctl (TLS) — see runner-node/README.md.
set -uo pipefail

SPOOL="${SYNTHMK_SPOOL:-/var/lib/check_mk_agent/spool}"
# socat's EXEC child doesn't inherit the entrypoint's env, so fall back to the
# VERSION file shipped in the image.
SYNTHMK_HOME="${SYNTHMK_HOME:-/opt/synthmk}"
VERSION="${SYNTHMK_VERSION:-$(cat "$SYNTHMK_HOME/VERSION" 2>/dev/null || echo 0.0.0)}"

printf '<<<check_mk>>>\n'
printf 'Version: synthmk-runner-%s\n' "$VERSION"
printf 'AgentOS: linux\n'
printf 'Hostname: %s\n' "$(hostname)"

printf '<<<uptime>>>\n'
awk '{print $1}' /proc/uptime 2>/dev/null || echo 0

# Emit fresh synthetic sections. A "<maxage>_" filename prefix marks a max age in
# seconds; an older file is skipped so Checkmk flags the service stale instead of
# showing an outdated result (the scheduler sets maxage = interval * 3).
now="$(date +%s)"
shopt -s nullglob
for f in "$SPOOL"/*; do
  [[ -f "$f" ]] || continue
  base="$(basename "$f")"
  if [[ "$base" =~ ^([0-9]+)_ ]]; then
    maxage="${BASH_REMATCH[1]}"
    mtime="$(stat -c %Y "$f" 2>/dev/null || echo 0)"
    (( now - mtime > maxage )) && continue
  fi
  cat "$f"
done
