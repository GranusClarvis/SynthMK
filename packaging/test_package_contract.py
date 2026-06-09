#!/usr/bin/env python3
"""Package payload contract — what's actually INSIDE the built MKP.

`scripts/ci.sh` already proves the package rebuilds byte-identically. That
guards determinism but says nothing about *correctness*: a build that drops the
runner, ships a non-executable local-check, or leaks `__pycache__` would still
be perfectly deterministic. This test opens the tarball the builder produced and
asserts the payload contract a Checkmk operator depends on:

  * the agent local-check lands at its install path AND is mode 0755
  * the runtime payload (runner.py, flows, demo page, README, VERSION) is present
  * `info` and `info.json` exist and their version == VERSION
  * no build junk leaked (__pycache__, *.pyc, .git, screenshots, node_modules)

Browser-free; needs only Python (tarfile/json are stdlib). It builds the package
itself via packaging/build_mkp.sh so it is self-contained.

Run:  python3 packaging/test_package_contract.py   (exit 0 = contract holds)
"""
from __future__ import annotations

import json
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Files that MUST be present in the staged package, relative to the
# synthmk-<version>/ root inside the tarball.
EXPECTED_FILES = [
    "info",
    "info.json",
    "local/lib/check_mk_agent/local/300/synthmk_check.sh",
    "local/lib/python3/cmk_addons/plugins/synthmk/agent_based/synthmk.py",
    "local/lib/python3/cmk_addons/plugins/synthmk/rulesets/synthmk.py",
    "local/lib/python3/cmk_addons/plugins/synthmk/graphing/synthmk.py",
    "local/share/synthmk/runner/runner.py",
    "local/share/synthmk/runner/secret_source.py",
    "local/share/synthmk/runner/flow_lint.py",
    "local/share/synthmk/flows/example-ok.yaml",
    "local/share/synthmk/flows/demo/index.html",
    "local/share/synthmk/checkmk/synthmk_check.sh",
    "local/share/synthmk/README.md",
    "local/share/synthmk/VERSION",
]

# The agent local-check is invoked by the Checkmk agent and must be executable.
EXEC_FILES = ["local/lib/check_mk_agent/local/300/synthmk_check.sh"]

# Substrings that must never appear in any packaged path.
FORBIDDEN_SUBSTRINGS = ["__pycache__", ".pyc", "/.git", "screenshots", "node_modules", ".env"]

PASS = 0
FAILS: list[str] = []


def check(label: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
        print(f"  ok   - {label}")
    else:
        FAILS.append(label)
        print(f"  FAIL - {label}")


def main() -> int:
    version = (REPO / "VERSION").read_text().strip()
    print(f"== build package (synthmk-{version}.mkp) ==")
    build = subprocess.run(
        ["bash", str(REPO / "packaging" / "build_mkp.sh")],
        capture_output=True, text=True,
    )
    if build.returncode != 0:
        print(build.stdout)
        print(build.stderr, file=sys.stderr)
        print("  FAIL - build_mkp.sh errored")
        return 1
    print(f"  ok   - built synthmk-{version}.mkp")

    mkp = REPO / "dist" / f"synthmk-{version}.mkp"
    check("tarball exists", mkp.exists())
    if not mkp.exists():
        return 1

    root = f"synthmk-{version}"
    with tarfile.open(mkp, "r:gz") as tf:
        members = {m.name: m for m in tf.getmembers()}
        # Map both with and without the leading root dir for convenience.
        rel = {
            name[len(root) + 1:]: m
            for name, m in members.items()
            if name.startswith(root + "/")
        }

        print("== expected payload files present ==")
        for f in EXPECTED_FILES:
            check(f, f in rel and rel[f].isfile())

        print("== local-check is executable (0755-ish) ==")
        for f in EXEC_FILES:
            m = rel.get(f)
            check(f"{f} is executable", m is not None and bool(m.mode & 0o111))

        print("== no build junk leaked ==")
        leaked = [
            name for name in members
            if any(bad in name for bad in FORBIDDEN_SUBSTRINGS)
        ]
        check(f"no forbidden paths ({leaked[:3]})", not leaked)

        print("== metadata version consistency ==")
        info_json_m = rel.get("info.json")
        if info_json_m is not None:
            info = json.loads(tf.extractfile(members[f"{root}/info.json"]).read())
            check(f"info.json version == VERSION ({version})", info.get("version") == version)
            check("info.json name == synthmk", info.get("name") == "synthmk")
        else:
            check("info.json present", False)

        info_m = rel.get("info")
        if info_m is not None:
            info_txt = tf.extractfile(members[f"{root}/info"]).read().decode()
            check("info (python-dict) references VERSION", f"'{version}'" in info_txt)
        else:
            check("info present", False)

    print(f"\n{PASS} checks passed, {len(FAILS)} failed.")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
