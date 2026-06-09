#!/usr/bin/env bash
# SynthMK runner-node — official Checkmk agent + TLS registration (one-time).
#
# Upgrades the node's agent transport from plaintext socat to the official,
# version-matched Checkmk agent with the TLS agent controller:
#
#   docker exec synthmk-runner bash /opt/synthmk/runner-node/register_agent.sh \
#       --server cmk:8000 --site cmk --user cmkadmin --host synthmk-runner
#   (password read from $CMK_PASSWORD or prompted)
#
# What it does, in order:
#   1. downloads the site's own agent .deb (so versions always match the server)
#   2. installs it (the agent natively serves our spool dir — no glue needed)
#   3. registers the TLS controller against the site (cmk-agent-ctl register)
#
# Afterwards restart the container with SYNTHMK_AGENT_MODE=official and mount a
# volume at /var/lib/cmk-agent to persist the registration. The Checkmk host
# must already exist (with "agent" as its monitoring agent) and the agent
# receiver port (default 8000) must be reachable from this node.
set -euo pipefail

SERVER="" SITE="" USER_="" HOSTNAME_="$(hostname)" PASSWORD="${CMK_PASSWORD:-}"
UI_PORT_DEFAULT=5000

usage() {
  grep '^#' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server)   SERVER="$2"; shift 2 ;;   # host:agent-receiver-port (e.g. cmk:8000)
    --ui)       UI="$2"; shift 2 ;;       # host:ui-port for the .deb download (default <server-host>:5000)
    --site)     SITE="$2"; shift 2 ;;
    --user)     USER_="$2"; shift 2 ;;
    --host)     HOSTNAME_="$2"; shift 2 ;;
    --password) PASSWORD="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$SERVER" && -n "$SITE" && -n "$USER_" ]] || usage
if [[ -z "$PASSWORD" ]]; then
  read -r -s -p "Password for $USER_: " PASSWORD; echo
fi

SERVER_HOST="${SERVER%%:*}"
UI="${UI:-$SERVER_HOST:$UI_PORT_DEFAULT}"

echo "== 1/3 download version-matched agent package from http://$UI/$SITE =="
DEB=/tmp/check-mk-agent.deb
curl -fsS -o "$DEB" "http://$UI/$SITE/check_mk/agents/check-mk-agent_$(
  curl -fsS "http://$UI/$SITE/check_mk/api/1.0/version" \
    -H "Authorization: Bearer $USER_ $PASSWORD" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["versions"]["checkmk"].split(".cre")[0])'
)-1_all.deb" || {
  # Fallback: directory listing name may differ across patch levels; grab the
  # generic agent deb the site publishes.
  curl -fsS -o "$DEB" "http://$UI/$SITE/check_mk/agents/check-mk-agent_all.deb" 2>/dev/null ||
  { echo "FATAL: could not download the agent .deb from http://$UI/$SITE/check_mk/agents/"; exit 1; }
}

echo "== 2/3 install agent (serves $SYNTHMK_SPOOL natively) =="
export DEBIAN_FRONTEND=noninteractive
dpkg -i "$DEB" >/dev/null || apt-get install -fy >/dev/null
rm -f "$DEB"

echo "== 3/3 register TLS controller against $SERVER (site $SITE, host $HOSTNAME_) =="
# No systemd in a container: provide the agent socket the controller expects
# (the same thing check-mk-agent.socket does on a systemd host).
if [[ ! -S /run/check-mk-agent.socket ]]; then
  socat "UNIX-LISTEN:/run/check-mk-agent.socket,fork,mode=666" \
        "EXEC:/usr/bin/check_mk_agent" >/var/log/synthmk-agent-socket.log 2>&1 &
  sleep 1
fi
cmk-agent-ctl register \
  --server "$SERVER" --site "$SITE" \
  --user "$USER_" --password "$PASSWORD" \
  --hostname "$HOSTNAME_" --trust-cert

echo
echo "Registered. Restart the container with SYNTHMK_AGENT_MODE=official"
echo "(and a volume on /var/lib/cmk-agent to persist the registration)."
