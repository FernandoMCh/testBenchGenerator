"""Validate values typed by the user against a VHDL type, converting plain
numeric literals into the appropriate VHDL conversion-function call when the
target type requires one (e.g. an integer into ``to_unsigned(value, width)``).

This is intentionally not a full VHDL expression parser: known literal forms
are checked precisely (and, for vectors, checked against the resolved bit
width when known); anything else that looks like a plausible VHDL expression
(a function call, an aggregate, an operator expression...) is accepted
as-is, since fully verifying arbitrary VHDL is out of scope.
"""

import re
from dataclasses import dataclass
from typing import Optional

_VECTOR_KINDS = {"std_logic_vector", "std_ulogic_vector", "unsigned", "signed", "bit_vector"}
_SCALAR_BIT_KINDS = {"std_logic", "std_ulogic", "bit"}
_INTEGER_KINDS = {"integer", "natural", "positive"}


@dataclass
class TypeInfo:
    kind: str
    width: Optional[int]
    raw: str


@dataclass
class CoercionResult:
    ok: bool
    value: str
    message: str = ""
    converted: bool = False


_BASE_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(\(.*\))?\s*$", re.DOTALL)
_RANGE_RE = re.compile(r"\(\s*(.+?)\s+(downto|to)\s+(.+?)\s*\)", re.IGNORECASE)
_ARITH_ONLY_RE = re.compile(r"^[0-9+\-*/() \t]+$")


def _eval_int_expr(expr: str) -> Optional[int]:
    expr = expr.strip()
    if not expr or not _ARITH_ONLY_RE.match(expr):
        return None
    try:
        return int(eval(expr, {"__builtins__": {}}, {}))
    except Exception:
        return None


def parse_type(type_str: str) -> TypeInfo:
    """Parse a (generics-resolved) VHDL type string into base kind + width."""
    match = _BASE_RE.match(type_str or "")
    if not match:
        return TypeInfo(kind="other", width=None, raw=type_str)

    base = match.group(1).lower()
    bounds = match.group(2)

    width: Optional[int] = None
    if bounds:
        range_match = _RANGE_RE.search(bounds)
        if range_match:
            left = _eval_int_expr(range_match.group(1))
            right = _eval_int_expr(range_match.group(3))
            if left is not None and right is not None:
                width = abs(left - right) + 1

    if base in _VECTOR_KINDS or base in _SCALAR_BIT_KINDS or base in _INTEGER_KINDS:
        kind = base
    elif base in ("boolean", "real", "time"):
        kind = base
    else:
        kind = "other"

    return TypeInfo(kind=kind, width=width, raw=type_str)


_STD_LOGIC_CHAR_RE = re.compile(r"^'([01UuXxZzWwLlHh\-])'$")
_BIT_CHAR_RE = re.compile(r"^'([01])'$")
_BIN_STR_STD_RE = re.compile(r'^"([01UuXxZzWwLlHh\-]+)"$')
_BIN_STR_BIT_RE = re.compile(r'^"([01]+)"$')
_HEX_STR_RE = re.compile(r'^[xX]"([0-9a-fA-F_]+)"$')
_OCT_STR_RE = re.compile(r'^[oO]"([0-7_]+)"$')
_PLAIN_INT_RE = re.compile(r"^-?\d+$")
_REAL_RE = re.compile(r"^-?\d+\.\d+$")
_TIME_RE = re.compile(r"^\d+(\.\d+)?\s*(fs|ps|ns|us|ms|sec|min|hr)$", re.IGNORECASE)
# Allows aggregates ((others => '0'), (7 downto 4 => "1111", ...)) and
# concatenations ('1' & "000" & X"F") in addition to function calls.
_EXPR_RE = re.compile(r'^[\w\s.,()+\-*/&\'"=>_]+$')


def _looks_like_expression(value: str) -> bool:
    if value.count("(") != value.count(")"):
        return False
    return bool(_EXPR_RE.match(value))


def _check_bit_length(natural_bits: str, width: Optional[int], literal_repr: str) -> "CoercionResult":
    """Compare the bit count a literal naturally represents against the
    target width, applying VHDL's rule that extra, most-significant '0' bits
    may be silently dropped (e.g. O"312" == "011001010" fits an 8-bit target
    as "11001010"), but a literal that is too short is never auto-extended.
    """
    if width is None:
        return CoercionResult(ok=True, value=literal_repr)

    n = len(natural_bits)
    if n == width:
        return CoercionResult(ok=True, value=literal_repr)
    if n > width:
        excess = natural_bits[: n - width]
        if all(c == "0" for c in excess):
            return CoercionResult(ok=True, value=literal_repr)
        return CoercionResult(
            ok=False,
            value=literal_repr,
            message=(
                f"'{literal_repr}' represents {n} bits (expected {width}) and the extra, "
                "most-significant bits aren't all '0', so they can't be truncated."
            ),
        )
    return CoercionResult(
        ok=False,
        value=literal_repr,
        message=f"'{literal_repr}' represents {n} bits, expected {width}; VHDL does not zero-extend missing bits automatically.",
    )


def coerce_value(raw_value: str, type_info: TypeInfo) -> CoercionResult:
    """Check ``raw_value`` against ``type_info`` and, if it is a plain literal
    that needs conversion (e.g. a bare integer for a vector type), return the
    converted VHDL expression to use instead."""
    value = raw_value.strip()
    if not value:
        return CoercionResult(ok=False, value=raw_value, message="Value cannot be empty.")

    kind = type_info.kind

    if kind in _SCALAR_BIT_KINDS:
        allowed_re = _BIT_CHAR_RE if kind == "bit" else _STD_LOGIC_CHAR_RE
        if allowed_re.match(value):
            return CoercionResult(ok=True, value=value)
        if value in ("0", "1"):
            return CoercionResult(ok=True, value=f"'{value}'", converted=True)
        expected = "'0' or '1'" if kind == "bit" else "'0', '1', 'U', 'X', 'Z', 'W', 'L', 'H' or '-'"
        return CoercionResult(
            ok=False, value=raw_value, message=f"'{type_info.raw}' expects a {expected} character."
        )

    if kind in _VECTOR_KINDS:
        bin_re = _BIN_STR_BIT_RE if kind == "bit_vector" else _BIN_STR_STD_RE
        bin_match = bin_re.match(value)
        if bin_match:
            return _check_bit_length(bin_match.group(1), type_info.width, value)

        hex_match = _HEX_STR_RE.match(value)
        if hex_match:
            digits = hex_match.group(1).replace("_", "")
            natural_bits = "".join(format(int(d, 16), "04b") for d in digits)
            return _check_bit_length(natural_bits, type_info.width, value)

        oct_match = _OCT_STR_RE.match(value)
        if oct_match:
            digits = oct_match.group(1).replace("_", "")
            natural_bits = "".join(format(int(d, 8), "03b") for d in digits)
            return _check_bit_length(natural_bits, type_info.width, value)

        if _PLAIN_INT_RE.match(value):
            if type_info.width is None:
                return CoercionResult(
                    ok=False,
                    value=raw_value,
                    message=(
                        f"Cannot determine the width of '{type_info.raw}' to convert "
                        f"the integer {value}; use an explicit literal instead (e.g. \"0101\" or x\"5\")."
                    ),
                )
            is_negative = value.startswith("-")
            if kind == "signed":
                converted = f"to_signed({value}, {type_info.width})"
            elif kind == "unsigned":
                if is_negative:
                    return CoercionResult(
                        ok=False, value=raw_value, message="unsigned does not accept negative values."
                    )
                converted = f"to_unsigned({value}, {type_info.width})"
            else:  # std_logic_vector / std_ulogic_vector / bit_vector
                fn = "to_signed" if is_negative else "to_unsigned"
                cast = "bit_vector" if kind == "bit_vector" else "std_logic_vector"
                converted = f"{cast}({fn}({value}, {type_info.width}))"
            return CoercionResult(ok=True, value=converted, converted=True)

        if _looks_like_expression(value):
            return CoercionResult(ok=True, value=value)
        return CoercionResult(
            ok=False,
            value=raw_value,
            message=f"'{value}' is not recognized as a valid literal or expression for '{type_info.raw}'.",
        )

    if kind in _INTEGER_KINDS:
        if _PLAIN_INT_RE.match(value):
            ivalue = int(value)
            if kind == "natural" and ivalue < 0:
                return CoercionResult(ok=False, value=raw_value, message="natural does not accept negative values.")
            if kind == "positive" and ivalue < 1:
                return CoercionResult(ok=False, value=raw_value, message="positive requires values >= 1.")
            return CoercionResult(ok=True, value=value)
        if _looks_like_expression(value):
            return CoercionResult(ok=True, value=value)
        return CoercionResult(
            ok=False, value=raw_value, message=f"'{value}' is not a valid integer or expression for '{type_info.raw}'."
        )

    if kind == "boolean":
        if value.lower() in ("true", "false"):
            return CoercionResult(ok=True, value=value.lower(), converted=value != value.lower())
        return CoercionResult(ok=False, value=raw_value, message="boolean expects TRUE or FALSE.")

    if kind == "real":
        if _REAL_RE.match(value):
            return CoercionResult(ok=True, value=value)
        return CoercionResult(
            ok=False, value=raw_value, message="real expects a literal with a decimal point, e.g. 3.14."
        )

    if kind == "time":
        if _TIME_RE.match(value):
            return CoercionResult(ok=True, value=value)
        return CoercionResult(
            ok=False, value=raw_value, message="time expects a value with a unit, e.g. 10 ns."
        )

    # Unknown/custom type (record, enumerated type, ...): cannot validate meaningfully.
    return CoercionResult(ok=True, value=value)
