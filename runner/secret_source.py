#!/usr/bin/env python3
"""SynthMK secret source — file-backed credentials for login flows.

Login flows need credentials, and credentials must never live in the flow YAML
(flows are committed, linted, shipped in MKPs) nor in plain process environment
(visible in /proc/<pid>/environ and `docker inspect`). This module gives flows
the New-Relic-style `{{ secret.NAME }}` reference, resolved at run time from a
permission-checked secrets file that only the runner user can read.

Resolution rules
----------------
* ``{{ secret.NAME }}``  -> value of NAME from the secrets file. Missing name
  or missing/insecure file is a hard UNKNOWN (the flow never runs with a blank
  credential, which would lock out test accounts and produce misleading CRITs).
* ``{{ NAME }}``         -> legacy environment lookup (kept for back-compat;
  empty string when unset, as before).

Secrets file
------------
YAML mapping of scalars, path from ``$SYNTHMK_SECRETS_FILE`` or
``--secrets-file``. Example::

    wiki_user: monitor-bot
    wiki_password: s3cret...

The file MUST be owned by the runner user and not group/world accessible
(mode 0600 or 0400). Anything looser is rejected up front with a clear
message — a quietly readable credentials file is worse than a failing check.

Redaction
---------
Every value resolved from the secrets file is registered and scrubbed from any
outgoing text (service summaries, error messages) by :func:`redact`, so a
selector error like "could not fill 'hunter2' into #pw" can never leak a
credential into the Checkmk GUI, spool files, or logs.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - dependency guard
    yaml = None

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
SECRET_PREFIX = "secret."

# Values resolved from the secrets file during this process, for redaction.
_RESOLVED: set[str] = set()

MASK = "***"


class SecretError(Exception):
    """Secrets misconfiguration. Message is safe to surface (no values)."""


def secrets_file_path(cli_value: str | None = None) -> Path | None:
    raw = cli_value or os.environ.get("SYNTHMK_SECRETS_FILE")
    return Path(raw) if raw else None


def load_secrets(path: Path) -> dict[str, str]:
    """Load and permission-check the secrets file."""
    if yaml is None:
        raise SecretError("PyYAML is required to read the secrets file")
    if not path.exists():
        raise SecretError(f"secrets file not found: {path}")

    st = path.stat()
    if stat.S_ISDIR(st.st_mode):
        raise SecretError(f"secrets file is a directory: {path}")
    if st.st_mode & 0o077:
        raise SecretError(
            f"secrets file {path} is group/world accessible "
            f"(mode {stat.S_IMODE(st.st_mode):04o}); chmod 600 it"
        )
    # Ownership: the file must belong to the runner user (or root, the usual
    # owner for operator-managed config). Skipped when running AS root — root
    # reads any operator file, and bind-mounted files keep their host uid.
    if hasattr(os, "geteuid") and os.geteuid() != 0 and st.st_uid not in (os.geteuid(), 0):
        raise SecretError(
            f"secrets file {path} is not owned by the runner user (uid {st.st_uid})"
        )

    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        raise SecretError(f"secrets file {path} is not valid YAML")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SecretError(f"secrets file {path} must be a YAML mapping (name: value)")

    secrets: dict[str, str] = {}
    for key, value in data.items():
        if value is None or isinstance(value, (dict, list)):
            raise SecretError(f"secret '{key}' must be a scalar value")
        secrets[str(key)] = str(value)
    return secrets


def substitute(value: str, secrets: dict[str, str] | None) -> str:
    """Resolve {{ secret.NAME }} (secrets file) and {{ NAME }} (env) refs."""

    def repl(match: re.Match) -> str:
        name = match.group(1).strip()
        if name.startswith(SECRET_PREFIX):
            key = name[len(SECRET_PREFIX):].strip()
            if secrets is None:
                raise SecretError(
                    f"flow references {{{{ secret.{key} }}}} but no secrets file is "
                    f"configured (set SYNTHMK_SECRETS_FILE or --secrets-file)"
                )
            if key not in secrets:
                raise SecretError(f"secret '{key}' not found in secrets file")
            resolved = secrets[key]
            if resolved:
                _RESOLVED.add(resolved)
            return resolved
        return os.environ.get(name, "")

    return PLACEHOLDER_RE.sub(repl, value)


def referenced_secret_names(text: str) -> list[str]:
    """Secret names referenced by {{ secret.X }} in a string (for linting)."""
    names = []
    for match in PLACEHOLDER_RE.finditer(text or ""):
        name = match.group(1).strip()
        if name.startswith(SECRET_PREFIX):
            names.append(name[len(SECRET_PREFIX):].strip())
    return names


def register_sensitive(value: str) -> None:
    """Mark an arbitrary value (e.g. a sensitive fill) for redaction."""
    if value:
        _RESOLVED.add(value)


def redact(text: str) -> str:
    """Scrub every resolved secret value out of outgoing text."""
    out = str(text)
    # Longest first so overlapping values (e.g. "pass" inside "password1")
    # cannot leave a recognizable remainder behind.
    for value in sorted(_RESOLVED, key=len, reverse=True):
        if value in out:
            out = out.replace(value, MASK)
    return out


def reset() -> None:
    """Test hook: clear the redaction registry."""
    _RESOLVED.clear()
