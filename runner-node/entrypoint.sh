#!/usr/bin/env bash
# SynthMK runner-node entrypoint.
#
# Starts three things and keeps the agent transport in the foreground as PID 1:
#   1. screenshot server (shot_server.py, token-auth)   — as pwuser
#   2. flow scheduler    (scheduler.py, worker pool)    — as pwuser
#   3. agent transport                                  — socat (lab) or the
#      official Checkmk agent controller (TLS, production; see register_agent.sh)
#
# Privilege model: the container may start as root (needed for the official
# agent controller and for chown of mounted volumes), but everything that
# touches a BROWSER or serves HTTP drops to the unprivileged 'pwuser' shipped
# in the Playwright base image — a compromised page never runs code as root.
set -uo pipefail

SYNTHMK_HOME="${SYNTHMK_HOME:-/opt/synthmk}"
SHOT_DIR="${SYNTHMK_SHOT_DIR:-$SYNTHMK_HOME/screenshots}"
SHOT_PORT="${SYNTHMK_SHOT_PORT:-9180}"
AGENT_PORT="${SYNTHMK_AGENT_PORT:-6556}"
AGENT_MODE="${SYNTHMK_AGENT_MODE:-socat}"     # socat | official
export SYNTHMK_VERSION="${SYNTHMK_VERSION:-$(cat "$SYNTHMK_HOME/VERSION" 2>/dev/null || echo 0.0.0)}"
export SYNTHMK_SPOOL="${SYNTHMK_SPOOL:-/var/lib/check_mk_agent/spool}"
# How Checkmk users reach this node's screenshots; default to the container name.
export SYNTHMK_SHOT_BASE_URL="${SYNTHMK_SHOT_BASE_URL:-http://$(hostname):$SHOT_PORT}"
# Shared key: shot_server.py creates it 0600, runner.py signs links with it.
export SYNTHMK_SHOT_KEY_FILE="${SYNTHMK_SHOT_KEY_FILE:-$SHOT_DIR/.synthmk_shot_key}"

mkdir -p "$SHOT_DIR" "$SYNTHMK_SPOOL"

# Drop-privileges prefix for browser/HTTP processes (no-op if already non-root).
RUNAS=()
if [[ "$(id -u)" == "0" ]] && id pwuser >/dev/null 2>&1; then
  chown -R pwuser:pwuser "$SHOT_DIR" "$SYNTHMK_SPOOL" 2>/dev/null || true
  export HOME=/home/pwuser
  RUNAS=(setpriv --reuid pwuser --regid pwuser --clear-groups)
  # Bind-mounted secrets keep their HOST uid/mode, which the runner's
  # strict ownership check (rightly) rejects. While still root, install a
  # pwuser-owned 0600 runtime copy and point the runner at that.
  if [[ -n "${SYNTHMK_SECRETS_FILE:-}" && -f "$SYNTHMK_SECRETS_FILE" ]]; then
    install -o pwuser -g pwuser -m 600 "$SYNTHMK_SECRETS_FILE" /run/synthmk-secrets.yaml
    export SYNTHMK_SECRETS_FILE=/run/synthmk-secrets.yaml
  fi
fi

echo "== SynthMK runner-node $SYNTHMK_VERSION =="
echo "  agent transport : $AGENT_MODE on tcp/$AGENT_PORT"
echo "  screenshots     : http/$SHOT_PORT  base=$SYNTHMK_SHOT_BASE_URL (token-auth: ${SYNTHMK_SHOT_AUTH:-on})"
echo "  spool           : $SYNTHMK_SPOOL"
if [[ ${#RUNAS[@]} -gt 0 ]]; then
  echo "  runs as         : pwuser (browser/HTTP dropped from root)"
else
  echo "  runs as         : $(id -un)"
fi

# 1. screenshot server (authenticated; see runner-node/shot_server.py)
"${RUNAS[@]}" python3 "$SYNTHMK_HOME/runner-node/shot_server.py" >/var/log/synthmk-shots.log 2>&1 &

# 2. flow scheduler (worker pool; see runner-node/scheduler.py)
"${RUNAS[@]}" python3 "$SYNTHMK_HOME/runner-node/scheduler.py" &

# 3. management dashboard (token-protected; SYNTHMK_ADMIN=off to disable)
if [[ "${SYNTHMK_ADMIN:-on}" != "off" ]]; then
  # Audit trail must be appendable by the (unprivileged) dashboard process.
  AUDIT_LOG="${SYNTHMK_AUDIT_LOG:-/var/log/synthmk-audit.log}"
  touch "$AUDIT_LOG" 2>/dev/null || true
  [[ "$(id -u)" == "0" ]] && chown pwuser:pwuser "$AUDIT_LOG" 2>/dev/null || true
  "${RUNAS[@]}" python3 "$SYNTHMK_HOME/runner-node/admin_server.py" &
fi

# Graceful shutdown: forward SIGTERM/SIGINT to every child and wait for them.
# The agent transport runs in the BACKGROUND (not exec'd) so this bash process
# stays PID-relative to its children and the trap actually fires on stop. With
# exec, the trap was replaced and the scheduler/dashboard/shot-server were
# hard-killed, risking a half-written spool or a truncated audit line.
shutdown() {
  echo "entrypoint: shutting down, signalling children" >&2
  kill $(jobs -p) 2>/dev/null || true
  wait 2>/dev/null || true
  exit 0
}
trap shutdown TERM INT

# 4. agent transport (background; this script waits on it as the main process).
if [[ "$AGENT_MODE" == "official" ]]; then
  # Production: version-matched official Checkmk agent + TLS controller.
  # Requires a one-time `register_agent.sh` run (downloads the agent from your
  # site, installs it, registers TLS). The official agent serves the same
  # spool dir natively, so scheduler output flows through unchanged.
  if ! command -v cmk-agent-ctl >/dev/null 2>&1; then
    echo "FATAL: SYNTHMK_AGENT_MODE=official but cmk-agent-ctl is not installed."
    echo "       Either bake the agent into the image at build time"
    echo "         (docker build --build-arg CMK_AGENT_DEB=<site agent .deb url>)"
    echo "       or install + register it at runtime:"
    echo "         runner-node/register_agent.sh  (see runner-node/README.md)."
    exit 1
  fi
  # Containers have no systemd socket activation — provide the agent socket
  # the controller pulls output through.
  socat "UNIX-LISTEN:/run/check-mk-agent.socket,fork,mode=666" \
        "EXEC:/usr/bin/check_mk_agent" >/var/log/synthmk-agent-socket.log 2>&1 &
  cmk-agent-ctl daemon &
else
  # Lab/simple: plaintext socat transport. Firewall 6556 to the Checkmk server.
  "${RUNAS[@]}" socat -T30 "TCP-LISTEN:$AGENT_PORT,reuseaddr,fork,crlf" \
       "EXEC:bash $SYNTHMK_HOME/runner-node/agent_output.sh" &
fi

# Wait on all background services. `wait -n` returns when ANY exits; if the
# agent transport dies the container should fail (and be restarted) rather
# than linger with a dead transport, so we re-raise by exiting non-zero.
wait -n
echo "entrypoint: a service exited; stopping container" >&2
shutdown
