"""SynthMK Setup ruleset (Checkmk rulesets API v1).

Gives operators a native Setup GUI for SynthMK services — currently the
journey-duration thresholds, overriding the flow file's warn_ms/crit_ms
without touching the runner node. Find it under
Setup → Service monitoring rules → "SynthMK synthetic browser checks".
"""
from cmk.rulesets.v1 import Help, Title
from cmk.rulesets.v1.form_specs import (
    DefaultValue,
    DictElement,
    Dictionary,
    LevelDirection,
    SimpleLevels,
    TimeMagnitude,
    TimeSpan,
)
from cmk.rulesets.v1.rule_specs import CheckParameters, HostAndItemCondition, Topic


def _parameter_form() -> Dictionary:
    return Dictionary(
        elements={
            "duration_levels": DictElement(
                required=False,
                parameter_form=SimpleLevels(
                    title=Title("Upper levels on total journey duration"),
                    help_text=Help(
                        "WARN/CRIT when the whole synthetic journey takes longer "
                        "than this. Overrides the warn_ms/crit_ms configured in "
                        "the flow file on the runner node."
                    ),
                    level_direction=LevelDirection.UPPER,
                    form_spec_template=TimeSpan(
                        displayed_magnitudes=[
                            TimeMagnitude.MINUTE,
                            TimeMagnitude.SECOND,
                            TimeMagnitude.MILLISECOND,
                        ]
                    ),
                    prefill_fixed_levels=DefaultValue(value=(5.0, 15.0)),
                ),
            ),
        },
    )


rule_spec_synthmk = CheckParameters(
    name="synthmk",
    title=Title("SynthMK synthetic browser checks"),
    topic=Topic.APPLICATIONS,
    parameter_form=_parameter_form,
    condition=HostAndItemCondition(item_title=Title("Synthetic check (service) name")),
)
