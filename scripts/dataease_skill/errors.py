from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DataEaseError(Exception):
    message: str
    code: str = "dataease_error"
    stage: str = "runtime"
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "stage": self.stage,
            "retryable": self.retryable,
            "details": self.details,
        }
