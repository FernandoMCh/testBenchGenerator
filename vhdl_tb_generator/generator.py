"""Builds a VHDL testbench source from a parsed DUT plus user-provided stimuli.

The output follows the layout of Vivado's own "Add Sources > Add or create
simulation sources" testbench template (``<entity>_tb`` naming, a
``component`` declaration, the clock as a single concurrent assignment,
a ``stimuli`` process), so generated files feel native to a Vivado project.
"""

from typing import Dict, List, Optional, Tuple

import pandas as pd

from .models import Generic, Port
from .utils import substitute_generics

_NUMERIC_STD_MARKERS = ("to_unsigned(", "to_signed(", "unsigned(", "signed(")


def generate_testbench(
    entity_name: str,
    ports: List[Port],
    generics: List[Generic],
    generic_values: Dict[str, str],
    clock_port: Optional[str],
    clock_period_ns: float,
    step_time_ns: float,
    waveform: pd.DataFrame,
) -> str:
    """Return the full VHDL source of the testbench as a string.

    ``waveform`` must have one row per simulation step and one column per
    input port (excluding the clock), holding VHDL literals/expressions as
    strings.
    """
    tb_entity_name = f"{entity_name}_tb"
    input_ports = [p for p in ports if p.direction == "in" and p.name != clock_port]
    resolved_types = {
        p.name: substitute_generics(p.type, generics, generic_values) for p in ports
    }
    period_name = "clockPeriod" if clock_port else "stepTime"
    period_value = clock_period_ns if clock_port else step_time_ns

    needs_numeric_std = any(
        marker in (resolved_types[p.name] or "").lower() for p in ports for marker in _NUMERIC_STD_MARKERS
    ) or any(
        marker in str(waveform.loc[idx, col]).lower()
        for col in waveform.columns
        for idx in waveform.index
        for marker in _NUMERIC_STD_MARKERS
    )

    lines: List[str] = []
    lines.append("-- Testbench automatically generated")
    lines.append("")
    lines.append("library IEEE;")
    lines.append("use IEEE.STD_LOGIC_1164.ALL;")
    lines.append("use IEEE.NUMERIC_STD.ALL;" if needs_numeric_std else "-- use IEEE.NUMERIC_STD.ALL;")
    lines.append("")
    lines.append(f"entity {tb_entity_name} is")
    lines.append(f"end {tb_entity_name};")
    lines.append("")
    lines.append(f"architecture test_bench of {tb_entity_name} is")
    lines.append("")
    lines.append("-- Signals for connection to the DUT")
    for port in ports:
        if port.name == clock_port:
            lines.append(f"  signal {port.name} : {resolved_types[port.name]} := '0';")
        else:
            lines.append(f"  signal {port.name} : {resolved_types[port.name]};")
    lines.append("")
    lines.append("  -- Component declaration")
    lines.append(f"  component {entity_name}")
    if generics:
        lines.append("    generic (")
        lines.append(_attached_paren_block(
            [f"{g.name} : {g.type} := {generic_values.get(g.name) or g.default or ''}" for g in generics],
            indent="      ",
            sep=";",
        ))
    lines.append("    port (")
    lines.append(_attached_paren_block(
        [f"{p.name} : {p.direction} {p.type}" for p in ports],
        indent="      ",
        sep=";",
    ))
    lines.append("  end component;")
    lines.append("")
    lines.append(f"  constant {period_name} : time := {_fmt_num(period_value)} ns;")
    lines.append("")
    lines.append("begin")
    lines.append(f"  DUT : {entity_name}")
    if generics:
        lines.append("    generic map (")
        lines.append(
            _attached_paren_block(
                [f"{g.name} => {generic_values.get(g.name) or g.default or ''}" for g in generics],
                indent="      ",
                close_with_semicolon=False,
            )
        )
    lines.append("    port map(")
    lines.append(_attached_paren_block([f"{p.name} => {p.name}" for p in ports], indent="      "))
    lines.append("")

    if clock_port:
        lines.append(f"  {clock_port} <= not {clock_port} after {period_name}/2;")
        lines.append("")

    lines.append("  stimuli : process")
    lines.append("  begin")
    lines.extend(_stimuli_lines(input_ports, waveform, period_name))
    lines.append("    wait;")
    lines.append("  end process;")
    lines.append("")
    lines.append(f"end test_bench;")
    lines.append("")

    return "\n".join(lines)


def _attached_paren_block(
    items: List[str], indent: str, sep: str = ",", close_with_semicolon: bool = True
) -> str:
    """Format a list with the closing ``)`` (and ``;``, if requested)
    attached to the last item, matching Vivado's own style::

        indent + item1<sep>
        indent + item2)[;]

    Use ``sep=";"`` for declaration lists (a component's ``generic``/``port``
    clauses) and the default ``sep=","`` for association lists (a
    ``generic map``/``port map``).
    """
    if not items:
        return f"{indent[:-2]})" + (";" if close_with_semicolon else "")
    closer = ")" + (";" if close_with_semicolon else "")
    body = [f"{indent}{item}" for item in items[:-1]]
    body.append(f"{indent}{items[-1]}{closer}")
    return f"{sep}\n".join(body)


def _stimuli_lines(input_ports: List[Port], waveform: pd.DataFrame, period_name: str) -> List[str]:
    if not input_ports:
        return []

    groups: List[Tuple[Dict[str, str], int]] = []
    for _, row in waveform.iterrows():
        values = {p.name: row[p.name] for p in input_ports}
        if groups and groups[-1][0] == values:
            prev_values, prev_count = groups[-1]
            groups[-1] = (prev_values, prev_count + 1)
        else:
            groups.append((values, 1))

    lines: List[str] = []
    prev_values: Optional[Dict[str, str]] = None
    for values, count in groups:
        for port in input_ports:
            if prev_values is None or prev_values[port.name] != values[port.name]:
                lines.append(f"    {port.name} <= {values[port.name]};")
        lines.append(f"    wait for {count} * {period_name};")
        lines.append("")
        prev_values = values

    return lines


def _fmt_num(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value)
