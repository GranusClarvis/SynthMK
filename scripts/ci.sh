#!/usr/bin/env bash
# SynthMK local CI contract — the single check GitHub Actions and agents both run.
#
#   ./scripts/ci.sh        # or: make ci
#
# Runs every deterministic gate, browser-free:
#   1. make validate            runner output contract + recorder-export contract
#   2. shell syntax             bash -n (+ shellcheck if available) on tracked *.sh
#   3. js syntax                node --check on tracked extension *.js
#   4. package determinism      build the MKP twice, assert byte-identical sha256
#   5. secret scan              tracked files only, fail on private-key/token shapes
#   6. version consistency      VERSION == built info.json version == docs refs
#
# Exit non-zero on the first failing gate's class (gates are collected, then the
# script exits 1 if any failed) so CI surfaces every problem in one run.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
cd "$REPO"

PY="${PYTHON:-python3}"
NODE="${NODE:-node}"
fail=0
section() { printf '\n== %s ==\n' "$1"; }
ok()      { printf '  ok   - %s\n' "$1"; }
bad()     { printf '  FAIL - %s\n' "$1"; fail=1; }

# Only consider tracked files so CI scans exactly what ships.
mapfile -t TRACKED < <(git ls-files)

# --- 1. validate -----------------------------------------------------------
section "make validate (runner + recorder-export contract)"
if make --no-print-directory validate >/tmp/synthmk_ci_validate.log 2>&1; then
  ok "make validate"
else
  bad "make validate (see output below)"
  sed 's/^/    /' /tmp/synthmk_ci_validate.log
fi

# --- 1b. flow lint (every tracked flow) ------------------------------------
section "flow lint (static schema check on tracked flows)"
mapfile -t FLOWS < <(printf '%s\n' "${TRACKED[@]}" | grep -E '^(flows|lab/flows)/.*\.ya?ml$' || true)
if [[ "${#FLOWS[@]}" -eq 0 ]]; then
  ok "no tracked flow files to lint"
elif $PY runner/flow_lint.py "${FLOWS[@]}" >/tmp/synthmk_ci_lint.log 2>&1; then
  ok "all tracked flows lint clean (${#FLOWS[@]})"
else
  bad "flow lint failed"; sed 's/^/    /' /tmp/synthmk_ci_lint.log
fi

# --- 2. shell syntax -------------------------------------------------------
section "shell syntax (bash -n + shellcheck)"
have_shellcheck=0; command -v shellcheck >/dev/null 2>&1 && have_shellcheck=1
for f in "${TRACKED[@]}"; do
  [[ "$f" == *.sh ]] || continue
  if ! bash -n "$f" 2>/tmp/synthmk_ci_shn.log; then
    bad "bash -n $f"; sed 's/^/    /' /tmp/synthmk_ci_shn.log; continue
  fi
  if [[ "$have_shellcheck" -eq 1 ]]; then
    if shellcheck -S error "$f" >/tmp/synthmk_ci_shc.log 2>&1; then
      ok "$f"
    else
      bad "shellcheck $f"; sed 's/^/    /' /tmp/synthmk_ci_shc.log
    fi
  else
    ok "$f (bash -n only; shellcheck absent)"
  fi
done

# --- 2b. python syntax ------------------------------------------------------
# The Checkmk-side plugin files import cmk.* (only available on a site), so
# they can't be unit-run here — but they must always at least parse.
section "python syntax (ast.parse on tracked *.py)"
for f in "${TRACKED[@]}"; do
  [[ "$f" == *.py ]] || continue
  if $PY -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$f" 2>/tmp/synthmk_ci_py.log; then
    ok "$f"
  else
    bad "python syntax $f"; sed 's/^/    /' /tmp/synthmk_ci_py.log
  fi
done

# --- 3. js syntax ----------------------------------------------------------
section "js syntax (node --check)"
if command -v "$NODE" >/dev/null 2>&1; then
  for f in "${TRACKED[@]}"; do
    [[ "$f" == *.js ]] || continue
    if "$NODE" --check "$f" 2>/tmp/synthmk_ci_node.log; then
      ok "$f"
    else
      bad "node --check $f"; sed 's/^/    /' /tmp/synthmk_ci_node.log
    fi
  done
else
  bad "node not found — cannot syntax-check extension JS"
fi

# --- 4. package determinism ------------------------------------------------
section "package build determinism (byte-identical rebuild)"
VERSION="$(cat VERSION)"
if bash packaging/build_mkp.sh >/tmp/synthmk_ci_pkg1.log 2>&1; then
  sha1="$(sha256sum "dist/synthmk-$VERSION.mkp" | cut -d' ' -f1)"
  if bash packaging/build_mkp.sh >/tmp/synthmk_ci_pkg2.log 2>&1; then
    sha2="$(sha256sum "dist/synthmk-$VERSION.mkp" | cut -d' ' -f1)"
    if [[ "$sha1" == "$sha2" ]]; then
      ok "deterministic: $sha1"
    else
      bad "non-deterministic build: $sha1 != $sha2"
    fi
  else
    bad "second package build errored"; sed 's/^/    /' /tmp/synthmk_ci_pkg2.log
  fi
else
  bad "package build errored"; sed 's/^/    /' /tmp/synthmk_ci_pkg1.log
fi

# --- 4b. package payload contract ------------------------------------------
# Determinism (above) proves the build is reproducible; this proves it is
# CORRECT — expected install paths present, local-check executable, no junk.
section "package payload contract (expected files / paths / no junk)"
if $PY packaging/test_package_contract.py >/tmp/synthmk_ci_pkgc.log 2>&1; then
  ok "package payload contract holds"
else
  bad "package payload contract failed"; sed 's/^/    /' /tmp/synthmk_ci_pkgc.log
fi

# --- 5. secret scan (tracked files only) -----------------------------------
section "secret scan (tracked files)"
# Conservative, low-false-positive shapes: private-key headers, AWS access keys,
# GitHub tokens, Slack tokens, and long base64-ish bearer/api assignments.
secret_re='BEGIN (RSA|EC|OPENSSH|PGP|DSA) PRIVATE KEY|AKIA[0-9A-Z]{16}|gh[pousr]_[0-9A-Za-z]{30,}|xox[baprs]-[0-9A-Za-z-]{10,}|-----BEGIN PRIVATE KEY-----'
hits=0
for f in "${TRACKED[@]}"; do
  # skip this scanner (it necessarily contains the patterns) and binary blobs
  [[ "$f" == "scripts/ci.sh" ]] && continue
  if git grep -nIE "$secret_re" -- "$f" >/tmp/synthmk_ci_sec.log 2>/dev/null; then
    bad "possible secret in $f"; sed 's/^/    /' /tmp/synthmk_ci_sec.log; hits=1
  fi
done
[[ "$hits" -eq 0 ]] && ok "no private-key/token shapes in tracked files"

# --- 6. version consistency ------------------------------------------------
section "version consistency (VERSION <-> package <-> docs)"
info_ver="$($PY -c "import json,sys;print(json.load(open('dist/synthmk-$VERSION/info.json'))['version'])" 2>/dev/null || echo MISSING)"
if [[ "$info_ver" == "$VERSION" ]]; then
  ok "info.json version == VERSION ($VERSION)"
else
  bad "info.json version ($info_ver) != VERSION ($VERSION)"
fi
# Any hardcoded synthmk-<x.y.z> reference in tracked text must match VERSION.
badrefs="$(git grep -hoE 'synthmk-[0-9]+\.[0-9]+\.[0-9]+' -- '*.md' 2>/dev/null \
            | sort -u | grep -v "synthmk-$VERSION" || true)"
if [[ -z "$badrefs" ]]; then
  ok "no stale synthmk-<version> refs in docs"
else
  bad "stale version refs in docs: $(echo "$badrefs" | tr '\n' ' ')"
fi

# --- summary ---------------------------------------------------------------
section "summary"
if [[ "$fail" -eq 0 ]]; then
  echo "CI OK"
else
  echo "CI FAILED"
fi
exit "$fail"
