# Scaling a SynthMK runner node to 50–100 checks

The architecture that makes this work is unchanged from v0.2: the scheduler
runs flows on their own intervals into the Checkmk **spool dir**, and the agent
poll just concatenates spool files — so an agent poll is always instant no
matter how slow or numerous the browser runs are. v0.3 adds the pieces that
make *the browser side* scale safely.

## The mechanisms (runner-node/scheduler.py)

| Mechanism | Knob | Default |
|---|---|---|
| Worker pool — at most N concurrent browser runs | `SYNTHMK_MAX_CONCURRENCY` | 4 |
| Startup stagger — first runs spread out, no t=0 stampede | automatic | — |
| Overlap suppression — a still-running flow is never stacked | automatic (counted in perfdata) | — |
| Hard run timeout — hung browser killed, slot freed, UNKNOWN reported | `SYNTHMK_RUN_TIMEOUT_S` | 180 |
| Warmup lines — instant discoverable result per flow at start | automatic | — |
| Self-monitoring — `SynthMK Scheduler` service: WARN when flows go overdue | automatic, every 30s | — |

**The contract: if the node is oversubscribed, the `SynthMK Scheduler` service
goes WARN on the node** (with names of overdue flows) — monitored applications
never show false CRITs because of a saturated runner.

## Capacity formula

```
runs_per_minute     = Σ over flows (60 / interval_s)
avg_concurrency     = runs_per_minute × avg_flow_seconds / 60
required            : avg_concurrency  <  SYNTHMK_MAX_CONCURRENCY  (headroom ≥ 2×)
memory              ≈ 700 MB base + 1.0–1.5 GB × SYNTHMK_MAX_CONCURRENCY
cpu                 ≈ 0.5–1 core × SYNTHMK_MAX_CONCURRENCY (browser-bound)
```

Worked example — **100 flows @ 5 min interval, ~3 s average flow**:
20 runs/min × 3 s / 60 = **1.0 average concurrency** → default pool of 4 has 4×
headroom; memory limit 6 GB is comfortable. Long journeys change the math:
100 flows @ 5 min with 30 s flows = avg concurrency 10 → raise the pool to ~12,
give the container ~16 GB / 8 cores, or split across two nodes.

Scale **up** (pool + limits together), then **out** (more runner nodes, e.g.
one per network zone — each is just another Checkmk host). Piggyback names stay
unique per target site, so multiple nodes coexist cleanly.

## Measured (v0.3.0, this repo's `scripts/scale_test.sh`)

2026-06-09, single container (limits: 4 CPUs / 6 GB / `no-new-privileges`),
**60 flows** against the lab's internal site — 20 each at 60 s / 120 s / 180 s
intervals, every 5th flow the full multi-step login journey with secrets:

| Metric | Result |
|---|---|
| Sustained run rate | **≈37 browser runs/min** (219 runs in ~6 min; matches the formula's 36.7) |
| Spool freshness after 5 min soak | **60/60 fresh OK results** — 0 stale, 0 still-warming, 0 failures |
| Overlap skips / overdue flows | **0 / 0** — pool peaked at 3 of 4 slots |
| Slowest single run | 0.6 s |
| Agent poll (full 128-line output over TCP) | **< 0.5 s** including client container start — spool decoupling works |
| Container CPU during steady state | 12–25 % of the 4-CPU budget |
| Container RSS between runs | ~22 MiB (browsers are per-run subprocesses; budget 1–1.5 GB per *concurrent* slot for long flows) |

Conclusion: with short intranet flows, one default-sized node clears the
100-checks-at-5-minutes target with ~4× headroom; long (30 s+) journeys are the
thing that consumes pool slots — size with the formula above, and trust the
`SynthMK Scheduler` service to WARN if you get it wrong.

Reproduce with the LAN lab up: `bash scripts/scale_test.sh 60 300`.

## v0.5.0: 150-flow stress + the throughput watchdog

`runner-node/stress_test.py` drives the scheduler itself (browser stubbed via
`SYNTHMK_RUNNER_CMD`) at 150 flows / 150 runs-per-minute sustained — hot
reload and run-now exercised under load — then deliberately overloads it
(150 runs/sec demanded). The overload run exposed a silent failure mode: a
saturated pool **round-robins fairly**, so no single flow lags far enough to
trip the per-flow overdue alarm while every flow quietly runs at a multiple
of its configured interval (and its Checkmk service goes stale).

The scheduler self-service therefore carries two independent alarms:

1. **Overdue** — a specific flow is > max(interval, 60s) past schedule
   (stuck/starved flow; names it).
2. **Throughput watchdog** — achieved vs demanded runs/min over the last
   5 minutes drops below 80% (saturation; reports both numbers). Needs 5
   minutes of history, so node startup never false-alarms.

Both WARN on the node, never on monitored applications.
