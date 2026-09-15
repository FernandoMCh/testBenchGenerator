# testBenchGenerator

A Streamlit web app that helps you design VHDL testbenches interactively: upload a DUT,
set its generics, pick the clock, sketch the input stimuli on a waveform, and download a
ready-to-simulate testbench.

## Features

- **VHDL entity parsing** &mdash; upload a `.vhd`/`.vhdl` file and its ports and generics are
  extracted automatically.
- **Generic values** &mdash; assign a single value to each generic; it's used both to
  instantiate the component and to resolve data types everywhere else (e.g. a bus width
  defined by a generic).
- **Clock selection** &mdash; pick which input is the clock and its period, or mark the DUT
  as combinational (no clock) and set a simulation step duration instead.
- **Interactive waveform editor** &mdash; an editable table (one row per clock cycle, one
  column per input) with a live preview chart. Editing a cell lets you choose whether the
  new value applies to that cycle only or from that cycle onward.
- **VHDL type checking** &mdash; every value is validated against the port's VHDL type.
  Binary/hex/octal literals, aggregates (`others => ...`), indexed/range assignments, and
  concatenation (`&`) are all accepted; a plain integer is automatically converted to the
  right expression (e.g. `std_logic_vector(to_unsigned(10, 8))`).
- **One-click generation** &mdash; download the generated testbench as a `.vhd` file.

## Requirements

- Python 3.9+
- Dependencies listed in [requirements.txt](requirements.txt): `streamlit`, `pandas`, `plotly`

## Running the app

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL Streamlit prints (by default http://localhost:8501).

## Project structure

```
app.py                      Streamlit UI, orchestrates the step-by-step workflow
vhdl_tb_generator/
  parser.py                 Parses a VHDL entity's ports and generics
  type_check.py             Validates/converts stimulus and generic values against VHDL types
  generator.py               Builds the testbench VHDL source
  waveform.py                Builds/resizes the stimulus table and renders the preview chart
  utils.py                    Shared helper (generic substitution in port types)
  models.py                   Port / Generic data classes
examples/                    Sample DUTs to try the app with (clocked and combinational)
assets/                      University of Seville logo/favicon used in the UI
```

## Author

Fernando Muñoz Chavero &mdash; University of Seville
