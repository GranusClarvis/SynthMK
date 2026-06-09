# SynthMK failure modes & exit codes

SynthMK is designed so an operator can tell *what went wrong* from the exit code
and the single Checkmk line, without reading a stack trace. There are two
distinct surfaces: the **runner** (executes a flow in a browser) and the
**linter** (validates a flow file statically, before you ever deploy it).

## Runner exit codes

The runner exit code mirrors the Checkmk status digit, so the same binary works
as a local check and as a CI smoke test.

| Exit | Checkmk state | When |
|------|---------------|------|
| `0`  | OK    | Flow completed, duration under `warn_ms` |
| `1`  | WARN  | Flow passed but duration ≥ `warn_ms` (and < `crit_ms`) |
| `2`  | CRIT  | An assertion/interaction failed, or duration ≥ `crit_ms` |
| `3`  | UNKNOWN | Flow file missing/unparseable, unknown action, or an internal runner error |

Every exit emits exactly one Checkmk local-check line — even failures. A schema
or load error becomes an `UNKNOWN` line, never a traceback, so a broken flow
file degrades to a visible UNKNOWN service rather than a silent gap:

```text
3 "example-ok" duration=0ms;; UNKNOWN - Flow file flows/example-ok.yaml missing a 'steps' list
```

Missing dependency: if PyYAML is not installed the runner prints a one-line
`PyYAML is required` to stderr and exits `3`.

## Flow linter (`runner/flow_lint.py`)

Catch flow mistakes **before** deploying, with line-pointed messages and no
browser. Lint one or many files:

```bash
python3 runner/flow_lint.py flows/example-ok.yaml
make lint-flows                      # lints flows/*.yaml
```

| Exit | Meaning |
|------|---------|
| `0`  | Clean (warnings allowed) |
| `2`  | At least one lint **error** (unknown action, missing required key, `warn_ms > crit_ms`, empty steps) |
| `3`  | File missing or not valid YAML/mapping |

Errors block; warnings (unknown top-level/step keys, missing `name`) are advisory
and surface likely typos. The linter's per-action required-key table is kept in
lockstep with the runner's dispatch table — `runner/test_contract.py` asserts the
two stay aligned, so adding a runner action without teaching the linter is caught
by CI.

## Package payload contract (`packaging/test_package_contract.py`)

`make ci` proves the MKP rebuilds byte-identically (determinism). The payload
contract proves it is *correct*: the agent local-check lands at its install path
and is executable, the runtime payload (runner, flows, demo, README, VERSION) is
present, `info`/`info.json` versions match `VERSION`, and no build junk
(`__pycache__`, `*.pyc`, `.git`, `screenshots`, `node_modules`) leaked into the
tarball. Run standalone with `make package-contract`.
