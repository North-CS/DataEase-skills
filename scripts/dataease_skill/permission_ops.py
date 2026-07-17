from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from .admin_ops import _permission_items, _role_permission_patch, _validate_row_column_permission_changes
from .audit import AuditLog
from .client import DataEaseClient
from .config import Settings
from .errors import DataEaseError
from .redact import redact_configuration
from .safety import PlanStore
from .versioning import adapter_for_client


SCOPES = {"panel", "screen", "dataset", "datasource", "data_filling"}
SCOPE_ALIASES = {"dashboard": "panel", "datav": "screen", "data-v": "screen", "datafilling": "data_filling"}
SUBJECT_TYPES = {"user": 0, "role": 1}


def _envelope(operation: str, result: Any, **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "ok": True, "operation": operation, "result": result,
            "warnings": extra.pop("warnings", []), **extra}


def _load(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataEaseError(f"JSON 配置无效: {exc}", code="invalid_spec", stage="input") from exc
    if not isinstance(value, dict):
        raise DataEaseError("配置根节点必须是对象", code="invalid_spec", stage="input")
    return value


def _digest(value: Any) -> str:
    value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _context(client: DataEaseClient) -> dict[str, Any]:
    version = client.data("GET", "/license/version")
    return {"base_url": client.settings.base_url, "api_prefix": client.settings.api_prefix,
            "org_id": client.settings.org_id or None, "version": version}


def _subject(client: DataEaseClient, subject_type: str, subject_id: str) -> dict[str, Any]:
    endpoint = f"/user/queryById/{subject_id}" if subject_type == "user" else f"/role/detail/{subject_id}"
    value = client.data("GET", endpoint)
    if not isinstance(value, dict) or str(value.get("id")) != str(subject_id):
        raise DataEaseError("找不到授权对象", code="resource_not_found", stage="permissions")
    return value


def _read_scope(client: DataEaseClient, subject_type: str, subject_id: str, scope: str) -> dict[str, Any]:
    value = client.data("POST", "/auth/busiPermission",
                        {"id": int(subject_id), "type": SUBJECT_TYPES[subject_type], "flag": scope.upper()})
    if not isinstance(value, dict):
        raise DataEaseError("权限接口未返回对象", code="invalid_response", stage="permissions")
    return value


def _normalize(spec: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(spec) - {"subject_type", "subject_id", "identity", "scopes"})
    if unknown:
        raise DataEaseError("资源授权配置包含未知字段", code="unknown_spec_fields", stage="input",
                            details={"fields": unknown})
    subject_type = str(spec.get("subject_type") or "").lower()
    subject_id = str(spec.get("subject_id") or "")
    identity = str(spec.get("identity") or "")
    scopes = spec.get("scopes")
    if subject_type not in SUBJECT_TYPES or not subject_id or not identity or not isinstance(scopes, dict) or not scopes:
        raise DataEaseError("需要 subject_type、subject_id、identity 和非空 scopes", code="invalid_spec", stage="input")
    normalized_scopes = {SCOPE_ALIASES.get(str(scope).lower(), str(scope).lower()): items for scope, items in scopes.items()}
    if len(normalized_scopes) != len(scopes):
        raise DataEaseError("scopes 包含指向同一 DataEase 资源范围的重复别名", code="duplicate_permission_scope", stage="input")
    unknown_scopes = sorted(set(normalized_scopes) - SCOPES)
    if unknown_scopes:
        raise DataEaseError("包含不支持的资源范围", code="invalid_permission_scope", stage="input",
                            details={"scopes": unknown_scopes, "allowed": sorted(SCOPES)})
    return {"subject_type": subject_type, "subject_id": int(subject_id), "identity": identity,
            "scopes": {scope: _permission_items(items) for scope, items in normalized_scopes.items()}}


def _identity_value(subject_type: str, value: dict[str, Any]) -> str:
    return str(value.get("account") if subject_type == "user" else value.get("name"))


def inspect_permissions(client: DataEaseClient, subject_type: str, subject_id: str,
                        scope: str = "all") -> dict[str, Any]:
    version, adapter = adapter_for_client(client)
    adapter.require("resource_permissions", version)
    if subject_type not in SUBJECT_TYPES:
        raise DataEaseError("subject-type 必须是 user 或 role", code="invalid_input", stage="input")
    subject = _subject(client, subject_type, subject_id)
    scopes = sorted(SCOPES) if scope == "all" else [SCOPE_ALIASES.get(scope.lower(), scope.lower())]
    if any(item not in SCOPES for item in scopes):
        raise DataEaseError("不支持的资源范围", code="invalid_permission_scope", stage="input")
    return {"subject": {"id": subject_id, "type": subject_type,
                        "identity": _identity_value(subject_type, subject)},
            "scopes": {item: _read_scope(client, subject_type, subject_id, item) for item in scopes}}


def _snapshot(settings: Settings, subject_type: str, subject_id: str, value: Any) -> str:
    directory = settings.output_dir / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"permissions-{subject_type}-{subject_id}-{int(time.time())}.json"
    path.write_text(json.dumps(redact_configuration(value), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def handle_permission_operation(args: Any, settings: Settings, client: DataEaseClient,
                                plans: PlanStore, audit: AuditLog) -> dict[str, Any]:
    if args.action == "inspect":
        return _envelope("permission.inspect",
                         inspect_permissions(client, args.subject_type, args.subject_id, args.scope))
    operation = "permission.apply"
    request = _normalize(_load(args.spec))
    version, adapter = adapter_for_client(client)
    adapter.require("resource_permissions", version, mutation=True, client=client)
    subject_type = request["subject_type"]
    subject_id = str(request["subject_id"])
    subject = _subject(client, subject_type, subject_id)
    if _identity_value(subject_type, subject) != request["identity"]:
        raise DataEaseError("identity 与授权对象不一致", code="target_mismatch", stage="safety")
    current = {scope: _read_scope(client, subject_type, subject_id, scope) for scope in request["scopes"]}
    changes: list[dict[str, Any]] = []
    for scope, desired in request["scopes"].items():
        before = _permission_items(current[scope].get("permissions"))
        _validate_row_column_permission_changes(before, desired)
        changes.append({"action": "replace-resource-permissions", "scope": scope,
                        "before_count": len(before), "after_count": len(desired)})
    if not args.apply:
        snapshot = _snapshot(settings, subject_type, subject_id, {"subject": subject, "scopes": current})
        plan = plans.create(operation, target={"id": subject_id, "type": subject_type,
                            "identity": request["identity"], "scopes": sorted(request["scopes"])},
                            changes=changes, risk="L3",
                            spec={"payload_sha256": _digest(request), "precondition_sha256": _digest(current),
                                  "subject_sha256": _digest(subject), "snapshot": snapshot},
                            rollback={"strategy": "restore-each-permission-matrix", "snapshot": snapshot,
                                      "automatic_on_partial_failure": True}, context=_context(client))
        return _envelope(operation, plan, mode="dry-run", changes=changes, artifacts=[snapshot])
    if not args.plan_id:
        raise DataEaseError("执行资源授权需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_context(client))
    stored = plan.get("spec", {})
    if plan.get("operation") != operation or stored.get("payload_sha256") != _digest(request):
        raise DataEaseError("apply 配置与 dry-run 不一致", code="spec_changed", stage="safety")
    if stored.get("precondition_sha256") != _digest(current) or stored.get("subject_sha256") != _digest(subject):
        raise DataEaseError("授权对象或权限矩阵已变化，请重新 dry-run", code="target_changed", stage="safety")

    applied: list[str] = []
    try:
        for scope, desired in request["scopes"].items():
            before = _permission_items(current[scope].get("permissions"))
            patch = _role_permission_patch(before, desired)
            if patch:
                client.data("POST", "/auth/saveBusiPer",
                            {"id": int(subject_id), "type": SUBJECT_TYPES[subject_type],
                             "flag": scope.upper(), "permissions": patch})
            after = _permission_items(_read_scope(client, subject_type, subject_id, scope).get("permissions"))
            if after != desired:
                raise DataEaseError(f"{scope} 权限回读不一致", code="verification_failed", stage="verification")
            applied.append(scope)
    except Exception as exc:
        rollback_errors: list[str] = []
        for scope in reversed(applied):
            desired = _permission_items(current[scope].get("permissions"))
            now = _permission_items(_read_scope(client, subject_type, subject_id, scope).get("permissions"))
            try:
                client.data("POST", "/auth/saveBusiPer",
                            {"id": int(subject_id), "type": SUBJECT_TYPES[subject_type],
                             "flag": scope.upper(), "permissions": _role_permission_patch(now, desired)})
            except Exception:
                rollback_errors.append(scope)
        if isinstance(exc, DataEaseError):
            exc.details.update({"applied_before_failure": applied, "rollback_failed_scopes": rollback_errors})
            raise
        raise DataEaseError("资源授权执行失败", code="partial_failure", stage="permissions",
                            details={"applied_before_failure": applied, "rollback_failed_scopes": rollback_errors}) from exc
    after_all = {scope: _read_scope(client, subject_type, subject_id, scope) for scope in request["scopes"]}
    result = {"subject": {"id": subject_id, "type": subject_type, "identity": request["identity"]},
              "scopes": {scope: {"permission_count": len(_permission_items(value.get("permissions"))),
                                  "permissions_sha256": _digest(_permission_items(value.get("permissions")))}
                         for scope, value in after_all.items()}}
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"),
                           changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id,
                     artifacts=[stored.get("snapshot")])
