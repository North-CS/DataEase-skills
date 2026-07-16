from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .redact import redact


class AuditLog:
    def __init__(self, output_dir: Path):
        self.directory = output_dir / "audit"
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        operation: str,
        *,
        status: str,
        risk: str,
        target: dict[str, Any] | None = None,
        changes: list[dict[str, Any]] | None = None,
        result: Any = None,
    ) -> str:
        audit_id = f"audit-{int(time.time())}-{uuid.uuid4().hex[:10]}"
        entry = {
            "audit_id": audit_id,
            "timestamp_ms": int(time.time() * 1000),
            "operation": operation,
            "status": status,
            "risk": risk,
            "target": redact(target or {}),
            "changes": redact(changes or []),
            "result": redact(result),
        }
        path = self.directory / f"{time.strftime('%Y-%m-%d')}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        return audit_id
