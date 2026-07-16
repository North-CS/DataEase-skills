from __future__ import annotations

import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any

from .errors import DataEaseError
from .redact import redact


RISK_LEVELS = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


class PlanStore:
    def __init__(self, output_dir: Path, ttl_seconds: int = 1800):
        self.directory = output_dir / "plans"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

    def create(
        self,
        operation: str,
        *,
        target: dict[str, Any],
        changes: list[dict[str, Any]],
        risk: str,
        spec: dict[str, Any],
        rollback: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if risk not in RISK_LEVELS:
            raise DataEaseError(f"未知风险级别: {risk}", code="invalid_risk", stage="safety")
        created_at = int(time.time())
        nonce = secrets.token_hex(4) if RISK_LEVELS[risk] >= 3 else ""
        canonical = json.dumps(
            {
                "operation": operation,
                "target": target,
                "changes": changes,
                "risk": risk,
                "spec": spec,
                "context": context or {},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        plan_id = "plan-" + hashlib.sha256(f"{canonical}|{created_at}|{secrets.token_hex(8)}".encode()).hexdigest()[:20]
        plan = {
            "plan_id": plan_id,
            "operation": operation,
            "risk": risk,
            "created_at": created_at,
            "expires_at": created_at + self.ttl_seconds,
            "target": redact(target),
            "changes": redact(changes),
            "rollback": redact(rollback or {}),
            "context": redact(context or {}),
            "execution_state": "pending",
            "confirmation_token": nonce or None,
            "spec": redact(spec),
        }
        (self.directory / f"{plan_id}.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {key: value for key, value in plan.items() if key != "spec"}

    def load(
        self,
        plan_id: str,
        confirmation_token: str = "",
        *,
        expected_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not plan_id.startswith("plan-") or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in plan_id):
            raise DataEaseError("plan-id 格式不合法", code="invalid_plan", stage="safety")
        path = self.directory / f"{plan_id}.json"
        if not path.exists():
            raise DataEaseError("找不到变更计划", code="plan_not_found", stage="safety")
        plan = json.loads(path.read_text(encoding="utf-8"))
        if int(plan.get("expires_at", 0)) < int(time.time()):
            raise DataEaseError("变更计划已过期，请重新 dry-run", code="plan_expired", stage="safety")
        if plan.get("execution_state") == "applied":
            raise DataEaseError("变更计划已经执行，不能重复使用", code="plan_already_applied", stage="safety")
        if expected_context is not None and plan.get("context", {}) != redact(expected_context):
            raise DataEaseError(
                "实例、组织或 DataEase 版本已变化，请重新 dry-run",
                code="plan_context_changed",
                stage="safety",
                details={"planned": plan.get("context", {}), "current": redact(expected_context)},
            )
        expected = plan.get("confirmation_token") or ""
        if RISK_LEVELS.get(plan.get("risk"), 99) >= 3 and confirmation_token != expected:
            raise DataEaseError("高风险操作需要正确的确认令牌", code="confirmation_required", stage="safety")
        return plan

    def mark_applied(self, plan_id: str, audit_id: str = "") -> None:
        path = self.directory / f"{plan_id}.json"
        if not path.exists():
            raise DataEaseError("找不到变更计划", code="plan_not_found", stage="safety")
        plan = json.loads(path.read_text(encoding="utf-8"))
        plan["execution_state"] = "applied"
        plan["applied_at"] = int(time.time())
        plan["audit_id"] = audit_id or None
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
