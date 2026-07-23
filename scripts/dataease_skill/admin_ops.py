from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from .audit import AuditLog
from .client import DataEaseClient
from .config import Settings
from .errors import DataEaseError
from .redact import redact_configuration
from .safety import PlanStore


CREATE_OPERATIONS = {
    "organization-create": {
        "resource": "organization",
        "endpoint": "/org/page/create",
        "detail": "/org/detail/{id}",
        "identity": "name",
        "required": ("name",),
    },
    "role-create": {
        "resource": "role",
        "endpoint": "/role/create",
        "detail": "/role/detail/{id}",
        "identity": "name",
        "required": ("name", "typeCode"),
    },
    "user-create": {
        "resource": "user",
        "endpoint": "/user/create",
        "detail": "/user/queryById/{id}",
        "identity": "account",
        "required": ("name", "account", "email", "roleIds", "enable"),
    },
}

EDIT_OPERATIONS = {
    "organization-edit": {
        "resource": "organization",
        "endpoint": "/org/page/edit",
        "detail": "/org/detail/{id}",
        "identity": "name",
        "required": ("id", "name"),
    },
    "role-edit": {
        "resource": "role",
        "endpoint": "/role/edit",
        "detail": "/role/detail/{id}",
        "identity": "name",
        "required": ("id", "name"),
    },
    "user-edit": {
        "resource": "user",
        "endpoint": "/user/edit",
        "detail": "/user/queryById/{id}",
        "identity": "account",
        "required": ("id", "name", "account", "email", "roleIds", "enable"),
    },
}

DELETE_OPERATIONS = {
    "organization-delete": {
        "resource": "organization",
        "endpoint": "/org/page/delete/{id}",
        "detail": "/org/detail/{id}",
        "identity": "name",
    },
    "role-delete": {
        "resource": "role",
        "endpoint": "/role/delete/{id}",
        "detail": "/role/detail/{id}",
        "identity": "name",
    },
    "user-delete": {
        "resource": "user",
        "endpoint": "/user/delete/{id}",
        "detail": "/user/queryById/{id}",
        "identity": "account",
    },
}

ROLE_PERMISSION_SCOPES = ("menu", "datasource", "dataset", "panel", "screen", "data_filling")
ROLE_PERMISSION_SCOPE_ALIASES = {
    "dashboard": "panel",
    "datav": "screen",
    "data-v": "screen",
    "datafilling": "data_filling",
}


def _envelope(operation: str, result: Any, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": True,
        "operation": operation,
        "result": result,
        "warnings": extra.pop("warnings", []),
        **extra,
    }


def _load_spec(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataEaseError(f"JSON 配置无效: {exc}", code="invalid_spec", stage="input") from exc
    if not isinstance(value, dict):
        raise DataEaseError("配置根节点必须是 JSON 对象", code="invalid_spec", stage="input")
    return value


def _digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plan_context(client: DataEaseClient) -> dict[str, Any]:
    version = None
    try:
        version = client.data("GET", "/license/version")
    except DataEaseError:
        pass
    return {
        "base_url": client.settings.base_url,
        "api_prefix": client.settings.api_prefix,
        "org_id": client.settings.org_id or None,
        "version": version,
    }


def _snapshot(settings: Settings, resource: str, resource_id: str, data: Any) -> str:
    directory = settings.output_dir / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    safe_resource = "".join(char for char in resource if char.isalnum() or char in {"-", "_"})
    safe_id = "".join(char for char in str(resource_id) if char.isalnum() or char in {"-", "_"})
    path = directory / f"{safe_resource}-{safe_id}-{int(time.time())}.json"
    path.write_text(json.dumps(redact_configuration(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def _detail(client: DataEaseClient, template: str, resource_id: str) -> dict[str, Any]:
    value = client.data("GET", template.format(id=resource_id))
    if not isinstance(value, dict) or str(value.get("id")) != str(resource_id):
        raise DataEaseError("找不到目标管理资源", code="resource_not_found", stage="administration")
    return value


def _public_state(resource: str, detail: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "organization": ("id", "name", "pid", "rootPath"),
        "role": ("id", "name", "typeCode", "desc"),
        "user": ("id", "account", "name", "enable", "roleIds", "mfaEnable", "origin"),
    }[resource]
    return {key: detail.get(key) for key in fields if key in detail}


def _validate_required(spec: dict[str, Any], required: tuple[str, ...]) -> None:
    missing = [key for key in required if key not in spec or spec.get(key) in (None, "")]
    if missing:
        raise DataEaseError(
            f"配置缺少必填字段: {', '.join(missing)}",
            code="invalid_spec",
            stage="input",
        )


def _normalize_create_spec(action: str, spec: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(spec)
    if action == "user-create":
        forbidden_password_fields = sorted(
            field for field in normalized
            if field.casefold() in {"password", "pwd", "newpwd", "new_password", "initialpassword"}
        )
        if forbidden_password_fields:
            raise DataEaseError(
                "DataEase 用户创建接口不支持指定密码；新用户始终使用系统初始密码",
                code="custom_user_password_unsupported",
                stage="input",
                details={
                    "fields": forbidden_password_fields,
                    "password_mode": "system_initial_password",
                    "custom_password_applied": False,
                },
            )
        normalized.setdefault("variables", [])
        normalized.setdefault("mfaEnable", False)
        if not isinstance(normalized["variables"], list):
            raise DataEaseError("variables 必须是数组", code="invalid_spec", stage="input")
    return normalized


def _normalized_role_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DataEaseError("roleIds 必须是数组", code="invalid_spec", stage="input")
    normalized: set[str] = set()
    for role_id in value:
        if isinstance(role_id, bool) or not isinstance(role_id, (int, str)):
            raise DataEaseError("roleIds 只能包含角色 ID", code="invalid_spec", stage="input")
        text = str(role_id).strip()
        if not text:
            raise DataEaseError("roleIds 不能包含空 ID", code="invalid_spec", stage="input")
        normalized.add(text)
    return tuple(sorted(normalized))


def _selected_role_state(client: DataEaseClient, role_ids: Any) -> list[dict[str, Any]]:
    selected = _normalized_role_ids(role_ids)
    value = client.data("POST", "/role/query", {"keyword": ""})
    records = value if isinstance(value, list) else value.get("records", []) if isinstance(value, dict) else []
    by_id = {
        str(item.get("id")): item
        for item in records
        if isinstance(item, dict) and item.get("id") is not None
    }
    missing = [role_id for role_id in selected if role_id not in by_id]
    if missing:
        raise DataEaseError(
            "所选角色不存在或当前组织不可见",
            code="role_not_found",
            stage="administration",
            details={"role_ids": missing},
        )
    return [
        {
            "id": role_id,
            "root": bool(by_id[role_id].get("root")),
            "readonly": bool(by_id[role_id].get("readonly")),
            "administrator": bool(by_id[role_id].get("root"))
            and not bool(by_id[role_id].get("readonly")),
        }
        for role_id in selected
    ]


def _user_create_risk(client: DataEaseClient, spec: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    role_state = _selected_role_state(client, spec.get("roleIds"))
    is_administrator = any(item["administrator"] for item in role_state)
    return ("L3" if is_administrator else "L1"), role_state


def _edit_risk(action: str, current: dict[str, Any], spec: dict[str, Any]) -> tuple[str, bool]:
    if action == "role-edit":
        return "L3", True
    if action == "user-edit":
        changed = _normalized_role_ids(current.get("roleIds", [])) != _normalized_role_ids(
            spec.get("roleIds")
        )
        return ("L3" if changed else "L2"), changed
    return "L2", False


def _load_digest_bound_spec(args: Any, plan: dict[str, Any]) -> dict[str, Any]:
    request_spec = _load_spec(args.spec)
    if _digest(request_spec) != plan.get("spec", {}).get("payload_sha256"):
        raise DataEaseError("apply 配置与 dry-run 内容不一致", code="spec_changed", stage="safety")
    return request_spec


def _role_permission_scope(value: Any, *, allow_all: bool = False) -> str:
    scope = str(value or "").strip().lower()
    scope = ROLE_PERMISSION_SCOPE_ALIASES.get(scope, scope)
    allowed = set(ROLE_PERMISSION_SCOPES)
    if allow_all:
        allowed.add("all")
    if scope not in allowed:
        raise DataEaseError(
            "不支持的角色权限范围",
            code="invalid_permission_scope",
            stage="input",
            details={"scope": value, "allowed": sorted(allowed)},
        )
    return scope


def _permission_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DataEaseError("permissions 必须是数组", code="invalid_spec", stage="input")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise DataEaseError("permissions 只能包含对象", code="invalid_spec", stage="input")
        unknown = sorted(set(item) - {"id", "weight", "ext", "columnPermissions", "rowPermissions"})
        if unknown:
            raise DataEaseError(
                "权限项包含未知字段",
                code="unknown_spec_fields",
                stage="input",
                details={"fields": unknown},
            )
        if item.get("id") in (None, "") or item.get("weight") is None:
            raise DataEaseError("每个权限项必须包含 id 与 weight", code="invalid_spec", stage="input")
        if isinstance(item.get("weight"), bool) or isinstance(item.get("ext", 0), bool):
            raise DataEaseError("weight/ext 必须是整数", code="invalid_spec", stage="input")
        try:
            permission_id = int(str(item["id"]).strip())
            weight = int(item["weight"])
            ext = int(item.get("ext", 0))
        except (TypeError, ValueError) as exc:
            raise DataEaseError("权限项 id、weight 和 ext 必须是整数", code="invalid_spec", stage="input") from exc
        if weight < 1 or weight > 9:
            raise DataEaseError(
                "目标权限矩阵中的 weight 必须位于 1 到 9；撤销权限请从 permissions 中移除该资源",
                code="invalid_spec",
                stage="input",
            )
        permission = {"id": permission_id, "weight": weight, "ext": ext}
        for field in ("columnPermissions", "rowPermissions"):
            if item.get(field) is not None:
                if not isinstance(item[field], dict):
                    raise DataEaseError(f"{field} 必须是对象或 null", code="invalid_spec", stage="input")
                permission[field] = item[field]
        normalized.append(permission)
    ids = [item["id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise DataEaseError("permissions 包含重复资源 ID", code="duplicate_permission", stage="input")
    return sorted(normalized, key=lambda item: item["id"])


def _normalize_role_permission_spec(spec: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(spec) - {"roleId", "scope", "permissions"})
    if unknown:
        raise DataEaseError(
            "角色权限配置包含未知字段",
            code="unknown_spec_fields",
            stage="input",
            details={"fields": unknown},
        )
    _validate_required(spec, ("roleId", "scope", "permissions"))
    if isinstance(spec["roleId"], bool):
        raise DataEaseError("roleId 必须是角色 ID", code="invalid_spec", stage="input")
    try:
        role_id = int(str(spec["roleId"]).strip())
    except (TypeError, ValueError) as exc:
        raise DataEaseError("roleId 必须是数字角色 ID", code="invalid_spec", stage="input") from exc
    return {
        "roleId": role_id,
        "scope": _role_permission_scope(spec["scope"]),
        "permissions": _permission_items(spec["permissions"]),
    }


def _permission_api_data(client: DataEaseClient, method: str, path: str, payload: Any = None) -> Any:
    try:
        return client.data(method, path, payload)
    except DataEaseError as exc:
        if exc.details.get("status") == 404:
            raise DataEaseError(
                "当前 DataEase 版本或版本授权未提供角色权限矩阵 API，请通过 UI 配置",
                code="capability_unavailable",
                stage="administration",
                details={"path": path},
            ) from exc
        raise


def _read_role_permission_scope(client: DataEaseClient, role_id: int | str, scope: str) -> dict[str, Any]:
    scope = _role_permission_scope(scope)
    if scope == "menu":
        value = _permission_api_data(client, "POST", "/auth/menuPermission", {"id": int(role_id)})
    else:
        value = _permission_api_data(
            client,
            "POST",
            "/auth/busiPermission",
            {"id": int(role_id), "type": 1, "flag": scope.upper()},
        )
    if not isinstance(value, dict):
        raise DataEaseError("权限接口未返回有效对象", code="invalid_response", stage="administration")
    return value


def _permission_summary(value: dict[str, Any]) -> dict[str, Any]:
    permissions = _permission_items(value.get("permissions"))
    return {
        "root": bool(value.get("root")),
        "readonly": bool(value.get("readonly")),
        "permission_count": len(permissions),
        "permissions_sha256": _digest(permissions),
    }


def _role_permission_patch(
    current_permissions: list[dict[str, Any]],
    desired_permissions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate a complete desired matrix into DataEase's incremental save DTO."""
    current_by_id = {item["id"]: item for item in current_permissions}
    desired_by_id = {item["id"]: item for item in desired_permissions}
    patch = [item for item in desired_permissions if current_by_id.get(item["id"]) != item]
    patch.extend(
        {"id": resource_id, "weight": 0, "ext": 0}
        for resource_id in sorted(set(current_by_id) - set(desired_by_id))
    )
    return patch


def _validate_row_column_permission_changes(
    current_permissions: list[dict[str, Any]],
    desired_permissions: list[dict[str, Any]],
) -> None:
    current_by_id = {item["id"]: item for item in current_permissions}
    desired_by_id = {item["id"]: item for item in desired_permissions}
    for resource_id in sorted(set(current_by_id) | set(desired_by_id)):
        current = current_by_id.get(resource_id, {})
        desired = desired_by_id.get(resource_id, {})
        if any(current.get(field) != desired.get(field) for field in ("columnPermissions", "rowPermissions")):
            raise DataEaseError(
                "数据集行列权限的变更需通过 DataEase UI 完成；当前命令只安全管理菜单和资源权重矩阵",
                code="capability_unavailable",
                stage="administration",
                details={"resource_id": str(resource_id)},
            )


def _role_permissions(args: Any, client: DataEaseClient) -> dict[str, Any]:
    role = _detail(client, "/role/detail/{id}", str(args.id))
    scope = _role_permission_scope(args.scope, allow_all=True)
    scopes = ROLE_PERMISSION_SCOPES if scope == "all" else (scope,)
    result = {
        item: _read_role_permission_scope(client, args.id, item)
        for item in scopes
    }
    return _envelope(
        "admin.role-permissions",
        {"role": _public_state("role", role), "scopes": result},
        adapter="official-api",
    )


def _role_permission_set(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "admin.role-permission-set"
    request_spec = _normalize_role_permission_spec(_load_spec(args.spec))
    role_id = str(request_spec["roleId"])
    role = _detail(client, "/role/detail/{id}", role_id)
    current = _read_role_permission_scope(client, role_id, request_spec["scope"])
    current_permissions = _permission_items(current.get("permissions"))
    _validate_row_column_permission_changes(current_permissions, request_spec["permissions"])
    if not args.apply:
        snapshot = _snapshot(settings, f"role-permissions-{request_spec['scope']}", role_id, current)
        plan = plans.create(
            operation,
            target={"id": role_id, "name": role.get("name"), "type": "role-permissions", "scope": request_spec["scope"]},
            changes=[
                {
                    "action": "replace-permission-matrix",
                    "scope": request_spec["scope"],
                    "before_count": len(current_permissions),
                    "after_count": len(request_spec["permissions"]),
                }
            ],
            risk="L3",
            spec={
                "role_id": role_id,
                "scope": request_spec["scope"],
                "payload_sha256": _digest(request_spec),
                "precondition_sha256": _digest(current),
                "role_precondition_sha256": _digest(role),
                "snapshot": snapshot,
            },
            rollback={"strategy": "restore-permission-snapshot", "snapshot": snapshot, "automatic": False},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])

    if not args.plan_id:
        raise DataEaseError("执行权限矩阵变更需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError("plan-id 不属于 admin.role-permission-set", code="invalid_plan", stage="safety")
    stored = plan["spec"]
    if _digest(request_spec) != stored.get("payload_sha256"):
        raise DataEaseError("apply 的权限配置与 dry-run 不一致", code="spec_changed", stage="safety")
    if _digest(role) != stored.get("role_precondition_sha256") or _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("角色或权限矩阵已变化，请重新 dry-run", code="target_changed", stage="safety")

    permission_patch = _role_permission_patch(current_permissions, request_spec["permissions"])
    payload = {"id": int(role_id), "permissions": permission_patch}
    if request_spec["scope"] == "menu":
        endpoint = "/auth/saveMenuPer"
    else:
        endpoint = "/auth/saveBusiPer"
        payload.update({"type": 1, "flag": request_spec["scope"].upper()})
    if permission_patch:
        _permission_api_data(client, "POST", endpoint, payload)
    after = _read_role_permission_scope(client, role_id, request_spec["scope"])
    after_permissions = _permission_items(after.get("permissions"))
    if after_permissions != request_spec["permissions"]:
        raise DataEaseError(
            "角色权限矩阵回读与请求不一致",
            code="verification_failed",
            stage="verification",
            details={"expected_count": len(request_spec["permissions"]), "actual_count": len(after_permissions)},
        )
    result = {
        "role": _public_state("role", role),
        "scope": request_spec["scope"],
        "before": _permission_summary(current),
        "after": _permission_summary(after),
    }
    audit_id = audit.write(
        operation,
        status="success",
        risk="L3",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(
        operation,
        result,
        mode="apply",
        adapter="official-api",
        artifacts=[stored["snapshot"]],
        audit_id=audit_id,
    )


def _create(
    args: Any,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    config = CREATE_OPERATIONS[args.action]
    operation = f"admin.{args.action}"
    if not args.apply:
        spec = _normalize_create_spec(args.action, _load_spec(args.spec))
        _validate_required(spec, config["required"])
        risk = "L1"
        role_state: list[dict[str, Any]] = []
        if args.action == "user-create":
            risk, role_state = _user_create_risk(client, spec)
        identity = str(spec[config["identity"]]).strip()
        changes = [{"action": "create", "resource": config["resource"]}]
        if args.action == "user-create":
            changes[0]["administrator_role"] = risk == "L3"
        plan_spec = {"payload_sha256": _digest(spec)}
        if args.action == "user-create":
            plan_spec["role_selection_sha256"] = _digest(role_state)
        plan = plans.create(
            operation,
            target={"type": config["resource"], config["identity"]: identity},
            changes=changes,
            risk=risk,
            spec=plan_spec,
            rollback={"strategy": "delete-created-resource", "requires_confirmation": True},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])

    if not args.plan_id:
        raise DataEaseError("执行创建需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError(f"plan-id 不属于 {operation}", code="invalid_plan", stage="safety")
    spec = _normalize_create_spec(args.action, _load_spec(args.spec))
    if _digest(spec) != plan.get("spec", {}).get("payload_sha256"):
        raise DataEaseError("apply 配置与 dry-run 内容不一致", code="spec_changed", stage="safety")
    if args.action == "user-create":
        required_risk, role_state = _user_create_risk(client, spec)
        if plan.get("risk") != required_risk:
            raise DataEaseError("操作风险等级已变化，请重新 dry-run", code="plan_risk_changed", stage="safety")
        if _digest(role_state) != plan.get("spec", {}).get("role_selection_sha256"):
            raise DataEaseError("所选角色已变化，请重新 dry-run", code="target_changed", stage="safety")
    resource_id = client.data("POST", config["endpoint"], spec)
    if resource_id is None:
        raise DataEaseError("创建接口没有返回资源 ID", code="invalid_response", stage="administration")
    detail = _detail(client, config["detail"], str(resource_id))
    if str(detail.get(config["identity"])) != str(spec.get(config["identity"])):
        raise DataEaseError("创建后身份字段回读不一致", code="verification_failed", stage="verification")
    result = _public_state(config["resource"], detail)
    if args.action == "user-create":
        result.update({
            "password_mode": "system_initial_password",
            "custom_password_applied": False,
            "password_change_required": True,
        })
    audit_id = audit.write(
        operation,
        status="success",
        risk=plan["risk"],
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def _edit(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    config = EDIT_OPERATIONS[args.action]
    operation = f"admin.{args.action}"
    if not args.apply:
        spec = _load_spec(args.spec)
        _validate_required(spec, config["required"])
        if args.action == "user-edit":
            _normalized_role_ids(spec.get("roleIds"))
        resource_id = str(spec["id"])
        current = _detail(client, config["detail"], resource_id)
        risk, permission_sensitive = _edit_risk(args.action, current, spec)
        snapshot = _snapshot(settings, config["resource"], resource_id, current)
        changes = [{"action": "update", "resource": config["resource"]}]
        if args.action in {"role-edit", "user-edit"}:
            changes[0]["permission_sensitive"] = permission_sensitive
        plan = plans.create(
            operation,
            target={
                "id": resource_id,
                "type": config["resource"],
                config["identity"]: current.get(config["identity"]),
            },
            changes=changes,
            risk=risk,
            spec={
                "id": resource_id,
                "payload_sha256": _digest(spec),
                "precondition_sha256": _digest(current),
                "snapshot": snapshot,
            },
            rollback={"strategy": "restore-snapshot", "snapshot": snapshot},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])

    if not args.plan_id:
        raise DataEaseError("执行编辑需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError(f"plan-id 不属于 {operation}", code="invalid_plan", stage="safety")
    spec = _load_digest_bound_spec(args, plan)
    stored = plan["spec"]
    current = _detail(client, config["detail"], str(stored["id"]))
    if _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("目标管理资源已变化，请重新 dry-run", code="target_changed", stage="safety")
    required_risk, _ = _edit_risk(args.action, current, spec)
    if plan.get("risk") != required_risk:
        raise DataEaseError("操作风险等级已变化，请重新 dry-run", code="plan_risk_changed", stage="safety")
    before = _public_state(config["resource"], current)
    client.data("POST", config["endpoint"], spec)
    after_detail = _detail(client, config["detail"], str(stored["id"]))
    if str(after_detail.get(config["identity"])) != str(spec.get(config["identity"])):
        raise DataEaseError("编辑后身份字段回读不一致", code="verification_failed", stage="verification")
    after = _public_state(config["resource"], after_detail)
    result = {"before": before, "after": after}
    audit_id = audit.write(
        operation,
        status="success",
        risk=plan["risk"],
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(
        operation,
        result,
        mode="apply",
        adapter="official-api",
        artifacts=[stored["snapshot"]],
        audit_id=audit_id,
    )


def _delete(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    config = DELETE_OPERATIONS[args.action]
    operation = f"admin.{args.action}"
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError(
                "管理资源删除没有已验证的自动恢复流程；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        if not args.id or not args.identity:
            raise DataEaseError("需要 --id 与身份字段", code="invalid_input", stage="input")
        current = _detail(client, config["detail"], str(args.id))
        if str(current.get(config["identity"])) != str(args.identity):
            raise DataEaseError("身份字段与目标资源不一致", code="target_mismatch", stage="safety")
        if args.action == "organization-delete":
            resource_exists = client.data("GET", f"/org/resourceExist/{args.id}")
            if resource_exists is True:
                raise DataEaseError("组织仍包含业务资源，拒绝删除", code="resource_not_empty", stage="safety")
        snapshot = _snapshot(settings, config["resource"], str(args.id), current)
        plan = plans.create(
            operation,
            target={
                "id": str(args.id),
                "type": config["resource"],
                config["identity"]: args.identity,
            },
            changes=[{"action": "delete", "resource": config["resource"]}],
            risk="L3",
            spec={
                "id": str(args.id),
                "precondition_sha256": _digest(current),
                "snapshot": snapshot,
            },
            rollback={"available": False, "reason": "未验证自动反删除接口", "snapshot": snapshot},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])

    if not args.plan_id:
        raise DataEaseError("执行删除需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError(f"plan-id 不属于 {operation}", code="invalid_plan", stage="safety")
    stored = plan["spec"]
    current = _detail(client, config["detail"], str(stored["id"]))
    if _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("目标管理资源已变化，请重新 dry-run", code="target_changed", stage="safety")
    response = client.data("POST", config["endpoint"].format(id=stored["id"]))
    try:
        remaining = client.data("GET", config["detail"].format(id=stored["id"]))
    except DataEaseError:
        remaining = None
    if isinstance(remaining, dict) and str(remaining.get("id")) == str(stored["id"]):
        raise DataEaseError("删除后管理资源仍然存在", code="verification_failed", stage="verification")
    result = {"id": stored["id"], "deleted": True, "response": response}
    audit_id = audit.write(
        operation,
        status="success",
        risk="L3",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(
        operation,
        result,
        mode="apply",
        adapter="official-api",
        artifacts=[stored["snapshot"]],
        audit_id=audit_id,
    )


def _user_enable(
    args: Any,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "admin.user-enable"
    if not args.apply:
        if not args.id or not args.account or args.enable is None:
            raise DataEaseError("需要 --id、--account 与 --enable", code="invalid_input", stage="input")
        current = _detail(client, "/user/queryById/{id}", str(args.id))
        if str(current.get("account")) != str(args.account):
            raise DataEaseError("--account 与目标用户不一致", code="target_mismatch", stage="safety")
        target_enable = args.enable == "true"
        risk = "L2" if target_enable else "L3"
        plan = plans.create(
            operation,
            target={"id": str(args.id), "account": args.account, "type": "user"},
            changes=[{"action": "enable" if target_enable else "disable", "resource": "user"}],
            risk=risk,
            spec={
                "id": str(args.id),
                "account": args.account,
                "enable": target_enable,
                "precondition_sha256": _digest(current),
            },
            rollback={"enable": bool(current.get("enable"))},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])

    if not args.plan_id:
        raise DataEaseError("执行用户状态变更需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError("plan-id 不属于 admin.user-enable", code="invalid_plan", stage="safety")
    stored = plan["spec"]
    current = _detail(client, "/user/queryById/{id}", str(stored["id"]))
    if _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("目标用户已变化，请重新 dry-run", code="target_changed", stage="safety")
    before = _public_state("user", current)
    client.data("POST", "/user/enable", {"id": stored["id"], "enable": stored["enable"]})
    after_detail = _detail(client, "/user/queryById/{id}", str(stored["id"]))
    if after_detail.get("enable") is not stored["enable"]:
        raise DataEaseError("用户状态回读不一致", code="verification_failed", stage="verification")
    after = _public_state("user", after_detail)
    result = {"before": before, "after": after}
    audit_id = audit.write(
        operation,
        status="success",
        risk=plan["risk"],
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def _user_reset_password(
    args: Any,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "admin.user-reset-password"
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError(
                "重置密码会使旧密码失效；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        if not args.id or not args.account:
            raise DataEaseError("需要 --id 与 --account", code="invalid_input", stage="input")
        current = _detail(client, "/user/queryById/{id}", str(args.id))
        if str(current.get("account")) != str(args.account):
            raise DataEaseError("--account 与目标用户不一致", code="target_mismatch", stage="safety")
        plan = plans.create(
            operation,
            target={"id": str(args.id), "account": args.account, "type": "user"},
            changes=[{"action": "reset-password", "resource": "user"}],
            risk="L3",
            spec={"id": str(args.id), "precondition_sha256": _digest(current)},
            rollback={"available": False, "reason": "旧密码无法恢复"},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])

    if not args.plan_id:
        raise DataEaseError("执行密码重置需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError("plan-id 不属于 admin.user-reset-password", code="invalid_plan", stage="safety")
    stored = plan["spec"]
    current = _detail(client, "/user/queryById/{id}", str(stored["id"]))
    if _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("目标用户已变化，请重新 dry-run", code="target_changed", stage="safety")
    response = client.data("POST", f"/user/resetPwd/{stored['id']}")
    result = {"id": stored["id"], "reset": True, "response": response}
    audit_id = audit.write(
        operation,
        status="success",
        risk="L3",
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def handle_admin_mutation(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    if args.action == "role-permissions":
        return _role_permissions(args, client)
    if args.action == "role-permission-set":
        return _role_permission_set(args, settings, client, plans, audit)
    if args.action in CREATE_OPERATIONS:
        return _create(args, client, plans, audit)
    if args.action in EDIT_OPERATIONS:
        return _edit(args, settings, client, plans, audit)
    if args.action in DELETE_OPERATIONS:
        return _delete(args, settings, client, plans, audit)
    if args.action == "user-enable":
        return _user_enable(args, client, plans, audit)
    if args.action == "user-reset-password":
        return _user_reset_password(args, client, plans, audit)
    raise DataEaseError(f"未实现管理命令: {args.action}", code="unsupported_operation", stage="routing")
