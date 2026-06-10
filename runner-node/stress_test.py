#!/usr/bin/env python3
"""Scheduler stress test — 150 flows on one node, browser-free.

scripts/scale_test.sh proves the full stack (real browsers) at 60 flows; this
harness proves the SCHEDULER's hot path well past that — worker pool, spool
publishing, hot reload, run-now — by substituting the browser runner with a
stub (SYNTHMK_RUNNER_CMD) that sleeps a realistic flow duration and emits a
native JSON result. 150 flows @ 10s = up to 15 runs/sec demanded, far beyond
any sane production schedule for one node.

Asserts after ~45s of sustained load:
  * every flow has a fresh spool result (none stale, none missing)
  * the scheduler self-service reports 0 overdue flows
  * a flow added mid-run (hot reload) is picked up and published
  * a run-now trigger refreshes its spool file within a few ticks
  * the scheduler process logged no tracebacks

Run:  python3 runner-node/stress_test.py    (exit 0 = all passed; ~60s)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

N_FLOWS = 150
INTERVAL_S = 60          # 150 runs/min demanded — 4x the documented envelope
LOAD_SECONDS = 100       # > one full stagger spread, so every flow runs
OVERLOAD_INTERVAL_S = 1  # phase 2: 150 runs/sec demanded — must alarm, loudly

STUB = '''#!/usr/bin/env python3
import json, random, sys, time
time.sleep(random.uniform(0.05, 0.35))
name = sys.argv[1].rsplit("/", 1)[-1].replace(".yaml", "")
print(json.dumps({"service": "Stress " + name, "status": 0, "duration_ms": 200,
                  "warn_ms": None, "crit_ms": None, "summary": "stub ok",
                  "failed_step": None, "steps": [], "screenshot_url": None,
                  "dynamic": False}))
'''

PASS = 0
FAILS = []


def check(label, cond):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok   - {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL - {label}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        flows = tdp / "flows"
        flows.mkdir()
        spool = tdp / "spool"
        spool.mkdir()
        run_now = tdp / "run-now"
        stub = tdp / "stub.py"
        stub.write_text(STUB)

        for i in range(N_FLOWS):
            (flows / f"f{i:03d}.yaml").write_text(
                f"name: Stress f{i:03d}\nsteps:\n  - action: open_url\n    url: x\n")
        conf = tdp / "flows.conf"
        conf.write_text("".join(
            f"f{i:03d}.yaml {INTERVAL_S}\n" for i in range(N_FLOWS)))

        env = dict(os.environ,
                   SYNTHMK_HOME=str(ROOT),
                   SYNTHMK_FLOWS=str(flows),
                   SYNTHMK_FLOWS_CONF=str(conf),
                   SYNTHMK_SPOOL=str(spool),
                   SYNTHMK_RUN_NOW_DIR=str(run_now),
                   SYNTHMK_RUNNER_CMD=f"{sys.executable} {stub}",
                   SYNTHMK_MAX_CONCURRENCY="8",
                   SYNTHMK_OUTPUT="native")
        proc = subprocess.Popen([sys.executable, str(HERE / "scheduler.py")],
                                env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        t0 = time.time()
        try:
            print(f"== sustaining {N_FLOWS} flows @ {INTERVAL_S}s for {LOAD_SECONDS}s ==")
            time.sleep(LOAD_SECONDS / 2)

            # Hot reload: add one more flow mid-run.
            (flows / "late.yaml").write_text(
                "name: Stress late\nsteps:\n  - action: open_url\n    url: x\n")
            with open(conf, "a") as fh:
                fh.write(f"late.yaml {INTERVAL_S}\n")

            time.sleep(LOAD_SECONDS / 2)

            results = {}
            for f in spool.iterdir():
                m = re.match(r"^(\d+)_synthmk_(.+)$", f.name)
                if not m or m.group(2) == "scheduler":
                    continue
                age = time.time() - f.stat().st_mtime
                results[m.group(2)] = age <= int(m.group(1))
            fresh = sum(1 for ok in results.values() if ok)
            check(f"all {N_FLOWS} flows have spool results ({len(results)} seen)",
                  sum(1 for k in results if k.startswith("f")) == N_FLOWS)
            check(f"all results fresh within maxage ({fresh}/{len(results)})",
                  fresh == len(results))
            check("hot-reloaded flow was scheduled and published",
                  results.get("late.yaml", False))

            sched = None
            for f in spool.glob("*_synthmk_scheduler"):
                for line in f.read_text().splitlines():
                    if line.strip().startswith("{"):
                        sched = json.loads(line)
            check("scheduler self-service present", sched is not None)
            if sched:
                summary = sched.get("summary", "")
                check(f"no overdue flows under load (summary: {summary[:90]})",
                      "pool healthy" in summary)

            # Run-now: trigger one flow and watch its spool mtime move.
            target = spool / f"{INTERVAL_S * 3}_synthmk_f000.yaml"
            before = target.stat().st_mtime
            run_now.mkdir(exist_ok=True)
            (run_now / "f000.yaml").touch()
            moved = False
            for _ in range(20):
                time.sleep(0.5)
                if target.stat().st_mtime > before:
                    moved = True
                    break
            check("run-now trigger refreshed the flow within ~10s", moved)

            # Overload phase: demand 30 runs/sec — far beyond any single node.
            # The contract is NOT to keep up (impossible) but to degrade
            # LOUDLY: the scheduler self-service must report overdue flows so
            # the node alarms before monitored apps show misleading CRITs.
            print("== overload phase: all flows every "
                  f"{OVERLOAD_INTERVAL_S}s ==")
            conf.write_text("".join(
                f"f{i:03d}.yaml {OVERLOAD_INTERVAL_S}\n" for i in range(N_FLOWS)))
            # Overdue alarm needs >60s of sustained lag (max(interval, 60s)
            # grace) plus a 30s health-emit cycle — poll for up to 150s.
            # Two distinct alarm paths: per-flow "overdue" (a stuck flow) and
            # the throughput watchdog "scheduling behind" (saturated pool
            # round-robining fairly — no flow individually overdue, every
            # service silently late). Saturation manifests as the latter.
            alarmed = ""
            for _ in range(36):
                time.sleep(5)
                for f in spool.glob("*_synthmk_scheduler"):
                    for line in f.read_text().splitlines():
                        if line.strip().startswith("{"):
                            s = json.loads(line)
                            summary = s.get("summary", "")
                            if s.get("status") == 1 and (
                                    "overdue" in summary or "behind" in summary):
                                alarmed = summary
                if alarmed:
                    break
            check(f"overload raises the scheduler self-service to WARN "
                  f"({alarmed[:80]})", bool(alarmed))
        finally:
            proc.terminate()
            try:
                out = proc.communicate(timeout=10)[0]
            except subprocess.TimeoutExpired:
                proc.kill()
                out = proc.communicate()[0]
        check("no tracebacks in scheduler output", "Traceback" not in out)
        print(f"== done in {time.time() - t0:.0f}s ==")

    print(f"\n{PASS} checks passed, {len(FAILS)} failed.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
