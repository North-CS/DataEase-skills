from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .admin_ops import _permission_items, _role_permission_patch
from .audit import AuditLog
from .client import DataEaseClient
from .config import Settings
from .datasets import DatasetService, profile_field
from .errors import DataEaseError
from .intelligence import build_visual_plan
from .model_ops import prepare_new_model_spec, validate_model_spec
from .safety import PlanStore
from .versioning import adapter_for_client


SUBJECT_TYPES = {"user": 0, "role": 1}
RESOURCE_SCOPES = {"panel", "screen", "dataset", "datasource", "data_filling"}
SCOPE_ALIASES = {"dashboard": "panel", "datav": "screen", "data-v": "screen", "datafilling": "data_filling"}


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
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _context(client: DataEaseClient) -> dict[str, Any]:
    version = client.data("GET", "/license/version")
    return {"base_url": client.settings.base_url, "api_prefix": client.settings.api_prefix,
            "org_id": client.settings.org_id or None, "version": version}


def _replace(value: Any, replacements: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    return replacements.get(str(value), value)


def _model_profile(model: dict[str, Any]) -> dict[str, Any]:
    fields = [profile_field(item) for item in model.get("allFields", []) if isinstance(item, dict)]
    return {
        "dataset": {"id": f"$model:{model['name']}", "name": model["name"]},
        "field_count": len(fields),
        "dimensions": [item for item in fields if item["semantic_role"] == "dimension"],
        "measures": [item for item in fields if item["semantic_role"] == "measure"],
        "dates": [item for item in fields if item["semantic_role"] == "date"],
        "identifiers": [item for item in fields if item["semantic_role"] == "identifier"],
        "sensitive_fields": [item for item in fields if item["sensitive"]],
        "fields": fields,
    }


def _quality(profile: dict[str, Any], fail_on_sensitive: bool) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    if not profile.get("fields"):
        issues.append("数据集没有字段")
    if not profile.get("measures") and not profile.get("identifiers"):
        issues.append("没有可用于指标的数值字段或标识符")
    sensitive = [item.get("name") for item in profile.get("sensitive_fields", [])]
    if sensitive:
        message = "发现敏感字段: " + ", ".join(str(item) for item in sensitive)
        (issues if fail_on_sensitive else warnings).append(message)
    return {"dataset": profile["dataset"], "passed": not issues, "issues": issues,
            "warnings": warnings, "field_count": profile.get("field_count", len(profile.get("fields", [])))}


def _sample_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("data", "records", "rows", "list"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
            if isinstance(nested, dict):
                rows = _sample_rows(nested)
                if rows:
                    return rows
    return []


def _sample_quality(client: DataEaseClient, payload: dict[str, Any], limit: int) -> dict[str, Any]:
    value = client.data("POST", "/datasetData/previewData", payload)
    rows = _sample_rows(value)[:limit]
    if not rows:
        return {"mode": "sample", "sample_rows": 0, "empty": True, "duplicate_rows": 0, "null_ratios": {}}
    keys = sorted({str(key) for row in rows for key in row})
    null_ratios = {
        key: round(sum(1 for row in rows if row.get(key) in (None, "")) / len(rows), 4)
        for key in keys
    }
    fingerprints = [json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in rows]
    return {"mode": "sample", "sample_rows": len(rows), "empty": False,
            "duplicate_rows": len(fingerprints) - len(set(fingerprints)), "null_ratios": null_ratios}


def _validate_metrics(metrics: Any, profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(metrics, list) or not metrics:
        raise DataEaseError("一站式执行必须提供非空 metrics，并逐项确认业务口径", code="metric_confirmation_required", stage="solution")
    fields_by_dataset = {
        str(profile["dataset"]["id"]): {str(field.get("name")) for field in profile.get("fields", [])}
        for profile in profiles
    }
    normalized: list[dict[str, Any]] = []
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict) or not metric.get("name") or not metric.get("dataset_id") \
                or not metric.get("field") or not metric.get("aggregation"):
            raise DataEaseError(f"metrics[{index}] 缺少 name/dataset_id/field/aggregation", code="invalid_spec", stage="solution")
        if metric.get("confirmed") is not True:
            raise DataEaseError(f"指标“{metric.get('name')}”尚未 confirmed=true", code="metric_confirmation_required", stage="solution")
        dataset_id = str(metric["dataset_id"])
        if dataset_id not in fields_by_dataset or str(metric["field"]) not in fields_by_dataset[dataset_id]:
            raise DataEaseError(f"指标字段不存在: {dataset_id}.{metric['field']}", code="field_not_found", stage="solution")
        normalized.append({key: metric.get(key) for key in ("name", "definition", "dataset_id", "field", "aggregation", "confirmed")})
    return normalized


def _apply_confirmed_metrics(visual: dict[str, Any], metrics: list[dict[str, Any]]) -> None:
    aggregations = {
        (str(metric["dataset_id"]), str(metric["field"])): str(metric["aggregation"])
        for metric in metrics
    }
    for chart in visual.get("charts", []):
        if not isinstance(chart, dict):
            continue
        dataset_id = str(chart.get("dataset_name") or chart.get("dataset_id") or "")
        fields = chart.get("y_axis") or []
        current = chart.get("y_aggregations") or []
        chart["y_aggregations"] = [
            aggregations.get((dataset_id, str(field)), str(current[index]) if index < len(current) else "sum")
            for index, field in enumerate(fields)
        ]


def build_solution_manifest(client: DataEaseClient, spec: dict[str, Any]) -> dict[str, Any]:
    version, adapter = adapter_for_client(client)
    adapter.require("solution_orchestration", version)
    name = str(spec.get("name") or "").strip()
    if not name:
        raise DataEaseError("方案必须包含 name", code="invalid_spec", stage="solution")
    dataset_ids = spec.get("datasets") or []
    models = spec.get("models") or []
    if not isinstance(dataset_ids, list) or not isinstance(models, list) or (not dataset_ids and not models):
        raise DataEaseError("方案至少需要 datasets 或 models", code="invalid_spec", stage="solution")
    service = DatasetService(client)
    profiles = [service.profile(str(item)) for item in dataset_ids]
    prepared_models: list[dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            raise DataEaseError("models 每项必须是对象", code="invalid_spec", stage="solution")
        if model.get("id"):
            raise DataEaseError("一站式编排中的 models 只允许新建；已有模型请先使用 model save 独立变更",
                                code="unsafe_composite_update", stage="safety")
        validate_model_spec(model)
        prepared = prepare_new_model_spec(model)
        prepared_models.append(prepared)
        profiles.append(_model_profile(prepared))
    quality_config = spec.get("quality") if isinstance(spec.get("quality"), dict) else {}
    quality_mode = str(quality_config.get("mode") or "metadata")
    if quality_mode not in {"metadata", "sample"}:
        raise DataEaseError("quality.mode 必须是 metadata 或 sample", code="invalid_spec", stage="solution")
    quality = [_quality(profile, bool(quality_config.get("fail_on_sensitive"))) for profile in profiles]
    if quality_mode == "sample":
        preview_payloads = [
            client.data("POST", f"/datasetTree/details/{profile['dataset']['id']}", {})
            for profile in profiles[:len(dataset_ids)]
        ] + prepared_models
        limit = int(quality_config.get("sample_limit") or 200)
        if limit < 1 or limit > 1000:
            raise DataEaseError("quality.sample_limit 必须在 1 到 1000", code="invalid_spec", stage="solution")
        for item, payload in zip(quality, preview_payloads):
            sample = _sample_quality(client, payload, limit)
            item["sample"] = sample
            if sample["empty"]:
                item["passed"] = False
                item["issues"].append("抽样预览没有返回数据")
    if any(not item["passed"] for item in quality):
        raise DataEaseError("数据质量门禁未通过", code="quality_gate_failed", stage="solution",
                            details={"datasets": [item for item in quality if not item["passed"]]})
    metrics = _validate_metrics(spec.get("metrics"), profiles)
    visual = spec.get("visual")
    if visual is None:
        visual = build_visual_plan(profiles, f"{name}驾驶舱", str(spec.get("busi_type") or "dataV"))
    if not isinstance(visual, dict) or not isinstance(visual.get("charts"), list) or not visual["charts"]:
        raise DataEaseError("visual 必须包含非空 charts", code="invalid_spec", stage="solution")
    _apply_confirmed_metrics(visual, metrics)
    permissions = spec.get("permissions") or []
    if not isinstance(permissions, list):
        raise DataEaseError("permissions 必须是数组", code="invalid_spec", stage="solution")
    for item in permissions:
        scope = SCOPE_ALIASES.get(str(item.get("scope") or "").lower(), str(item.get("scope") or "").lower()) if isinstance(item, dict) else ""
        if not isinstance(item, dict) or item.get("subject_type") not in SUBJECT_TYPES or scope not in RESOURCE_SCOPES:
            raise DataEaseError("permissions 项缺少有效 subject_type/scope", code="invalid_spec", stage="solution")
    report = spec.get("report")
    if report is not None and (not isinstance(report, dict) or not all(report.get(key) not in (None, "") for key in ("name", "rid", "rtid", "rateType", "rateVal"))):
        raise DataEaseError("report 缺少 name/rid/rtid/rateType/rateVal", code="invalid_spec", stage="solution")
    steps = [
        {"id": "quality", "action": f"{quality_mode}-quality-gate", "status": "ready"},
        {"id": "metrics", "action": "confirmed-metric-gate", "status": "ready", "count": len(metrics)},
        {"id": "models", "action": "create-dataset-models", "status": "ready", "count": len(models)},
        {"id": "visual", "action": "create-unpublished-visual", "status": "ready", "chart_count": len(visual["charts"])},
        {"id": "permissions", "action": "grant-resource-permissions", "status": "ready", "count": len(permissions)},
        {"id": "report", "action": "create-report-subscription", "status": "ready" if report else "skipped"},
    ]
    return {"name": name, "adapter": adapter.public_info(version), "quality": quality, "metrics": metrics,
            "visual": visual, "steps": steps,
            "rollback_order": ["report", "permissions", "visual", "models"],
            "limitations": ["quality.mode=metadata 只检查元数据；设置 quality.mode=sample 可增加最多 1000 行的空值率与重复行抽样检查。"]}


def _subject(client: DataEaseClient, subject_type: str, subject_id: str) -> dict[str, Any]:
    path = f"/user/queryById/{subject_id}" if subject_type == "user" else f"/role/detail/{subject_id}"
    value = client.data("GET", path)
    if not isinstance(value, dict):
        raise DataEaseError("找不到授权对象", code="resource_not_found", stage="solution")
    return value


def _report_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("records", "list", "items"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
    return []


def execute_solution(client: DataEaseClient, settings: Settings, spec: dict[str, Any],
                     manifest: dict[str, Any]) -> dict[str, Any]:
    created_models: list[dict[str, Any]] = []
    visual_id = ""
    visual_kind = str(manifest["visual"].get("kind") or spec.get("busi_type") or "dataV")
    permission_before: list[dict[str, Any]] = []
    report_id = ""
    rollback_errors: list[str] = []
    replacements: dict[str, Any] = {}
    try:
        for model in spec.get("models") or []:
            prepared_model = prepare_new_model_spec(model)
            response = client.data("POST", "/datasetTree/create", prepared_model)
            model_id = str(response.get("id") if isinstance(response, dict) else response)
            if not model_id:
                raise DataEaseError("模型创建未返回 ID", code="invalid_response", stage="solution")
            created_models.append({"id": model_id, "name": model["name"]})
            replacements[f"$model:{model['name']}"] = model_id

        visual_spec = _replace(manifest["visual"], replacements)
        from .visual_engine import MultiDataEaseChartEngine
        engine = MultiDataEaseChartEngine(settings.base_url, settings.access_key, settings.secret_key, settings=settings)
        visual_id, visual_url = engine.deploy_multi(
            str(visual_spec.get("title") or f"{manifest['name']}驾驶舱"), visual_spec["charts"],
            busi_type=visual_kind, theme=str(visual_spec.get("theme") or "neon-dark"),
            publish=False, append_timestamp=False,
        )
        visual_id = str(visual_id)
        replacements["$visual"] = visual_id

        for grant in spec.get("permissions") or []:
            grant = _replace(grant, replacements)
            subject_type = str(grant["subject_type"])
            subject_id = str(grant["subject_id"])
            subject = _subject(client, subject_type, subject_id)
            identity = str(subject.get("account") if subject_type == "user" else subject.get("name"))
            if identity != str(grant.get("identity")):
                raise DataEaseError("授权对象 identity 不匹配", code="target_mismatch", stage="solution")
            raw_scope = str(grant["scope"]).lower()
            scope = SCOPE_ALIASES.get(raw_scope, raw_scope)
            current_raw = client.data("POST", "/auth/busiPermission",
                                      {"id": int(subject_id), "type": SUBJECT_TYPES[subject_type], "flag": scope.upper()})
            current = _permission_items(current_raw.get("permissions") if isinstance(current_raw, dict) else [])
            desired_by_id = {item["id"]: item for item in current}
            resources = grant.get("resources") or [{"id": visual_id, "weight": grant.get("weight", 7), "ext": grant.get("ext", 0)}]
            for item in _permission_items(resources):
                desired_by_id[item["id"]] = item
            desired = sorted(desired_by_id.values(), key=lambda item: item["id"])
            permission_before.append({"subject_type": subject_type, "subject_id": subject_id,
                                      "scope": scope, "permissions": current})
            patch = _role_permission_patch(current, desired)
            if patch:
                client.data("POST", "/auth/saveBusiPer",
                            {"id": int(subject_id), "type": SUBJECT_TYPES[subject_type], "flag": scope.upper(),
                             "permissions": patch})
            after_raw = client.data("POST", "/auth/busiPermission",
                                    {"id": int(subject_id), "type": SUBJECT_TYPES[subject_type],
                                     "flag": scope.upper()})
            after = _permission_items(after_raw.get("permissions") if isinstance(after_raw, dict) else [])
            if after != desired:
                raise DataEaseError("资源权限保存后回读不一致", code="verification_failed", stage="solution",
                                    details={"subject_type": subject_type, "subject_id": subject_id,
                                             "scope": scope, "expected": desired, "actual": after})

        report_spec = spec.get("report")
        if report_spec:
            report_spec = _replace(report_spec, replacements)
            client.data("POST", "/report/create", report_spec)
            records = _report_records(client.data("POST", "/report/pager/1/100",
                                                  {"keyword": report_spec["name"], "timeDesc": True}))
            matches = [item for item in records if item.get("name") == report_spec["name"]]
            if len(matches) != 1:
                raise DataEaseError("报告创建后无法唯一回读", code="verification_failed", stage="solution")
            report_id = str(matches[0].get("taskId") or matches[0].get("id"))

        return {"models": created_models, "visual": {"id": visual_id, "type": visual_kind, "url": visual_url,
                                                       "published": False},
                "permissions_applied": len(permission_before),
                "report": {"id": report_id, "created": bool(report_id)}, "rollback_errors": []}
    except Exception as exc:
        if not report_id and isinstance(spec.get("report"), dict):
            try:
                pending_report = _replace(spec["report"], replacements)
                records = _report_records(client.data("POST", "/report/pager/1/100",
                                                      {"keyword": pending_report.get("name", ""), "timeDesc": True}))
                matches = [item for item in records if item.get("name") == pending_report.get("name")]
                if len(matches) == 1:
                    report_id = str(matches[0].get("taskId") or matches[0].get("id") or "")
            except Exception:
                rollback_errors.append("report-discovery")
        if report_id:
            try:
                client.data("POST", "/report/delete", [report_id])
            except Exception:
                rollback_errors.append("report")
        for item in reversed(permission_before):
            try:
                now_raw = client.data("POST", "/auth/busiPermission",
                                      {"id": int(item["subject_id"]), "type": SUBJECT_TYPES[item["subject_type"]],
                                       "flag": item["scope"].upper()})
                now = _permission_items(now_raw.get("permissions") if isinstance(now_raw, dict) else [])
                client.data("POST", "/auth/saveBusiPer",
                            {"id": int(item["subject_id"]), "type": SUBJECT_TYPES[item["subject_type"]],
                             "flag": item["scope"].upper(),
                             "permissions": _role_permission_patch(now, item["permissions"])})
            except Exception:
                rollback_errors.append(f"permission:{item['subject_type']}:{item['subject_id']}:{item['scope']}")
        if visual_id:
            try:
                client.data("POST", f"/dataVisualization/deleteLogic/{visual_id}/{visual_kind}")
            except Exception:
                rollback_errors.append("visual")
        for model in reversed(created_models):
            try:
                client.data("POST", f"/datasetTree/delete/{model['id']}", {})
            except Exception:
                rollback_errors.append(f"model:{model['id']}")
        if isinstance(exc, DataEaseError):
            exc.details.update({"automatic_rollback_errors": rollback_errors})
            raise
        raise DataEaseError("一站式编排执行失败", code="solution_failed", stage="solution",
                            details={"automatic_rollback_errors": rollback_errors}) from exc


def handle_solution_operation(args: Any, settings: Settings, client: DataEaseClient,
                              plans: PlanStore, audit: AuditLog) -> dict[str, Any]:
    operation = f"solution.{args.action}"
    spec = _load(args.spec)
    manifest = build_solution_manifest(client, spec)
    if args.action == "plan":
        return _envelope(operation, manifest)
    version, adapter = adapter_for_client(client)
    adapter.require("solution_orchestration", version, mutation=True, client=client)
    if not args.apply:
        plan = plans.create(operation, target={"name": manifest["name"], "type": "analytics-solution"},
                            changes=manifest["steps"], risk="L3",
                            spec={"payload_sha256": _digest(spec), "manifest_sha256": _digest(manifest)},
                            rollback={"strategy": "compensating-transaction", "order": manifest["rollback_order"],
                                      "automatic_on_failure": True}, context=_context(client))
        return _envelope(operation, plan, mode="dry-run", manifest=manifest)
    if not args.plan_id:
        raise DataEaseError("执行一站式编排需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_context(client))
    stored = plan.get("spec", {})
    if plan.get("operation") != operation or stored.get("payload_sha256") != _digest(spec) \
            or stored.get("manifest_sha256") != _digest(manifest):
        raise DataEaseError("方案或源数据结构在 dry-run 后已变化", code="target_changed", stage="safety")
    result = execute_solution(client, settings, spec, manifest)
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"),
                           changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter=adapter.name, audit_id=audit_id)
