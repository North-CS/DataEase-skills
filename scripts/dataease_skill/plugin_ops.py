from __future__ import annotations

import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

from .audit import AuditLog
from .client import DataEaseClient
from .errors import DataEaseError
from .safety import PlanStore
from .versioning import adapter_for_client


DRIVER_MARKERS = ("driver", "datasource", "database", "jdbc", "ds-")
MAX_LIST_TEXT_BYTES = 2048
MAX_PACKAGE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 100_000


def _envelope(operation: str, result: Any, **extra: Any) -> dict[str, Any]:
    return {"schema_version": 1, "ok": True, "operation": operation, "result": result,
            "warnings": extra.pop("warnings", []), **extra}


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package(path: str) -> tuple[Path, dict[str, Any]]:
    package = Path(path).expanduser().resolve()
    if not package.is_file():
        raise DataEaseError("插件包不存在", code="file_not_found", stage="plugin")
    if package.suffix.lower() not in {".jar", ".zip"}:
        raise DataEaseError("插件包扩展名必须是 .jar 或 .zip", code="invalid_plugin_package", stage="plugin")
    if package.stat().st_size <= 0:
        raise DataEaseError("插件包为空", code="invalid_plugin_package", stage="plugin")
    if package.stat().st_size > MAX_PACKAGE_BYTES:
        raise DataEaseError("插件包超过 512 MiB 安全上限", code="invalid_plugin_package", stage="plugin")
    archive = {"valid_zip": False, "entry_count": None, "manifest": False}
    try:
        with zipfile.ZipFile(package) as value:
            names = value.namelist()
            archive = {"valid_zip": True, "entry_count": len(names),
                       "manifest": any(name.upper() == "META-INF/MANIFEST.MF" for name in names)}
    except zipfile.BadZipFile:
        raise DataEaseError("插件包不是有效 ZIP/JAR 容器", code="invalid_plugin_package", stage="plugin")
    if archive["entry_count"] > MAX_ARCHIVE_ENTRIES:
        raise DataEaseError("插件包条目数量超过安全上限", code="invalid_plugin_package", stage="plugin")
    if not archive["manifest"]:
        raise DataEaseError("插件包缺少 META-INF/MANIFEST.MF", code="invalid_plugin_package", stage="plugin")
    return package, {"path": str(package), "bytes": package.stat().st_size,
                     "sha256": _file_digest(package), **archive}


def _context(client: DataEaseClient) -> dict[str, Any]:
    version = client.data("GET", "/license/version")
    return {"base_url": client.settings.base_url, "api_prefix": client.settings.api_prefix,
            "org_id": client.settings.org_id or None, "version": version}


def _plugins(client: DataEaseClient) -> list[dict[str, Any]]:
    version, adapter = adapter_for_client(client)
    adapter.require("plugin_management", version)
    value = client.data("GET", "/plugin/query")
    if not isinstance(value, list):
        raise DataEaseError("插件查询接口未返回数组", code="invalid_response", stage="plugin")
    return [item for item in value if isinstance(item, dict)]


def _is_driver(item: dict[str, Any]) -> bool:
    value = " ".join(str(item.get(key) or "") for key in ("name", "flag", "developer")).lower()
    return any(marker in value for marker in DRIVER_MARKERS)


def _plugin_summary(item: dict[str, Any]) -> dict[str, Any]:
    """Keep plugin inventory useful without returning embedded icons/binaries."""
    summary: dict[str, Any] = {}
    omitted: list[dict[str, Any]] = []
    for key, value in item.items():
        if isinstance(value, str) and len(value.encode("utf-8")) > MAX_LIST_TEXT_BYTES:
            raw = value.encode("utf-8")
            omitted.append({"field": key, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
            continue
        summary[key] = value
    if omitted:
        summary["omitted_payloads"] = omitted
    return summary


def _multipart(client: DataEaseClient, endpoint: str, package: Path, plugin_id: str = "") -> Any:
    with package.open("rb") as handle:
        files: dict[str, Any] = {"file": (package.name, handle, "application/octet-stream")}
        if plugin_id:
            files["request"] = (None, json.dumps({"id": str(plugin_id)}), "application/json")
        result = client.request("POST", endpoint, files=files, timeout=max(client.settings.timeout, 300))
    return result.get("data") if isinstance(result, dict) and "data" in result else result


def handle_plugin_operation(args: Any, client: DataEaseClient, plans: PlanStore,
                            audit: AuditLog) -> dict[str, Any]:
    domain = args.domain
    operation = f"{domain}.{args.action}"
    if args.action == "list":
        plugins = [_plugin_summary(item) for item in _plugins(client)]
        if domain == "driver":
            plugins = [{**item, "driver_candidate": _is_driver(item)} for item in plugins]
        return _envelope(operation, plugins, warnings=[] if domain == "plugin" else [
            "DataEase PluginVO 没有统一 driver 类型字段；driver list 返回全部插件并以 driver_candidate 做启发式标注。"
        ])
    if args.action == "package-check":
        _, metadata = _package(args.package)
        return _envelope(operation, metadata)

    version, adapter = adapter_for_client(client)
    adapter.require("plugin_management", version, mutation=True, client=client)
    before = _plugins(client)
    plugin_id = str(getattr(args, "plugin_id", "") or "")
    current = next((item for item in before if str(item.get("id")) == plugin_id), None) if plugin_id else None
    if args.action in {"update", "rollback", "uninstall"} and current is None:
        raise DataEaseError("找不到目标插件", code="resource_not_found", stage="plugin")
    package = None
    metadata = None
    if args.action in {"install", "update", "rollback"}:
        package, metadata = _package(args.package)
    if args.action == "uninstall" and not args.ack_no_rollback:
        raise DataEaseError("卸载插件无法自动恢复；需要 --ack-no-rollback", code="rollback_ack_required", stage="safety")
    target = {"id": plugin_id or None, "name": current.get("name") if current else package.name,
              "kind": domain, "current_version": current.get("version") if current else None}
    changes = [{"action": args.action, "package_sha256": metadata.get("sha256") if metadata else None}]
    if not args.apply:
        plan = plans.create(operation, target=target, changes=changes, risk="L3",
                            spec={"plugin_id": plugin_id or None, "package_sha256": metadata.get("sha256") if metadata else None,
                                  "precondition_sha256": _digest(before)},
                            rollback={"strategy": "uninstall-created-plugin-if-identifiable" if args.action == "install" else
                                      ("install-explicit-rollback-package" if args.action in {"update", "rollback"} else "unavailable"),
                                      "automatic": False}, context=_context(client))
        return _envelope(operation, plan, mode="dry-run", changes=changes)
    if not args.plan_id:
        raise DataEaseError("执行插件变更需要 --plan-id", code="plan_required", stage="safety")
    plan = plans.load(args.plan_id, args.confirm_token, expected_context=_context(client))
    stored = plan.get("spec", {})
    if plan.get("operation") != operation or stored.get("plugin_id") != (plugin_id or None) \
            or stored.get("precondition_sha256") != _digest(before):
        raise DataEaseError("插件状态或目标已变化，请重新 dry-run", code="target_changed", stage="safety")
    if metadata and stored.get("package_sha256") != metadata.get("sha256"):
        raise DataEaseError("插件包在 dry-run 后已变化", code="package_changed", stage="safety")
    if args.action == "install":
        response = _multipart(client, "/plugin/install", package)
    elif args.action in {"update", "rollback"}:
        response = _multipart(client, "/plugin/update", package, plugin_id)
    else:
        response = client.data("POST", f"/plugin/uninstall/{plugin_id}")
    after = _plugins(client)
    warnings: list[str] = []
    if args.action == "install":
        created = [item for item in after if str(item.get("id")) not in {str(value.get("id")) for value in before}]
        if not created:
            raise DataEaseError("安装后没有检测到新插件", code="verification_failed", stage="verification")
        changed = created
    elif args.action == "uninstall":
        if any(str(item.get("id")) == plugin_id for item in after):
            raise DataEaseError("卸载后插件仍存在", code="verification_failed", stage="verification")
        changed = [{"id": plugin_id, "removed": True}]
    else:
        updated = next((item for item in after if str(item.get("id")) == plugin_id), None)
        if updated is None:
            raise DataEaseError("更新后目标插件不存在", code="verification_failed", stage="verification")
        if updated == current:
            warnings.append("插件仍可回读，但版本元数据未变化；DataEase 不暴露已安装包摘要，请在隔离环境执行功能烟测。")
        changed = [updated]
    result = {"changed": changed, "response": response,
              "package": {key: metadata[key] for key in ("bytes", "sha256") if metadata and key in metadata} if metadata else None}
    audit_id = audit.write(operation, status="success", risk="L3", target=plan.get("target"),
                           changes=plan.get("changes"), result=result)
    plans.mark_applied(args.plan_id, audit_id)
    return _envelope(operation, result, mode="apply", adapter="official-plugin-api", audit_id=audit_id,
                     warnings=warnings)
