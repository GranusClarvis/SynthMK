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
TOTP_PREFIX = "totp."
VAR_PREFIX = "var."

# Values resolved from the secrets file during this process, for redaction.
_RESOLVED: set[str] = set()

# Builtin {{ var.* }} values, generated once per process so the same variable
# resolves identically across steps (type an email with var.uuid, then assert
# the page echoes the same uuid).
_VARS: dict[str, str] = {}

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


def totp_code(secret_b32: str, *, period: int = 30, digits: int = 6,
              now: float | None = None) -> str:
    """RFC 6238 TOTP from a base32 secret (the standard authenticator format).

    Stdlib-only on purpose: MFA-protected logins are an enterprise requirement
    and must not pull in a dependency the appliance image doesn't ship.
    """
    import base64
    import hashlib
    import hmac as hmac_mod
    import struct
    import time as time_mod

    cleaned = re.sub(r"[\s-]+", "", secret_b32).upper()
    try:
        key = base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))
    except Exception:
        raise SecretError("TOTP secret is not valid base32")
    counter = int((time_mod.time() if now is None else now) // period)
    digest = hmac_mod.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def _builtin_var(name: str) -> str:
    """Resolve a {{ var.* }} builtin; values are stable for the process."""
    if name in _VARS:
        return _VARS[name]
    if name == "uuid":
        import uuid as uuid_mod
        value = str(uuid_mod.uuid4())
    elif name == "timestamp":
        import time as time_mod
        value = str(int(time_mod.time()))
    elif name == "random":
        import secrets as pysecrets
        import string
        value = "".join(pysecrets.choice(string.ascii_lowercase + string.digits)
                        for _ in range(12))
    else:
        raise SecretError(
            f"unknown builtin variable 'var.{name}' (known: uuid, timestamp, random)"
        )
    _VARS[name] = value
    return value


def substitute(value: str, secrets: dict[str, str] | None) -> str:
    """Resolve {{ secret.NAME }} / {{ totp.NAME }} / {{ var.NAME }} / {{ NAME }}."""

    def _secret(key: str) -> str:
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

    def repl(match: re.Match) -> str:
        name = match.group(1).strip()
        if name.startswith(SECRET_PREFIX):
            return _secret(name[len(SECRET_PREFIX):].strip())
        if name.startswith(TOTP_PREFIX):
            # The shared TOTP seed lives in the secrets file like any credential;
            # the 6-digit code it derives expires in seconds and is not redacted
            # (a 6-digit mask would false-positive on timings in output).
            key = name[len(TOTP_PREFIX):].strip()
            seed = _secret(key)
            try:
                return totp_code(seed)
            except SecretError:
                raise SecretError(f"secret '{key}' is not a valid base32 TOTP secret")
        if name.startswith(VAR_PREFIX):
            return _builtin_var(name[len(VAR_PREFIX):].strip())
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
    """Test hook: clear the redaction registry and the builtin-var cache."""
    _RESOLVED.clear()
    _VARS.clear()
