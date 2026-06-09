#!/usr/bin/env python3
"""SynthMK runner-node scheduler — concurrency-pooled flow execution.

Replaces the v0.2 bash loop. Same contract (flows.conf -> spool files the
agent transport serves), but built for 50-100 flows on one node:

  * worker pool        — at most SYNTHMK_MAX_CONCURRENCY browser runs at once
                         (Chromium is ~0.5-1.5 GB RSS per run; unbounded
                         parallelism is how a node tips over, see Uptime Kuma)
  * startup stagger    — first runs are spread across the pool instead of all
                         flows stampeding at t=0
  * overlap suppression— a flow still running when next due is skipped, never
                         stacked
  * hard run timeout   — a hung browser is killed and reported UNKNOWN, the
                         slot is freed
  * warmup lines       — at startup every configured flow immediately gets a
                         discoverable "warming up" result under its REAL
                         service name, so early Checkmk discovery never
                         captures fallback names
  * self-monitoring    — a "SynthMK Scheduler" service reports pool/queue
                         health so an oversubscribed node alerts as ITSELF
                         instead of as false CRITs on monitored apps

flows.conf format is unchanged:  <flow_file> <interval_s> [checkmk_host]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

HOME = Path(os.environ.get("SYNTHMK_HOME", "/opt/synthmk"))
FLOWS_DIR = Path(os.environ.get("SYNTHMK_FLOWS", HOME / "flows"))
CONF = Path(os.environ.get("SYNTHMK_FLOWS_CONF", HOME / "runner-node" / "flows.conf"))
SPOOL = Path(os.environ.get("SYNTHMK_SPOOL", "/var/lib/check_mk_agent/spool"))
SHOT_DIR = Path(os.environ.get("SYNTHMK_SHOT_DIR", HOME / "screenshots"))
SHOT_RETENTION_DAYS = int(os.environ.get("SYNTHMK_SHOT_RETENTION_DAYS", "7"))
PYTHON = os.environ.get("SYNTHMK_PYTHON", sys.executable or "python3")
TICK = float(os.environ.get("SYNTHMK_SCHED_TICK", "2"))
MAX_CONCURRENCY = int(os.environ.get("SYNTHMK_MAX_CONCURRENCY", "4"))
# Hard per-run wall clock: a flow's own timeout_ms guards steps, this guards
# the whole subprocess (browser launch hangs, zombie Chromium, ...).
RUN_TIMEOUT_S = int(os.environ.get("SYNTHMK_RUN_TIMEOUT_S", "180"))
SCHED_SERVICE = os.environ.get("SYNTHMK_SCHED_SERVICE", "SynthMK Scheduler")
# "native" (default) -> JSON <<<synthmk>>> section for the native check plugin
# (rich metrics, rulesets, graphs; ships in the MKP). "local" -> the v0.2/v0.3
# <<<local>>> line format for sites without the plugin installed.
OUTPUT = os.environ.get("SYNTHMK_OUTPUT", "native").lower()
# Run-now triggers from the management dashboard (admin_server.py): a file
# named like the flow file dropped here schedules an immediate run.
RUN_NOW_DIR = Path(os.environ.get("SYNTHMK_RUN_NOW_DIR", "/tmp/synthmk-run-now"))

os.environ.setdefault("SYNTHMK_NO_SANDBOX", "1")  # Chromium-in-Docker default


def log(msg: str) -> None:
    print(f"synthmk-scheduler: {msg}", flush=True)


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


@dataclass
class Flow:
    file: str
    interval: int
    host: str = ""
    next_run: float = 0.0
    running: bool = False
    runs: int = 0
    overlaps_skipped: int = 0
    last_duration: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def id(self) -> str:
        return slug(self.file)

    @property
    def path(self) -> Path:
        return FLOWS_DIR / self.file

    @property
    def maxage(self) -> int:
        return self.interval * 3


def parse_conf(conf: Path) -> list[Flow]:
    flows: list[Flow] = []
    if not conf.is_file():
        return flows
    for raw in conf.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2 or not parts[1].isdigit() or int(parts[1]) <= 0:
            log(f"skip bad config line: {raw!r}")
            continue
        flows.append(Flow(file=parts[0], interval=int(parts[1]),
                          host=parts[2] if len(parts) > 2 else ""))
    return flows


def wrap_sections(payload: str, host: str) -> str:
    """Spool/piggyback section wrapping (mirrors checkmk/piggyback_wrap.sh)."""
    header = "<<<synthmk:sep(0)>>>" if OUTPUT == "native" else "<<<local>>>"
    if host:
        return f"<<<<{host}>>>>\n{header}\n{payload}\n<<<<>>>>\n"
    return f"{header}\n{payload}\n"


def synthetic_line(service: str, status: int, summary: str,
                   metrics: dict | None = None) -> str:
    """A scheduler-generated result (warmup, missing flow, health) in the
    currently selected output format."""
    if OUTPUT == "native":
        import json
        entry = {"service": service, "status": status, "duration_ms": 0,
                 "warn_ms": None, "crit_ms": None, "summary": summary,
                 "failed_step": None, "steps": [], "screenshot_url": None,
                 "dynamic": False}
        if metrics:
            entry["metrics"] = metrics
        return json.dumps(entry, sort_keys=True)
    state_name = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}[status]
    perf = "|".join(f"{k}={v}" for k, v in (metrics or {}).items()) or "-"
    return f'{status} "{service}" {perf} {state_name} - {summary}'


def publish(dest_name: str, payload: str, host: str = "") -> None:
    """Atomically publish a spool file so an agent poll never sees a half-write."""
    SPOOL.mkdir(parents=True, exist_ok=True)
    tmp = SPOOL / f".{dest_name}.tmp"
    tmp.write_text(wrap_sections(payload, host))
    tmp.replace(SPOOL / dest_name)


def flow_service_name(flow: Flow) -> str:
    """The service name the runner will use — for warmup lines (no browser)."""
    try:
        if yaml is not None:
            data = yaml.safe_load(flow.path.read_text())
            if isinstance(data, dict) and data.get("name"):
                return str(data["name"])
    except Exception:
        pass
    return flow.path.stem


def emit_warmup(flow: Flow) -> None:
    """First-run placeholder under the real service name, so discovery done
    before the first browser run completes still captures the right service."""
    if not flow.path.is_file():
        publish(f"{flow.maxage}_synthmk_{flow.id}",
                synthetic_line(f"SynthMK {flow.file}", 3, "flow file not found"),
                flow.host)
        return
    name = flow_service_name(flow)
    publish(f"{flow.maxage}_synthmk_{flow.id}",
            synthetic_line(name, 0, "warming up, first result pending"),
            flow.host)


def run_flow(flow: Flow) -> None:
    start = time.monotonic()
    try:
        if not flow.path.is_file():
            payload = synthetic_line(f"SynthMK {flow.file}", 3, "flow file not found")
        else:
            cmd = [PYTHON, str(HOME / "runner" / "runner.py"), str(flow.path)]
            if OUTPUT == "native":
                cmd.append("--json")
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT_S,
                )
                payload = proc.stdout.strip()
                if not payload:
                    err = " ".join(proc.stderr.split())[:160]
                    payload = synthetic_line(
                        f"SynthMK {flow.file}", 3,
                        f'runner produced no output ({err or "no stderr"})')
            except subprocess.TimeoutExpired:
                payload = synthetic_line(
                    flow_service_name(flow), 3,
                    f"runner killed after {RUN_TIMEOUT_S}s hard timeout")
        publish(f"{flow.maxage}_synthmk_{flow.id}", payload, flow.host)
    except Exception as exc:  # never let a worker die silently
        log(f"worker error for {flow.file}: {exc}")
    finally:
        flow.last_duration = time.monotonic() - start
        flow.runs += 1
        with flow.lock:
            flow.running = False


def emit_scheduler_health(flows: list[Flow], pool: "Pool", now: float) -> None:
    overdue = [f for f in flows if not f.running and now - f.next_run > max(f.interval, 60)]
    total_runs = sum(f.runs for f in flows)
    total_skips = sum(f.overlaps_skipped for f in flows)
    slowest = max((f.last_duration for f in flows), default=0.0)
    # Oversubscription = flows can't run on schedule: that's a node-sizing
    # problem and must alert on the NODE, not as fake CRITs on monitored apps.
    state = 0
    detail = "pool healthy"
    if overdue:
        state = 1
        names = ", ".join(f.file for f in overdue[:3])
        detail = (f"{len(overdue)} flow(s) overdue ({names}…) — raise "
                  f"SYNTHMK_MAX_CONCURRENCY or intervals")
    publish("120_synthmk_scheduler",
            synthetic_line(
                SCHED_SERVICE, state,
                f"{detail} (concurrency {pool.active()}/{MAX_CONCURRENCY})",
                metrics={
                    "flows": len(flows),
                    "active": pool.active(),
                    "overdue": len(overdue),
                    "runs": total_runs,
                    "overlap_skips": total_skips,
                    "slowest_run": round(slowest, 2),
                }))


class Pool:
    def __init__(self, size: int):
        self._sem = threading.Semaphore(size)
        self._active = 0
        self._lock = threading.Lock()

    def active(self) -> int:
        with self._lock:
            return self._active

    def try_submit(self, flow: Flow) -> bool:
        """Claim a slot and start the flow. Caller must hold flow.lock; the
        running flag is set BEFORE the worker thread exists, so the worker's
        own 'running = False' (under the same lock) can never be overtaken."""
        if not self._sem.acquire(blocking=False):
            return False
        with self._lock:
            self._active += 1
        flow.running = True

        def _work():
            try:
                run_flow(flow)
            finally:
                with self._lock:
                    self._active -= 1
                self._sem.release()

        threading.Thread(target=_work, daemon=True, name=f"flow-{flow.id}").start()
        return True


def prune_screenshots() -> None:
    cutoff = time.time() - SHOT_RETENTION_DAYS * 86400
    try:
        for png in SHOT_DIR.glob("*.png"):
            if png.stat().st_mtime < cutoff:
                png.unlink(missing_ok=True)
    except Exception:
        pass


def main() -> int:
    log(f"home={HOME} conf={CONF} spool={SPOOL} "
        f"concurrency={MAX_CONCURRENCY} tick={TICK}s run_timeout={RUN_TIMEOUT_S}s")
    SPOOL.mkdir(parents=True, exist_ok=True)
    SHOT_DIR.mkdir(parents=True, exist_ok=True)

    pool = Pool(MAX_CONCURRENCY)
    flows = parse_conf(CONF)
    conf_mtime = CONF.stat().st_mtime if CONF.is_file() else 0.0

    # Warmup + stagger: every flow gets an immediate discoverable placeholder,
    # then first real runs are spread so N flows don't stampede one pool.
    now = time.time()
    for i, flow in enumerate(flows):
        emit_warmup(flow)
        spread = min(flow.interval, max(30, 5 * len(flows)))
        flow.next_run = now + (i * spread / max(1, len(flows)))
    log(f"{len(flows)} flow(s) configured; warmup lines published")

    last_health = 0.0
    last_prune = 0.0
    while True:
        # Hot-reload flows.conf (keep state for unchanged flows).
        try:
            mtime = CONF.stat().st_mtime if CONF.is_file() else 0.0
            if mtime != conf_mtime:
                conf_mtime = mtime
                fresh = parse_conf(CONF)
                old = {f.file: f for f in flows}
                for f in fresh:
                    if f.file in old:
                        prev = old[f.file]
                        f.next_run, f.running = prev.next_run, prev.running
                        f.runs, f.last_duration = prev.runs, prev.last_duration
                        f.lock = prev.lock
                    else:
                        emit_warmup(f)
                flows = fresh
                log(f"flows.conf reloaded: {len(flows)} flow(s)")
        except Exception as exc:
            log(f"config reload error: {exc}")

        # Run-now triggers from the dashboard: pull the flow's next_run in.
        try:
            if RUN_NOW_DIR.is_dir():
                for trig in RUN_NOW_DIR.iterdir():
                    for flow in flows:
                        if flow.file == trig.name:
                            flow.next_run = 0.0
                            log(f"run-now trigger for {flow.file}")
                    trig.unlink(missing_ok=True)
        except Exception as exc:
            log(f"run-now scan error: {exc}")

        now = time.time()
        for flow in flows:
            if now < flow.next_run:
                continue
            with flow.lock:
                if flow.running:
                    # Still running from last interval: never stack runs.
                    flow.overlaps_skipped += 1
                    flow.next_run = now + flow.interval
                    continue
                if pool.try_submit(flow):
                    flow.next_run = now + flow.interval

        if now - last_health >= 30:
            last_health = now
            emit_scheduler_health(flows, pool, now)
        if now - last_prune >= 300:
            last_prune = now
            prune_screenshots()
        time.sleep(TICK)


if __name__ == "__main__":
    raise SystemExit(main())
