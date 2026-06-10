"""Server-side call for the SynthMK multi-node special agent.

Translates the Setup ruleset (rulesets/special_agent_synthmk.py) into the
``agent_synthmk`` command line. Tokens are passed as Checkmk secrets so they
are stored encrypted and never rendered into the command preview.

The special agent itself lives at checkmk/special/agent_synthmk.py; install it
as ``agents/special/agent_synthmk`` in the site (the MKP/install.sh place it).
"""
from collections.abc import Iterable, Sequence

from cmk.server_side_calls.v1 import (
    SpecialAgentCommand,
    SpecialAgentConfig,
)


def _commands(params, host_config) -> Iterable[SpecialAgentCommand]:
    args: list = ["--timeout", str(int(params.get("timeout", 30)))]
    if not params.get("tls_verify", True):
        args.append("--insecure")

    for node in params.get("nodes", []):
        url = node["url"]
        token = node.get("token")
        if token is None:
            args += ["--node", url]
            continue
        # The agent parses a single "URL@TOKEN" argument. Secret.unsafe() is
        # the documented escape hatch for embedding a secret inside a larger
        # argument string (LAN read-only token; still kept out of the GUI).
        raw = token.unsafe() if hasattr(token, "unsafe") else token
        args += ["--node", f"{url}@{raw}"]

    yield SpecialAgentCommand(command_arguments=args)


special_agent_synthmk = SpecialAgentConfig(
    name="synthmk",
    parameter_parser=lambda p: p,
    commands_function=_commands,
)
