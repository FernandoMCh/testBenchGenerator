"""Very small, dependency-free parser for VHDL entity declarations.

It is not a full VHDL parser: it only needs to reliably locate the
``generic`` and ``port`` clauses of an ``entity ... is ... end;`` block and
split their declarations, which is enough to drive the testbench generator.
"""

import re
from typing import List, Optional, Tuple

from .models import Generic, Port


class VhdlParseError(ValueError):
    pass


def _strip_comments(vhdl: str) -> str:
    return re.sub(r"--.*", "", vhdl)


def _extract_balanced(text: str, open_idx: int) -> Tuple[str, int]:
    """``text[open_idx]`` must be ``'('``.

    Returns the content strictly between the matching parentheses and the
    index right after the closing parenthesis.
    """
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : i], i + 1
    raise VhdlParseError("Unbalanced parentheses in VHDL source.")


def _split_top_level(content: str, sep: str = ";") -> List[str]:
    """Split ``content`` on ``sep`` while ignoring seps inside nested parens."""
    parts: List[str] = []
    depth = 0
    current: List[str] = []
    for ch in content:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return [p.strip() for p in parts if p.strip()]


def _find_block(text: str, keyword: str) -> Optional[str]:
    """Find ``<keyword> ( ... )`` (case-insensitive) and return its inner content."""
    pattern = re.compile(r"\b" + keyword + r"\s*\(", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    open_idx = match.end() - 1
    inner, _end_idx = _extract_balanced(text, open_idx)
    return inner


def _parse_generic_declarations(content: str) -> List[Generic]:
    generics: List[Generic] = []
    for decl in _split_top_level(content):
        if ":" not in decl:
            raise VhdlParseError(f"Malformed generic declaration: '{decl}'")
        names_part, rest = decl.split(":", 1)
        names = [n.strip() for n in names_part.split(",")]
        rest = rest.strip()
        if ":=" in rest:
            type_part, default_part = rest.split(":=", 1)
            default: Optional[str] = default_part.strip()
        else:
            type_part, default = rest, None
        type_str = type_part.strip()
        for name in names:
            generics.append(Generic(name=name, type=type_str, default=default))
    return generics


_DIRECTION_RE = re.compile(r"^(in|out|inout|buffer)\b\s*(.*)$", re.IGNORECASE)


def _parse_port_declarations(content: str) -> List[Port]:
    ports: List[Port] = []
    for decl in _split_top_level(content):
        if ":" not in decl:
            raise VhdlParseError(f"Malformed port declaration: '{decl}'")
        names_part, rest = decl.split(":", 1)
        names = [n.strip() for n in names_part.split(",")]
        rest = rest.strip()
        match = _DIRECTION_RE.match(rest)
        if not match:
            raise VhdlParseError(f"Could not determine direction in port declaration: '{decl}'")
        direction = match.group(1).lower()
        type_str = match.group(2).strip()
        for name in names:
            ports.append(Port(name=name, direction=direction, type=type_str))
    return ports


def parse_entity(vhdl_source: str) -> Tuple[str, List[Port], List[Generic]]:
    """Parse a VHDL source and return ``(entity_name, ports, generics)``."""
    text = _strip_comments(vhdl_source)

    entity_match = re.search(r"\bentity\s+(\w+)\s+is\b", text, re.IGNORECASE)
    if not entity_match:
        raise VhdlParseError("No 'entity ... is' declaration found in the VHDL file.")
    entity_name = entity_match.group(1)
    entity_start = entity_match.end()

    end_match = re.search(
        r"\bend\b(\s+entity)?(\s+" + re.escape(entity_name) + r")?\s*;",
        text[entity_start:],
        re.IGNORECASE,
    )
    entity_body = text[entity_start : entity_start + end_match.start()] if end_match else text[entity_start:]

    generic_content = _find_block(entity_body, "generic")
    generics = _parse_generic_declarations(generic_content) if generic_content else []

    port_content = _find_block(entity_body, "port")
    ports = _parse_port_declarations(port_content) if port_content else []

    if not ports:
        raise VhdlParseError("No ports found: is this a valid VHDL entity file?")

    return entity_name, ports, generics
