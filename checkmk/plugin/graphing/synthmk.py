"""SynthMK metric/graph/perf-o-meter definitions (Checkmk graphing API v1).

Makes the journey-duration metric first-class in the GUI: proper time unit,
a perf-o-meter on every service row, and a named graph with threshold bands
(check_levels supplies the warn/crit). Per-step metrics (synthmk_step*) carry
dynamic names per flow and use Checkmk's automatic graphs.
"""
from cmk.graphing.v1 import Title, graphs, metrics, perfometers

UNIT_TIME = metrics.Unit(metrics.TimeNotation())

metric_synthmk_duration = metrics.Metric(
    name="synthmk_duration",
    title=Title("Journey duration"),
    unit=UNIT_TIME,
    color=metrics.Color.LIGHT_BLUE,
)

perfometer_synthmk_duration = perfometers.Perfometer(
    name="synthmk_duration",
    focus_range=perfometers.FocusRange(
        perfometers.Closed(0),
        perfometers.Open(10.0),
    ),
    segments=["synthmk_duration"],
)

graph_synthmk_duration = graphs.Graph(
    name="synthmk_duration",
    title=Title("Synthetic journey duration"),
    simple_lines=["synthmk_duration"],
)
