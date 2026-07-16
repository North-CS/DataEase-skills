from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .audit import AuditLog
from .client import DataEaseClient
from .config import Settings
from .errors import DataEaseError
from .redact import redact_configuration
from .safety import PlanStore


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
    safe_id = "".join(char for char in str(resource_id) if char.isalnum() or char in {"-", "_"})
    path = directory / f"{resource}-{safe_id}-{int(time.time())}.json"
    path.write_text(json.dumps(redact_configuration(data), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def _validate_required(spec: dict[str, Any], required: tuple[str, ...]) -> None:
    missing = [key for key in required if key not in spec or spec.get(key) in (None, "")]
    if missing:
        raise DataEaseError(f"配置缺少必填字段: {', '.join(missing)}", code="invalid_spec", stage="input")


def _load_plan(args: Any, client: DataEaseClient, plans: PlanStore, operation: str) -> dict[str, Any]:
    if not args.plan_id:
        raise DataEaseError("执行变更需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_plan_context(client))
    if plan.get("operation") != operation:
        raise DataEaseError(f"plan-id 不属于 {operation}", code="invalid_plan", stage="safety")
    return plan


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        records = value.get("records") or value.get("list") or []
        return [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []
    return []


def _report_public(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    fields = (
        "id",
        "taskId",
        "name",
        "title",
        "rtid",
        "rid",
        "format",
        "status",
        "lastExecTime",
        "lastExecStatus",
        "nextExecTime",
        "rateType",
        "rateVal",
        "startTime",
        "endTime",
        "retryEnable",
        "retryLimit",
        "retryInterval",
        "createTime",
    )
    return {key: value.get(key) for key in fields if key in value}


def _report_page(client: DataEaseClient, page: int = 1, size: int = 100, keyword: str = "") -> Any:
    return client.data("POST", f"/report/pager/{page}/{size}", {"keyword": keyword, "timeDesc": True})


def _report_record(client: DataEaseClient, task_id: str) -> dict[str, Any]:
    matches = [item for item in _records(_report_page(client)) if str(item.get("id") or item.get("taskId")) == str(task_id)]
    if len(matches) != 1:
        raise DataEaseError("找不到目标定时报告", code="resource_not_found", stage="report")
    return matches[0]


def _report_info(client: DataEaseClient, task_id: str) -> dict[str, Any]:
    value = client.data("GET", f"/report/info/{task_id}")
    if not isinstance(value, dict) or str(value.get("taskId")) != str(task_id):
        raise DataEaseError("找不到目标定时报告", code="resource_not_found", stage="report")
    return value


def _report_list(args: Any, client: DataEaseClient) -> dict[str, Any]:
    value = _report_page(client, args.page, args.size, args.keyword)
    if isinstance(value, dict) and isinstance(value.get("records"), list):
        safe = dict(value)
        safe["records"] = [_report_public(item) for item in value["records"]]
    else:
        safe = [_report_public(item) for item in _records(value)]
    return _envelope("report.list", safe)


def _report_create(args: Any, client: DataEaseClient, plans: PlanStore, audit: AuditLog) -> dict[str, Any]:
    operation = "report.create"
    if not args.apply:
        spec = _load_spec(args.spec)
        _validate_required(spec, ("name", "rid", "rtid", "rateType", "rateVal"))
        existing = [item for item in _records(_report_page(client, keyword=str(spec["name"]))) if item.get("name") == spec["name"]]
        if existing:
            raise DataEaseError("已存在同名定时报告", code="duplicate_resource", stage="safety")
        plan = plans.create(
            operation,
            target={"type": "report", "name": str(spec["name"])},
            changes=[{"action": "create-scheduled-report"}],
            risk="L3",
            spec={"payload_sha256": _digest(spec)},
            rollback={"strategy": "stop-and-delete-created-report"},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])
    plan = _load_plan(args, client, plans, operation)
    spec = _load_spec(args.spec)
    if _digest(spec) != plan["spec"].get("payload_sha256"):
        raise DataEaseError("apply 配置与 dry-run 内容不一致", code="spec_changed", stage="safety")
    if any(item.get("name") == spec.get("name") for item in _records(_report_page(client, keyword=str(spec.get("name"))))):
        raise DataEaseError("同名定时报告已出现，请重新 dry-run", code="target_changed", stage="safety")
    client.data("POST", "/report/create", spec)
    matches = [item for item in _records(_report_page(client, keyword=str(spec.get("name")))) if item.get("name") == spec.get("name")]
    if len(matches) != 1:
        raise DataEaseError("创建后无法唯一回读定时报告", code="verification_failed", stage="verification")
    result = _report_public(matches[0])
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def _report_update(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "report.update"
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError(
                "报告收件人与内容不会写入快照；dry-run 需要 --ack-no-rollback",
                code="rollback_ack_required",
                stage="safety",
            )
        spec = _load_spec(args.spec)
        _validate_required(spec, ("taskId", "name", "rid", "rtid", "rateType", "rateVal"))
        current = _report_info(client, str(spec["taskId"]))
        snapshot = _snapshot(settings, "report", str(spec["taskId"]), _report_public(current))
        plan = plans.create(
            operation,
            target={"type": "report", "id": str(spec["taskId"]), "name": current.get("name")},
            changes=[{"action": "update-scheduled-report"}],
            risk="L3",
            spec={
                "id": str(spec["taskId"]),
                "payload_sha256": _digest(spec),
                "precondition_sha256": _digest(current),
                "snapshot": snapshot,
            },
            rollback={"available": False, "reason": "隐私字段未持久化", "snapshot": snapshot},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])
    plan = _load_plan(args, client, plans, operation)
    spec = _load_spec(args.spec)
    stored = plan["spec"]
    if _digest(spec) != stored.get("payload_sha256"):
        raise DataEaseError("apply 配置与 dry-run 内容不一致", code="spec_changed", stage="safety")
    current = _report_info(client, stored["id"])
    if _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("定时报告已变化，请重新 dry-run", code="target_changed", stage="safety")
    client.data("POST", "/report/update", spec)
    after = _report_info(client, stored["id"])
    if after.get("name") != spec.get("name"):
        raise DataEaseError("更新后名称回读不一致", code="verification_failed", stage="verification")
    result = {"before": _report_public(current), "after": _report_public(after)}
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", artifacts=[stored["snapshot"]], audit_id=audit_id)


def _report_control(args: Any, client: DataEaseClient, plans: PlanStore, audit: AuditLog) -> dict[str, Any]:
    action = args.action
    operation = f"report.{action}"
    current = _report_record(client, args.id)
    if current.get("name") != args.name:
        raise DataEaseError("--name 与目标报告不一致", code="target_mismatch", stage="safety")
    risk = "L2" if action == "stop" else "L3"
    if not args.apply:
        plan = plans.create(
            operation,
            target={"type": "report", "id": str(args.id), "name": args.name},
            changes=[{"action": action, "resource": "scheduled-report"}],
            risk=risk,
            spec={"id": str(args.id), "precondition_sha256": _digest(current)},
            rollback={"strategy": "start" if action == "stop" else "stop"},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])
    plan = _load_plan(args, client, plans, operation)
    if str(plan["spec"].get("id")) != str(args.id) or _digest(current) != plan["spec"].get("precondition_sha256"):
        raise DataEaseError("目标报告与 dry-run 状态不一致", code="target_changed", stage="safety")
    endpoint_action = {"fire-now": "fireNow", "start": "start", "stop": "stop"}[action]
    response = client.data("POST", f"/report/{endpoint_action}/{args.id}", {})
    after = _report_record(client, args.id)
    result = {"before": _report_public(current), "after": _report_public(after), "response": response}
    audit_id = audit.write(operation, status="success", risk=risk, target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def _report_delete(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "report.delete"
    current = _report_info(client, args.id)
    if current.get("name") != args.name:
        raise DataEaseError("--name 与目标报告不一致", code="target_mismatch", stage="safety")
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError("删除报告不可自动恢复；dry-run 需要 --ack-no-rollback", code="rollback_ack_required", stage="safety")
        snapshot = _snapshot(settings, "report", args.id, _report_public(current))
        plan = plans.create(
            operation,
            target={"type": "report", "id": str(args.id), "name": args.name},
            changes=[{"action": "delete", "resource": "scheduled-report"}],
            risk="L3",
            spec={"id": str(args.id), "precondition_sha256": _digest(current), "snapshot": snapshot},
            rollback={"available": False, "reason": "未验证反删除接口", "snapshot": snapshot},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])
    plan = _load_plan(args, client, plans, operation)
    if _digest(current) != plan["spec"].get("precondition_sha256"):
        raise DataEaseError("目标报告已变化，请重新 dry-run", code="target_changed", stage="safety")
    response = client.data("POST", "/report/delete", [str(args.id)])
    if any(str(item.get("id") or item.get("taskId")) == str(args.id) for item in _records(_report_page(client))):
        raise DataEaseError("删除后报告仍然存在", code="verification_failed", stage="verification")
    result = {"id": str(args.id), "name": args.name, "deleted": True, "response": response}
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", artifacts=[plan["spec"]["snapshot"]], audit_id=audit_id)


def _webhook_public(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {key: value.get(key) for key in ("id", "name", "contentType", "ssl", "oid", "createTime") if key in value}
    raw_url = value.get("url")
    if isinstance(raw_url, str) and raw_url:
        parsed = urlparse(raw_url)
        result["endpoint"] = {"scheme": parsed.scheme, "host": parsed.hostname, "port": parsed.port}
    result["secret_configured"] = bool(value.get("secret"))
    return result


def _webhook_page(client: DataEaseClient, page: int = 1, size: int = 100, keyword: str = "") -> Any:
    return client.data("POST", f"/webhook/pager/{page}/{size}", {"keyword": keyword})


def _webhook_detail(client: DataEaseClient, webhook_id: str) -> dict[str, Any]:
    value = client.data("GET", f"/webhook/get/{webhook_id}")
    if not isinstance(value, dict) or str(value.get("id")) != str(webhook_id):
        raise DataEaseError("找不到目标 Webhook", code="resource_not_found", stage="webhook")
    return value


def _webhook_list(args: Any, client: DataEaseClient) -> dict[str, Any]:
    value = _webhook_page(client, args.page, args.size, args.keyword)
    if isinstance(value, dict) and isinstance(value.get("records"), list):
        safe = dict(value)
        safe["records"] = [_webhook_public(item) for item in value["records"]]
    else:
        safe = [_webhook_public(item) for item in _records(value)]
    return _envelope("webhook.list", safe)


def _webhook_save(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "webhook.save"
    if not args.apply:
        spec = _load_spec(args.spec)
        _validate_required(spec, ("name", "url", "contentType", "ssl", "msgTemplate"))
        webhook_id = str(spec.get("id") or "")
        current = _webhook_detail(client, webhook_id) if webhook_id else None
        if webhook_id and not args.ack_no_rollback:
            raise DataEaseError("Webhook 密钥不会写入快照；更新需要 --ack-no-rollback", code="rollback_ack_required", stage="safety")
        if not webhook_id and any(item.get("name") == spec.get("name") for item in _records(_webhook_page(client, keyword=str(spec.get("name"))))):
            raise DataEaseError("已存在同名 Webhook", code="duplicate_resource", stage="safety")
        snapshot = _snapshot(settings, "webhook", webhook_id, _webhook_public(current)) if current else None
        risk = "L3" if webhook_id else "L2"
        plan = plans.create(
            operation,
            target={"type": "webhook", "id": webhook_id or None, "name": spec.get("name")},
            changes=[{"action": "update" if webhook_id else "create", "resource": "webhook"}],
            risk=risk,
            spec={
                "id": webhook_id or None,
                "payload_sha256": _digest(spec),
                "precondition_sha256": _digest(current) if current else None,
                "snapshot": snapshot,
            },
            rollback=(
                {"available": False, "reason": "旧 Webhook 密钥未持久化", "snapshot": snapshot}
                if current
                else {"strategy": "delete-created-webhook"}
            ),
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot] if snapshot else [])
    plan = _load_plan(args, client, plans, operation)
    spec = _load_spec(args.spec)
    stored = plan["spec"]
    if _digest(spec) != stored.get("payload_sha256"):
        raise DataEaseError("apply 配置与 dry-run 内容不一致", code="spec_changed", stage="safety")
    if stored.get("id"):
        current = _webhook_detail(client, stored["id"])
        if _digest(current) != stored.get("precondition_sha256"):
            raise DataEaseError("Webhook 已变化，请重新 dry-run", code="target_changed", stage="safety")
    elif any(item.get("name") == spec.get("name") for item in _records(_webhook_page(client, keyword=str(spec.get("name"))))):
        raise DataEaseError("同名 Webhook 已出现，请重新 dry-run", code="target_changed", stage="safety")
    client.data("POST", "/webhook/save", spec)
    if stored.get("id"):
        after_raw = _webhook_detail(client, stored["id"])
    else:
        matches = [item for item in _records(_webhook_page(client, keyword=str(spec.get("name")))) if item.get("name") == spec.get("name")]
        if len(matches) != 1:
            raise DataEaseError("保存后无法唯一回读 Webhook", code="verification_failed", stage="verification")
        after_raw = _webhook_detail(client, str(matches[0].get("id")))
    result = _webhook_public(after_raw)
    audit_id = audit.write(operation, status="success", risk=plan["risk"], target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", artifacts=[stored["snapshot"]] if stored.get("snapshot") else [], audit_id=audit_id)


def _webhook_ssl(args: Any, client: DataEaseClient, plans: PlanStore, audit: AuditLog) -> dict[str, Any]:
    operation = "webhook.ssl"
    current = _webhook_detail(client, args.id)
    if current.get("name") != args.name:
        raise DataEaseError("--name 与目标 Webhook 不一致", code="target_mismatch", stage="safety")
    target_ssl = args.ssl == "true"
    risk = "L2" if target_ssl else "L3"
    if not args.apply:
        plan = plans.create(
            operation,
            target={"type": "webhook", "id": str(args.id), "name": args.name},
            changes=[{"action": "switch-ssl", "ssl": target_ssl}],
            risk=risk,
            spec={"id": str(args.id), "ssl": target_ssl, "precondition_sha256": _digest(current)},
            rollback={"ssl": bool(current.get("ssl"))},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"])
    plan = _load_plan(args, client, plans, operation)
    stored = plan["spec"]
    if stored.get("ssl") is not target_ssl or _digest(current) != stored.get("precondition_sha256"):
        raise DataEaseError("Webhook 与 dry-run 状态不一致", code="target_changed", stage="safety")
    client.data("POST", "/webhook/switchSsl", {"id": str(args.id), "ssl": target_ssl})
    after = _webhook_detail(client, args.id)
    if after.get("ssl") is not target_ssl:
        raise DataEaseError("SSL 状态回读不一致", code="verification_failed", stage="verification")
    result = {"id": str(args.id), "name": args.name, "before": bool(current.get("ssl")), "after": target_ssl}
    audit_id = audit.write(operation, status="success", risk=risk, target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", audit_id=audit_id)


def _webhook_delete(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    operation = "webhook.delete"
    current = _webhook_detail(client, args.id)
    if current.get("name") != args.name:
        raise DataEaseError("--name 与目标 Webhook 不一致", code="target_mismatch", stage="safety")
    if not args.apply:
        if not args.ack_no_rollback:
            raise DataEaseError("删除 Webhook 不可自动恢复；dry-run 需要 --ack-no-rollback", code="rollback_ack_required", stage="safety")
        snapshot = _snapshot(settings, "webhook", args.id, _webhook_public(current))
        plan = plans.create(
            operation,
            target={"type": "webhook", "id": str(args.id), "name": args.name},
            changes=[{"action": "delete", "resource": "webhook"}],
            risk="L3",
            spec={"id": str(args.id), "precondition_sha256": _digest(current), "snapshot": snapshot},
            rollback={"available": False, "reason": "Webhook 密钥未持久化", "snapshot": snapshot},
            context=_plan_context(client),
        )
        return _envelope(operation, plan, mode="dry-run", changes=plan["changes"], artifacts=[snapshot])
    plan = _load_plan(args, client, plans, operation)
    if _digest(current) != plan["spec"].get("precondition_sha256"):
        raise DataEaseError("Webhook 已变化，请重新 dry-run", code="target_changed", stage="safety")
    response = client.data("POST", "/webhook/delete", [str(args.id)])
    if any(str(item.get("id")) == str(args.id) for item in _records(_webhook_page(client))):
        raise DataEaseError("删除后 Webhook 仍然存在", code="verification_failed", stage="verification")
    result = {"id": str(args.id), "name": args.name, "deleted": True, "response": response}
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"), changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-api", artifacts=[plan["spec"]["snapshot"]], audit_id=audit_id)


def handle_automation_operation(
    args: Any,
    settings: Settings,
    client: DataEaseClient,
    plans: PlanStore,
    audit: AuditLog,
) -> dict[str, Any]:
    if args.domain == "report":
        if args.action == "list":
            return _report_list(args, client)
        if args.action == "info":
            return _envelope("report.info", _report_public(_report_info(client, args.id)))
        if args.action == "logs":
            value = client.data("POST", f"/report/logPager/{args.page}/{args.size}", {"taskId": str(args.id), "timeDesc": True})
            return _envelope("report.logs", redact_configuration(value))
        if args.action == "create":
            return _report_create(args, client, plans, audit)
        if args.action == "update":
            return _report_update(args, settings, client, plans, audit)
        if args.action in {"fire-now", "start", "stop"}:
            return _report_control(args, client, plans, audit)
        if args.action == "delete":
            return _report_delete(args, settings, client, plans, audit)
    if args.domain == "webhook":
        if args.action == "list":
            return _webhook_list(args, client)
        if args.action == "get":
            return _envelope("webhook.get", _webhook_public(_webhook_detail(client, args.id)))
        if args.action == "options":
            return _envelope("webhook.options", client.data("GET", "/webhook/options"))
        if args.action == "save":
            return _webhook_save(args, settings, client, plans, audit)
        if args.action == "ssl":
            return _webhook_ssl(args, client, plans, audit)
        if args.action == "delete":
            return _webhook_delete(args, settings, client, plans, audit)
    raise DataEaseError(
        f"未实现自动化操作: {args.domain}.{args.action}",
        code="unsupported_operation",
        stage="routing",
    )
