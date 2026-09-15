"""Helpers to build, resize and plot the input-stimulus waveform table."""

from typing import List, Optional

import pandas as pd
import plotly.graph_objects as go

from .models import Port


def default_value_for(port: Port) -> str:
    return "(others => '0')" if port.is_vector else "'0'"


def build_waveform_df(input_ports: List[Port], num_steps: int) -> pd.DataFrame:
    data = {port.name: [default_value_for(port)] * num_steps for port in input_ports}
    df = pd.DataFrame(data, index=range(num_steps))
    df.index.name = "cycle"
    return df


def resize_waveform_df(df: pd.DataFrame, input_ports: List[Port], num_steps: int) -> pd.DataFrame:
    """Adjust ``df`` to have ``num_steps`` rows, keeping existing values and
    columns in sync with the current ``input_ports`` selection."""
    current_cols = list(df.columns)
    target_cols = [p.name for p in input_ports]

    df = df.copy()
    for col in target_cols:
        if col not in df.columns:
            port = next(p for p in input_ports if p.name == col)
            df[col] = default_value_for(port)
    for col in current_cols:
        if col not in target_cols:
            df = df.drop(columns=col)
    df = df[target_cols]

    current_len = len(df)
    if num_steps > current_len:
        last_row = df.iloc[-1] if current_len > 0 else None
        extra_rows = []
        for _ in range(num_steps - current_len):
            if last_row is not None:
                extra_rows.append(last_row.to_dict())
            else:
                extra_rows.append({p.name: default_value_for(p) for p in input_ports})
        df = pd.concat([df, pd.DataFrame(extra_rows)], ignore_index=True)
    elif num_steps < current_len:
        df = df.iloc[:num_steps].reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    df.index.name = "cycle"
    return df


def _to_bit(value: str) -> Optional[int]:
    v = value.strip().strip("'\"")
    if v == "0":
        return 0
    if v == "1":
        return 1
    return None


def plot_waveform(df: pd.DataFrame, clock_name: Optional[str]) -> go.Figure:
    """Render a digital-style step waveform for scalar (bit) signals.

    Vector signals are not bit-accurate here; their literal values are shown
    as text labels on their own lane instead of a 0/1 step line.
    """
    num_steps = len(df)
    fig = go.Figure()
    lane_names: List[str] = []

    if clock_name and num_steps > 0:
        _add_clock_lane(fig, clock_name, num_steps, lane_index=len(lane_names))
        lane_names.append(clock_name)

    for col in df.columns:
        bits = [_to_bit(v) for v in df[col]]
        if all(b is not None for b in bits) and bits:
            step_bits = bits + [bits[-1]]
            _add_digital_lane(fig, col, step_bits, lane_index=len(lane_names))
        else:
            _add_bus_lane(fig, col, [str(v) for v in df[col]], lane_index=len(lane_names))
        lane_names.append(col)

    fig.update_layout(
        height=max(120, 90 * len(lane_names)),
        margin=dict(l=10, r=10, t=10, b=30),
        showlegend=False,
        yaxis=dict(
            tickmode="array",
            tickvals=[-i + 0.4 for i in range(len(lane_names))],
            ticktext=lane_names,
            range=[-len(lane_names) - 0.2, 1.2],
        ),
        xaxis=dict(title="cycle", dtick=1, range=[0, max(num_steps, 1)]),
    )
    return fig


def _add_clock_lane(fig: go.Figure, name: str, num_steps: int, lane_index: int) -> None:
    """Draw the clock with its real low/high halves: each cycle starts on a
    falling edge (at an integer x) and ends on the next one."""
    base = _lane_y(lane_index, total=None)
    x: List[float] = []
    y: List[float] = []
    for i in range(num_steps):
        x.extend([i, i + 0.5])
        y.extend([base, base + 0.8])
    x.append(num_steps)
    y.append(base)
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line_shape="hv", name=name))


def _add_digital_lane(fig: go.Figure, name: str, step_bits: List[int], lane_index: int) -> None:
    base = _lane_y(lane_index, total=None)
    y = [base + b * 0.8 for b in step_bits]
    x = list(range(len(step_bits)))
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line_shape="hv", name=name))


def _short_label(value: str, max_len: int = 14) -> str:
    return value if len(value) <= max_len else value[: max_len - 1] + "…"


def _add_bus_lane(fig: go.Figure, name: str, values: List[str], lane_index: int, crossing: float = 0.15) -> None:
    """Draw a bus/vector lane like a waveform viewer (Vivado/ISE simulator
    style): a flat two-line envelope holding the value's label, that narrows
    to a point where the value changes and stays flat while it doesn't."""
    base = _lane_y(lane_index, total=None)
    top = base + 0.8
    bottom = base
    mid = base + 0.4
    n = len(values)

    top_pts = [(0.0, top)]
    bot_pts = [(0.0, bottom)]
    for b in range(1, n):
        if values[b] != values[b - 1]:
            top_pts.extend([(b - crossing, top), (b, mid), (b + crossing, top)])
            bot_pts.extend([(b - crossing, bottom), (b, mid), (b + crossing, bottom)])
    top_pts.append((float(n), top))
    bot_pts.append((float(n), bottom))

    line_style = dict(color="#2ca02c")
    fig.add_trace(
        go.Scatter(
            x=[p[0] for p in top_pts],
            y=[p[1] for p in top_pts],
            mode="lines",
            line=line_style,
            name=name,
            showlegend=False,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[p[0] for p in bot_pts],
            y=[p[1] for p in bot_pts],
            mode="lines",
            line=line_style,
            fill="tonexty",
            fillcolor="rgba(44, 160, 44, 0.15)",
            name=name,
            showlegend=False,
        )
    )
    label_x: List[float] = []
    label_text: List[str] = []
    label_hover: List[str] = []
    seg_start = 0
    for i in range(1, n + 1):
        if i == n or values[i] != values[seg_start]:
            width = i - seg_start
            label_x.append((seg_start + i) / 2)
            label_text.append(_short_label(values[seg_start], max_len=max(6, int(width * 8))))
            label_hover.append(values[seg_start])
            seg_start = i

    fig.add_trace(
        go.Scatter(
            x=label_x,
            y=[mid] * len(label_x),
            mode="text",
            text=label_text,
            hovertext=label_hover,
            hoverinfo="text",
            textposition="middle center",
            showlegend=False,
        )
    )


def _lane_y(lane_index: int, total: Optional[int]) -> float:
    # Lanes stack top-to-bottom; leave one unit of vertical room per signal.
    return -lane_index
