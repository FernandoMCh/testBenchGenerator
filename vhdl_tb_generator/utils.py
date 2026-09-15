import re
from typing import Dict, List

from .models import Generic


def substitute_generics(type_str: str, generics: List[Generic], generic_values: Dict[str, str]) -> str:
    """Replace generic identifiers used inside a type (e.g. array bounds) with
    their assigned value. Needed because generics are not visible outside the
    DUT instantiation in the testbench's own signal declarations, and to
    resolve concrete widths for stimulus validation."""
    result = type_str
    for g in generics:
        value = generic_values.get(g.name) or g.default
        if not value:
            continue
        result = re.sub(rf"\b{re.escape(g.name)}\b", value, result)
    return result
