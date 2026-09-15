from pathlib import Path

import streamlit as st

from vhdl_tb_generator.generator import generate_testbench
from vhdl_tb_generator.parser import VhdlParseError, parse_entity
from vhdl_tb_generator.type_check import coerce_value, fallback_value_for, parse_type
from vhdl_tb_generator.utils import substitute_generics
from vhdl_tb_generator.waveform import build_waveform_df, plot_waveform, resize_waveform_df

ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_PATH = ASSETS_DIR / "us_logo.png"
FAVICON_PATH = ASSETS_DIR / "us_favicon.png"
US_RED = "#A71026"
US_YELLOW = "#EEAD39"

st.set_page_config(page_title="testBenchGenerator", page_icon=str(FAVICON_PATH), layout="wide")

st.markdown(
    f"""
    <style>
    .block-container {{ padding-top: 3.5rem; max-width: 1100px; }}
    h1, h2, h3 {{ color: #1a1a1a; }}
    h2 {{ border-bottom: 2px solid {US_RED}; padding-bottom: 0.3rem; margin-top: 2rem; }}
    div.stButton > button[kind="primary"], div.stDownloadButton > button {{
        background-color: {US_RED}; border-color: {US_RED};
    }}
    div.stButton > button[kind="primary"]:hover, div.stDownloadButton > button:hover {{
        background-color: #8a0029; border-color: #8a0029;
    }}
    .header-rule {{ border: none; border-top: 4px solid {US_YELLOW}; margin: 0.75rem 0 1.5rem 0; }}
    .app-footer {{
        margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #ddd;
        font-size: 0.85rem; color: #777; text-align: center;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

@st.dialog("How to use testBenchGenerator")
def show_help() -> None:
    st.markdown(
        """
1. **Upload the DUT** &mdash; upload the VHDL file (`.vhd`/`.vhdl`) containing the entity you
   want to test. The tool parses its ports and generics automatically.

2. **Set generic values** &mdash; if the entity declares generics, give each one a single
   value (or keep its default). This value is used both to instantiate the component in the
   testbench and to resolve data types everywhere else (e.g. a bus width defined by a generic),
   so it's done before anything else.

3. **Choose the clock signal** &mdash; pick which input port is the clock, and set its period.
   If the DUT is purely combinational, choose *"No clock"* and set a simulation step duration
   instead.

4. **Edit the input stimuli (waveform)** &mdash; a table with one row per clock cycle (or
   simulation step) and one column per input signal. Type a VHDL literal or expression in any
   cell, for example:
   - `'0'`, `'1'` for a single bit
   - `"0110"`, `x"0A"`, `O"17"` for a vector
   - a plain integer like `10`, which is automatically converted to the port's type
     (e.g. `std_logic_vector(to_unsigned(10, 8))`)

   When you edit a single cell, you'll be asked whether to apply it **only to that cycle** or
   **from that cycle onward** (holding the value until the next change). Invalid values are
   flagged with an explanation of what's expected. The chart below the table previews the
   waveform, grouping bus values that stay constant across several cycles.

5. **Generate and download** &mdash; click *"Generate VHDL testbench"* to build the file and
   download it with the *"Download testbench"* button.
        """
    )
    if st.button("Close"):
        st.rerun()


header_cols = st.columns([1, 5, 1])
with header_cols[0]:
    st.image(str(LOGO_PATH), width=110)
with header_cols[1]:
    st.markdown(
        "### testBenchGenerator\n"
        "Interactively design and export VHDL testbenches from your DUT, step by step."
    )
with header_cols[2]:
    if st.button("❔ Help", key="help_button"):
        show_help()
st.markdown('<hr class="header-rule">', unsafe_allow_html=True)

if "dut" not in st.session_state:
    st.session_state.dut = None  # dict: name, ports, generics
if "waveform_committed" not in st.session_state:
    st.session_state.waveform_committed = None
if "num_steps" not in st.session_state:
    st.session_state.num_steps = 8

# ---------------------------------------------------------------------------
# 1. Upload the DUT
# ---------------------------------------------------------------------------
st.header("1. Upload the DUT VHDL file")
uploaded_file = st.file_uploader("VHDL file (.vhd / .vhdl)", type=["vhd", "vhdl"])

if uploaded_file is not None:
    source = uploaded_file.getvalue().decode("utf-8", errors="replace")
    try:
        entity_name, ports, generics = parse_entity(source)
        if st.session_state.dut is None or st.session_state.dut["name"] != entity_name:
            st.session_state.dut = {
                "name": entity_name,
                "ports": ports,
                "generics": generics,
                "source": source,
            }
            st.session_state.waveform_committed = None
            st.session_state.pop("waveform_editor", None)
            st.session_state.clock_port = None
    except VhdlParseError as exc:
        st.error(f"Could not parse the file: {exc}")
        st.session_state.dut = None

dut = st.session_state.dut

if dut:
    st.success(f"Entity detected: **{dut['name']}**")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Ports")
        st.table(
            [{"name": p.name, "direction": p.direction, "type": p.type} for p in dut["ports"]]
        )
    with col2:
        st.subheader("Generics")
        if dut["generics"]:
            st.table(
                [
                    {"name": g.name, "type": g.type, "default value": g.default or ""}
                    for g in dut["generics"]
                ]
            )
        else:
            st.write("This entity does not declare any generics.")

    # -----------------------------------------------------------------
    # 2. Generic values (resolved first: everything downstream — port
    #    widths, type checking, the waveform — depends on these).
    # -----------------------------------------------------------------
    generic_values = {}
    invalid_generics = []
    if dut["generics"]:
        st.header("2. Generic values")
        st.caption(
            "Set a single value for each generic. It will be used both to instantiate the "
            "component in the testbench and to resolve the data types used everywhere else "
            "below (port widths, stimulus validation, ...)."
        )
        for g in dut["generics"]:
            raw = st.text_input(
                f"{g.name} : {g.type}",
                value=g.default or "",
                key=f"generic_{g.name}",
            )
            type_info = parse_type(g.type)
            result = coerce_value(raw, type_info)
            if not result.ok:
                default_result = coerce_value(g.default, type_info) if g.default else None
                fallback_value = (
                    default_result.value
                    if default_result and default_result.ok
                    else fallback_value_for(type_info)
                )
                st.error(
                    f"⚠️ **{g.name}**: {result.message} Using `{fallback_value}` instead."
                )
                invalid_generics.append(g.name)
                generic_values[g.name] = fallback_value
            else:
                if result.converted:
                    st.caption(f"Will be used: `{result.value}`")
                generic_values[g.name] = result.value

        if invalid_generics:
            st.warning(
                "Invalid value(s) were replaced with a safe default so the testbench can "
                "still be generated: " + ", ".join(f"**{name}**" for name in invalid_generics)
            )

    # -----------------------------------------------------------------
    # 3. Clock signal
    # -----------------------------------------------------------------
    st.header("3. Clock signal")
    candidate_clocks = [p.name for p in dut["ports"] if p.direction == "in"]
    clock_options = ["-- No clock (combinational) --"] + candidate_clocks
    clock_choice = st.selectbox("Select the clock signal", clock_options)
    clock_port = None if clock_choice == clock_options[0] else clock_choice

    if clock_port:
        clock_period_ns = st.number_input("Clock period (ns)", min_value=1.0, value=10.0, step=1.0)
        step_time_ns = clock_period_ns
    else:
        clock_period_ns = 10.0
        step_time_ns = st.number_input("Simulation step duration (ns)", min_value=1.0, value=10.0, step=1.0)

    # -----------------------------------------------------------------
    # 4. Input stimuli (waveform)
    # -----------------------------------------------------------------
    st.header("4. Input stimuli (waveform)")
    input_ports = [p for p in dut["ports"] if p.direction == "in" and p.name != clock_port]
    resolved_types = {
        p.name: parse_type(substitute_generics(p.type, dut["generics"], generic_values))
        for p in input_ports
    }

    if not input_ports:
        st.info("This entity has no inputs (besides the clock) to stimulate.")
        final_waveform_df = build_waveform_df([], 0)
    else:
        num_steps = st.number_input(
            "Number of cycles / simulation steps",
            min_value=1,
            max_value=1000,
            value=st.session_state.num_steps,
            step=1,
        )
        st.session_state.num_steps = num_steps

        target_cols = [p.name for p in input_ports]
        committed = st.session_state.waveform_committed
        needs_rebuild = (
            committed is None
            or list(committed.columns) != target_cols
            or len(committed) != num_steps
        )
        if needs_rebuild:
            committed = (
                build_waveform_df(input_ports, num_steps)
                if committed is None
                else resize_waveform_df(committed, input_ports, num_steps)
            )
            st.session_state.waveform_committed = committed
            st.session_state.pop("waveform_editor", None)

        caption = (
            "Each row is one full clock period (from one falling edge to the next)."
            if clock_port
            else "Each row is one simulation step."
        )
        st.caption(
            f"{caption} Type the VHDL literal or expression for each input "
            "(e.g. `'1'`, `'0'`, `\"0110\"`, `x\"0A\"`, or simply an integer like `10`, "
            "which will be automatically converted to the port's type)."
        )
        edited_df = st.data_editor(
            committed,
            width="stretch",
            num_rows="fixed",
            key="waveform_editor",
        )

        raw_diffs = [
            (idx, col, edited_df.loc[idx, col])
            for col in committed.columns
            for idx in committed.index
            if str(committed.loc[idx, col]) != str(edited_df.loc[idx, col])
        ]

        if len(raw_diffs) == 1:
            row, col, new_val = raw_diffs[0]
            result = coerce_value(str(new_val), resolved_types[col])
            if not result.ok:
                st.error(f"Cycle {row}, signal **{col}**: {result.message}")
            else:
                if result.converted:
                    st.caption(f"'{new_val}' will be interpreted as `{result.value}`.")
                st.info(f"You changed **{col}** at cycle **{row}**. How should I apply it?")
                apply_col1, apply_col2 = st.columns(2)
                if apply_col1.button("This cycle only", key="apply_single_cycle"):
                    committed = committed.copy()
                    committed.loc[row, col] = result.value
                    st.session_state.waveform_committed = committed
                    st.session_state.pop("waveform_editor", None)
                    st.rerun()
                if apply_col2.button("From this cycle onward", key="apply_forward"):
                    committed = committed.copy()
                    committed.loc[row:, col] = result.value
                    st.session_state.waveform_committed = committed
                    st.session_state.pop("waveform_editor", None)
                    st.rerun()
        elif len(raw_diffs) > 1:
            # Bulk edit (e.g. a paste): validate and commit each cell, no propagation prompt.
            committed = committed.copy()
            for row, col, new_val in raw_diffs:
                result = coerce_value(str(new_val), resolved_types[col])
                if not result.ok:
                    st.error(f"Cycle {row}, signal **{col}**: {result.message}")
                else:
                    committed.loc[row, col] = result.value
            st.session_state.waveform_committed = committed

        final_waveform_df = st.session_state.waveform_committed

        st.subheader("Preview")
        fig = plot_waveform(final_waveform_df, clock_port)
        st.plotly_chart(fig)

    # -----------------------------------------------------------------
    # 5. Generate and download
    # -----------------------------------------------------------------
    st.header("5. Generate testbench")
    if invalid_generics:
        st.caption(
            "Note: a safe default was substituted for " + ", ".join(invalid_generics) +
            " (see step 2) — edit it there if you need a different value."
        )
    if st.button("Generate VHDL testbench", type="primary"):
        tb_source = generate_testbench(
            entity_name=dut["name"],
            ports=dut["ports"],
            generics=dut["generics"],
            generic_values=generic_values,
            clock_port=clock_port,
            clock_period_ns=clock_period_ns,
            step_time_ns=step_time_ns,
            waveform=final_waveform_df,
        )
        st.session_state.tb_source = tb_source

    if st.session_state.get("tb_source"):
        st.code(st.session_state.tb_source, language="vhdl")
        st.download_button(
            "Download testbench (.vhd)",
            data=st.session_state.tb_source,
            file_name=f"{dut['name']}_tb.vhd",
            mime="text/plain",
        )
else:
    st.info("Upload a VHDL file to get started.")

st.markdown(
    """
    <div class="app-footer">
        Developed by <strong>Fernando Mu&ntilde;oz Chavero</strong> &mdash; University of Seville
    </div>
    """,
    unsafe_allow_html=True,
)
