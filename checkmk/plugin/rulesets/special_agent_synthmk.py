"""Setup ruleset for the SynthMK multi-node special agent (rulesets API v1).

Setup → Other integrations (special agents) → "SynthMK runner nodes (multi-node
locations)". Configure one or more runner-node HTTP endpoints; the special
agent (agent_synthmk) pulls each node's /api/results and feeds all of them
through the one host this rule is bound to — so runners on different network
segments, each reachable only from the Checkmk server, share one host.

The server-side translation into the agent command line lives in
server_side_calls/synthmk.py.
"""
from cmk.rulesets.v1 import Help, Title
from cmk.rulesets.v1.form_specs import (
    DefaultValue,
    DictElement,
    Dictionary,
    Integer,
    List,
    Password,
    String,
    validators,
)
from cmk.rulesets.v1.rule_specs import SpecialAgent, Topic


def _node_form() -> Dictionary:
    return Dictionary(
        title=Title("Runner node"),
        elements={
            "url": DictElement(
                required=True,
                parameter_form=String(
                    title=Title("Node base URL"),
                    help_text=Help(
                        "Base URL of the runner node's admin/results server, "
                        "e.g. http://10.20.0.5:9181 — the agent appends "
                        "/api/results."
                    ),
                    custom_validate=(validators.LengthInRange(min_value=1),),
                ),
            ),
            "token": DictElement(
                required=False,
                parameter_form=Password(
                    title=Title("Read token"),
                    help_text=Help(
                        "Value of SYNTHMK_RESULTS_TOKEN on the node (or its "
                        "admin token). Omit only if the node's results endpoint "
                        "is unauthenticated."
                    ),
                ),
            ),
            "name": DictElement(
                required=False,
                parameter_form=String(
                    title=Title("Display name"),
                    help_text=Help(
                        "Label used in the 'SynthMK Node <name>' connectivity "
                        "service. Defaults to the node URL."
                    ),
                ),
            ),
        },
    )


def _parameter_form() -> Dictionary:
    return Dictionary(
        elements={
            "nodes": DictElement(
                required=True,
                parameter_form=List(
                    title=Title("Runner nodes (locations)"),
                    help_text=Help(
                        "Each node is pulled every check interval; its flows "
                        "surface under their piggyback target host (or this "
                        "host when none is set), plus a per-node connectivity "
                        "service."
                    ),
                    element_template=_node_form(),
                ),
            ),
            "timeout": DictElement(
                required=False,
                parameter_form=Integer(
                    title=Title("Per-node HTTP timeout"),
                    unit_symbol="s",
                    prefill=DefaultValue(30),
                ),
            ),
        },
    )


rule_spec_special_agent_synthmk = SpecialAgent(
    name="synthmk",
    title=Title("SynthMK runner nodes (multi-node locations)"),
    topic=Topic.APPLICATIONS,
    parameter_form=_parameter_form,
)
