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


SETTING_SCOPES = {
    "system-basic": ("/sysParameter/basic/query", "/sysParameter/basic/save", "L2"),
    "auth-basic": ("/perSetting/basic/query", "/perSetting/baisc/save", "L3"),
    "auth-mfa": ("/perSetting/mfa/query", "/perSetting/mfa/save", "L3"),
    "auth-hmac": ("/perSetting/hmac/query", "/perSetting/hmac/save", "L3"),
    "email": ("/email/setting/query", "/email/setting/save", "L2"),
}

INTEGRATION_PROVIDERS = {"wecom", "dingtalk", "lark", "larksuite"}
SSO_PROVIDERS = {"ldap", "oidc", "cas", "oauth2", "saml2"}


def _sso_path_provider(provider: str) -> str:
    return "saml" if provider == "saml2" else provider


def _safe_settings(value: Any) -> Any:
    safe = redact_configuration(value)
    if not isinstance(safe, list):
        return safe
    private_keys = {"email.account", "email.pwd", "email.reci"}
    result: list[Any] = []
    for item in safe:
        if isinstance(item, dict) and str(item.get("pkey", "")).lower() in private_keys:
            masked = dict(item)
            masked["pval"] = "***REDACTED***"
            result.append(masked)
        else:
            result.append(item)
    return result


def _envelope(operation: str, result: Any, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": True,
        "operation": operation,
        "result": result,
        "warnings": extra.pop("warnings", []),
        **extra,
    }


def _load_spec(path: str) -> Any:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8-sig")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DataEaseError(f"JSON 配置无效: {exc}", code="invalid_spec", stage="input") from exc


def _digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _setting_items(value: Any, *, source: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise DataEaseError(
            f"{source}设置配置必须是 JSON 对象数组",
            code="invalid_spec" if source == "提交的" else "invalid_response",
            stage="input" if source == "提交的" else "settings",
        )
    keys = [str(item.get("pkey") or "").strip() for item in value]
    if any(not key for key in keys):
        raise DataEaseError(
            f"{source}每个设置项都必须包含 pkey",
            code="invalid_spec" if source == "提交的" else "invalid_response",
            stage="input" if source == "提交的" else "settings",
        )
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise DataEaseError(
            f"{source}设置包含重复 pkey: {', '.join(duplicates)}",
            code="duplicate_setting_key",
            stage="safety",
            details={"pkeys": duplicates},
        )
    return value


def _validate_setting_replacement(current: Any, spec: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current_items = _setting_items(current, source="当前")
    spec_items = _setting_items(spec, source="提交的")
    current_keys = {str(item["pkey"]).strip() for item in current_items}
    spec_keys = {str(item["pkey"]).strip() for item in spec_items}
    if current_keys != spec_keys:
        raise DataEaseError(
            "设置保存必须保留当前完整 pkey 集合；新增或删除设置项请使用 DataEase 官方升级或管理界面",
            code="setting_key_set_changed",
            stage="safety",
            details={
                "missing_pkeys": sorted(current_keys - spec_keys),
                "unexpected_pkeys": sorted(spec_keys - current_keys),
            },
        )
    return current_items, spec_items


def _block_unsafe_email_save(client: DataEaseClient, scope: str) -> None:
    if scope != "email":
        return
    version = None
    try:
        version = client.data("GET", "/license/version")
    except DataEaseError:
        pass
    if str(version or "").strip() == "2.10.25":
        raise DataEaseError(
            "DataEase 2.10.25 邮件保存接口实测可能追加重复配置；Skill 仅允许 setting-validate，禁止通过该接口保存",
            code="unsafe_setting_endpoint",
            stage="compatibility",
            details={"scope": "email", "version": "2.10.25", "safe_alternative": "admin setting-validate"},
        )


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


def _snapshot(settings: Settings, resource: str, data: Any) -> str:
    directory = settings.output_dir / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    safe_resource = "".join(char for char in resource if char.isalnum() or char in {"-", "_"})
    path = directory / f"{safe_resource}-{int(time.time())}.json"
    path.write_text(json.dumps(redact_configuration(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def _load_plan(args: Any, client: DataEaseClient, plans: PlanStore, operation: str) -> dict[str, Any]:
    if not args.plan_id:
        raise DataEaseError("执行变更需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError(f"plan-id 不属于 {operation}", code="invalid_plan", stage="safety")
    return plan


def _setting_save(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    query_endpoint, save_endpoint, risk = SETTING_SCOPES[args.scope]
    operation = "admin.setting-save"
    current = client.data("GET", query_endpoint)
    _block_unsafe_email_save(client, args.scope)
    if not args.apply:
        if risk == "L3" and not args.ack_no_rollback:
            raise DataEaseError(
                "认证设置可能包含不可回读密钥；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        spec = _load_spec(args.spec)
        current, spec = _validate_setting_replacement(current, spec)
        snapshot = _snapshot(settings, f"setting-{args.scope}", _safe_settings(current))
        plan = plans.create(
            operation,
            target={"type": "setting", "scope": args.scope},
            changes=[{"action": "replace-settings", "scope": args.scope, "item_count": len(spec)}],
            risk=risk,
            spec={
                "scope": args.scope,
                "payload_sha256": _digest(spec),
                "precondition_sha256": _digest(current),
                "snapshot": snapshot,
            },
            rollback={
                "strategy": "manual-restore-snapshot" if risk == "L2" else "manual-security-recovery",
                "snapshot": snapshot,
            },
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])

    plan = _load_plan(args, client, plans, operation)
    stored = plan["spec"]
    if stored.get("scope") != args.scope:
        raise DataEaseError("设置范围与 dry-run 不一致", code="spec_changed", stage="safety")
    spec = _load_spec(args.spec)
    current, spec = _validate_setting_replacement(current, spec)
    if _digest(spec) != stored.get("payload_sha256"):
        raise DataEaseError("apply 配置与 dry-run 内容不一致", code="spec_changed", stage="safety")
    if _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("设置已变化，请重新 dry-run", code="target_changed", stage="safety")
    client.data("POST", save_endpoint, spec)
    after = client.data("GET", query_endpoint)
    after_items = _setting_items(after, source="保存后")
    if {str(item["pkey"]).strip() for item in after_items} != {str(item["pkey"]).strip() for item in spec}:
        raise DataEaseError("设置保存后的 pkey 集合与计划不一致", code="verification_failed", stage="verification")
    result = {
        "scope": args.scope,
        "before": _safe_settings(current),
        "after": _safe_settings(after),
    }
    audit_id = audit.write(
        operation,
        status="success",
        risk=plan["risk"],
        target=plan.get("target"),
        changes=plan.get("changes"),
        result=result,
    )
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", artifacts=[stored["snapshot"]], audit_id=audit_id)


def _setting_validate(args: Any, client: DataEaseClient) -> dict[str, Any]:
    if args.scope != "email":
        raise DataEaseError("当前仅邮件设置提供官方校验接口", code="unsupported_operation", stage="settings")
    spec = _load_spec(args.spec)
    if not isinstance(spec, list):
        raise DataEaseError("邮件配置必须是 JSON 数组", code="invalid_spec", stage="input")
    response = client.data("POST", "/email/setting/validate", spec)
    return _envelope("admin.setting-validate", {"scope": "email", "valid": True, "response": response})


def _integration_info(client: DataEaseClient, provider: str) -> dict[str, Any]:
    value = client.data("GET", f"/{provider}/info")
    if not isinstance(value, dict):
        raise DataEaseError("平台配置接口返回无效", code="invalid_response", stage="integration")
    return value


def _integration_validate(args: Any, client: DataEaseClient) -> dict[str, Any]:
    spec = _load_spec(args.spec)
    if not isinstance(spec, dict):
        raise DataEaseError("平台配置必须是 JSON 对象", code="invalid_spec", stage="input")
    response = client.data("POST", f"/{args.provider}/validate", spec)
    return _envelope(
        "admin.integration-validate",
        {"provider": args.provider, "valid": True, "response": response},
    )


def _integration_save(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "admin.integration-save"
    current = _integration_info(client, args.provider)
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError(
                "平台密钥无法从脱敏快照中自动恢复；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        spec = _load_spec(args.spec)
        if not isinstance(spec, dict):
            raise DataEaseError("平台配置必须是 JSON 对象", code="invalid_spec", stage="input")
        required = {"appId", "appSecret", "callBack", "enable"} if args.provider in {"lark", "larksuite"} else {
            "corpId", "agentId", "appSecret", "callBack", "enable"
        }
        if args.provider == "dingtalk":
            required.add("appKey")
        missing = sorted(key for key in required if key not in spec or spec.get(key) in (None, ""))
        if missing:
            raise DataEaseError(f"平台配置缺少字段: {', '.join(missing)}", code="invalid_spec", stage="input")
        snapshot = _snapshot(settings, f"integration-{args.provider}", current)
        plan = plans.create(
            operation,
            target={"type": "integration", "provider": args.provider},
            changes=[{"action": "replace-integration-config", "provider": args.provider}],
            risk="L3",
            spec={
                "provider": args.provider,
                "payload_sha256": _digest(spec),
                "precondition_sha256": _digest(current),
                "snapshot": snapshot,
            },
            rollback={"available": False, "reason": "旧平台密钥不可回读", "snapshot": snapshot},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])

    plan = _load_plan(args, client, plans, operation)
    stored = plan["spec"]
    if stored.get("provider") != args.provider:
        raise DataEaseError("平台与 dry-run 不一致", code="spec_changed", stage="safety")
    spec = _load_spec(args.spec)
    if _digest(spec) != stored.get("payload_sha256"):
        raise DataEaseError("apply 配置与 dry-run 内容不一致", code="spec_changed", stage="safety")
    if _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("平台配置已变化，请重新 dry-run", code="target_changed", stage="safety")
    client.data("POST", f"/{args.provider}/create", spec)
    after = _integration_info(client, args.provider)
    result = {"provider": args.provider, "configuration": redact_configuration(after)}
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", artifacts=[stored["snapshot"]], audit_id=audit_id)


def _integration_enable(
    args: Any,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "admin.integration-enable"
    current = _integration_info(client, args.provider)
    target_enable = args.enable == "true"
    if not args.apply:
        plan = plans.create(
            operation,
            target={"type": "integration", "provider": args.provider},
            changes=[{"action": "enable" if target_enable else "disable", "provider": args.provider}],
            risk="L3",
            spec={
                "provider": args.provider,
                "enable": target_enable,
                "precondition_sha256": _digest(current),
            },
            rollback={"enable": bool(current.get("enable"))},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])
    plan = _load_plan(args, client, plans, operation)
    stored = plan["spec"]
    if stored.get("provider") != args.provider or stored.get("enable") is not target_enable:
        raise DataEaseError("平台状态参数与 dry-run 不一致", code="spec_changed", stage="safety")
    if _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("平台配置已变化，请重新 dry-run", code="target_changed", stage="safety")
    client.data("POST", f"/{args.provider}/switchEnable", {"enable": target_enable})
    after = _integration_info(client, args.provider)
    if after.get("enable") is not target_enable:
        raise DataEaseError("平台启用状态回读不一致", code="verification_failed", stage="verification")
    result = {"provider": args.provider, "before": bool(current.get("enable")), "after": target_enable}
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def _sso_grid(client: DataEaseClient) -> list[dict[str, Any]]:
    value = client.data("GET", "/setting/authentication/grid")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _sso_info(client: DataEaseClient, provider: str) -> dict[str, Any]:
    path_provider = _sso_path_provider(provider)
    value = client.data("GET", f"/setting/authentication/info/{path_provider}")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DataEaseError("SSO 配置接口返回无效", code="invalid_response", stage="authentication")
    return value


def _sso_validate(args: Any, client: DataEaseClient) -> dict[str, Any]:
    spec = _load_spec(args.spec)
    if not isinstance(spec, dict):
        raise DataEaseError("SSO 配置必须是 JSON 对象", code="invalid_spec", stage="input")
    response = client.data("POST", f"/setting/authentication/validate/{args.provider}", spec)
    return _envelope(
        "admin.sso-validate",
        {"provider": args.provider, "valid": True, "response": redact_configuration(response)},
    )


def _sso_save(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "admin.sso-save"
    current = _sso_info(client, args.provider)
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError(
                "SSO 密钥和证书字段无法从脱敏快照自动恢复；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        spec = _load_spec(args.spec)
        if not isinstance(spec, dict):
            raise DataEaseError("SSO 配置必须是 JSON 对象", code="invalid_spec", stage="input")
        snapshot = _snapshot(settings, f"sso-{args.provider}", current)
        plan = plans.create(
            operation,
            target={"type": "sso", "provider": args.provider},
            changes=[{"action": "replace-sso-config", "provider": args.provider}],
            risk="L3",
            spec={
                "provider": args.provider,
                "payload_sha256": _digest(spec),
                "precondition_sha256": _digest(current),
                "snapshot": snapshot,
            },
            rollback={"available": False, "reason": "旧 SSO 密钥或证书不可安全回读", "snapshot": snapshot},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])
    plan = _load_plan(args, client, plans, operation)
    stored = plan["spec"]
    if stored.get("provider") != args.provider:
        raise DataEaseError("SSO 类型与 dry-run 不一致", code="spec_changed", stage="safety")
    spec = _load_spec(args.spec)
    if _digest(spec) != stored.get("payload_sha256"):
        raise DataEaseError("apply 配置与 dry-run 内容不一致", code="spec_changed", stage="safety")
    if _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("SSO 配置已变化，请重新 dry-run", code="target_changed", stage="safety")
    path_provider = _sso_path_provider(args.provider)
    response = client.data("POST", f"/setting/authentication/save/{path_provider}", spec)
    after = _sso_info(client, args.provider)
    result = {
        "provider": args.provider,
        "configuration": redact_configuration(after),
        "response": redact_configuration(response),
    }
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", artifacts=[stored["snapshot"]], audit_id=audit_id)


def _sso_enable(args: Any, client: DataEaseClient, plans: PlanStore, audit: AuditLog) -> dict[str, Any]:
    operation = "admin.sso-enable"
    matches = [item for item in _sso_grid(client) if str(item.get("id")) == str(args.id)]
    if len(matches) != 1 or str(matches[0].get("name")) != str(args.name):
        raise DataEaseError("--id/--name 与 SSO 配置不一致", code="target_mismatch", stage="safety")
    current = matches[0]
    target_enable = args.enable == "true"
    if not args.apply:
        plan = plans.create(
            operation,
            target={"type": "sso", "id": str(args.id), "name": args.name},
            changes=[{"action": "enable" if target_enable else "disable", "resource": "sso"}],
            risk="L3",
            spec={"id": str(args.id), "enable": target_enable, "precondition_sha256": _digest(current)},
            rollback={"enable": bool(current.get("enable"))},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])
    plan = _load_plan(args, client, plans, operation)
    stored = plan["spec"]
    if stored.get("enable") is not target_enable or _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("SSO 状态与 dry-run 不一致", code="target_changed", stage="safety")
    client.data("POST", "/setting/authentication/switchEnable", {"id": str(args.id), "enable": target_enable})
    after_matches = [item for item in _sso_grid(client) if str(item.get("id")) == str(args.id)]
    if len(after_matches) != 1 or after_matches[0].get("enable") is not target_enable:
        raise DataEaseError("SSO 启用状态回读不一致", code="verification_failed", stage="verification")
    result = {"id": str(args.id), "name": args.name, "before": bool(current.get("enable")), "after": target_enable}
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def handle_settings_operation(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    if args.action == "setting-read":
        query_endpoint = SETTING_SCOPES[args.scope][0]
        return _envelope(
            "admin.setting-read",
            {"scope": args.scope, "configuration": _safe_settings(client.data("GET", query_endpoint))},
        )
    if args.action == "setting-save":
        return _setting_save(args, settings, client, plans, audit)
    if args.action == "setting-validate":
        return _setting_validate(args, client)
    if args.action == "integration-validate":
        return _integration_validate(args, client)
    if args.action == "integration-save":
        return _integration_save(args, settings, client, plans, audit)
    if args.action == "integration-enable":
        return _integration_enable(args, client, plans, audit)
    if args.action == "sso-list":
        return _envelope("admin.sso-list", redact_configuration(_sso_grid(client)))
    if args.action == "sso-status":
        return _envelope("admin.sso-status", client.data("GET", "/setting/authentication/status"))
    if args.action == "sso-info":
        return _envelope(
            "admin.sso-info",
            {"provider": args.provider, "configuration": redact_configuration(_sso_info(client, args.provider))},
        )
    if args.action == "sso-validate":
        return _sso_validate(args, client)
    if args.action == "sso-save":
        return _sso_save(args, settings, client, plans, audit)
    if args.action == "sso-enable":
        return _sso_enable(args, client, plans, audit)
    raise DataEaseError(f"未实现设置操作: {args.action}", code="unsupported_operation", stage="routing")
