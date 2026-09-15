from dataclasses import dataclass
from typing import Optional


@dataclass
class Port:
    name: str
    direction: str  # "in", "out", "inout", "buffer"
    type: str

    @property
    def is_vector(self) -> bool:
        return "vector" in self.type.lower()


@dataclass
class Generic:
    name: str
    type: str
    default: Optional[str] = None
