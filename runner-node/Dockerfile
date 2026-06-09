# SynthMK runner-node appliance.
#
# One container you host inside the intranet range. It reaches internal-only
# sites, runs many browser flows on their own intervals, serves failure
# screenshots, and answers Checkmk agent polls on 6556. Build context is the
# repo root:  docker build -f runner-node/Dockerfile -t synthmk-runner:0.2.0 .
#
# Base = official Playwright Python image: Chromium + all system browser deps are
# preinstalled, which is the painful part to get right by hand.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ARG SYNTHMK_HOME=/opt/synthmk
ENV SYNTHMK_HOME=${SYNTHMK_HOME} \
    SYNTHMK_FLOWS=${SYNTHMK_HOME}/flows \
    SYNTHMK_SPOOL=/var/lib/check_mk_agent/spool \
    SYNTHMK_SHOT_DIR=${SYNTHMK_HOME}/screenshots \
    SYNTHMK_NO_SANDBOX=1 \
    PYTHONUNBUFFERED=1

# socat = the agent transport; tini = clean PID 1 signal handling.
RUN apt-get update \
 && apt-get install -y --no-install-recommends socat tini \
 && rm -rf /var/lib/apt/lists/* \
 # Pin the Playwright python package to match the image's preinstalled browsers
 # (this base ships browsers under /ms-playwright but not the pip package).
 # chromium build 1148 == Playwright 1.49.x.
 && pip install --no-cache-dir pyyaml "playwright==1.49.0"

WORKDIR ${SYNTHMK_HOME}
# Payload the node runs (runner + flows + checkmk wrapper + node scripts + version).
COPY runner/      ${SYNTHMK_HOME}/runner/
COPY flows/       ${SYNTHMK_HOME}/flows/
COPY checkmk/     ${SYNTHMK_HOME}/checkmk/
COPY runner-node/ ${SYNTHMK_HOME}/runner-node/
COPY VERSION      ${SYNTHMK_HOME}/VERSION

RUN chmod +x ${SYNTHMK_HOME}/runner-node/*.sh ${SYNTHMK_HOME}/checkmk/*.sh \
 && mkdir -p ${SYNTHMK_SPOOL} ${SYNTHMK_SHOT_DIR} \
 && chown -R pwuser:pwuser ${SYNTHMK_SPOOL} ${SYNTHMK_SHOT_DIR} \
 # Default schedule if the operator doesn't mount their own flows.conf.
 && cp ${SYNTHMK_HOME}/runner-node/flows.conf.example ${SYNTHMK_HOME}/runner-node/flows.conf

# The shot server doubles as the container liveness probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS "http://localhost:${SYNTHMK_SHOT_PORT:-9180}/healthz" || exit 1

EXPOSE 6556 9180 9181
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "/opt/synthmk/runner-node/entrypoint.sh"]
