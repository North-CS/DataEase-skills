from __future__ import annotations

from typing import Any, Callable

from .client import DataEaseClient
from .errors import DataEaseError
from .redact import redact, redact_configuration
from .trees import flatten_tree


class PlatformService:
    def __init__(self, client: DataEaseClient):
        self.client = client

    def organizations(self) -> list[dict[str, Any]]:
        data = self.client.data("POST", "/org/page/tree", {"keyword": "", "desc": True})
        return flatten_tree(data if isinstance(data, list) else [])

    def resources(self, busi_type: str) -> list[dict[str, Any]]:
        data = self.client.data(
            "POST", "/dataVisualization/tree", {"busiFlag": busi_type, "resourceTable": "core"}
        )
        return flatten_tree(data if isinstance(data, list) else [], leaves_only=True)

    def datasources(self) -> list[dict[str, Any]]:
        data = self.client.data("POST", "/datasource/tree", {"busiFlag": "datasource"})
        return redact(flatten_tree(data if isinstance(data, list) else [], leaves_only=True))

    def users(self, page: int = 1, size: int = 100) -> Any:
        return redact(self.client.data("POST", f"/user/pager/{page}/{size}", {}))

    def roles(self, keyword: str = "") -> Any:
        return redact(self.client.data("POST", "/role/query", {"keyword": keyword}))

    def filling_forms(self) -> Any:
        data = self.client.data("POST", "/data-filling/tree", {"busiFlag": "dataFilling"})
        return redact(flatten_tree(data if isinstance(data, list) else [], leaves_only=True))

    def system_settings(self) -> dict[str, Any]:
        return self._configuration_group({
            "basic": "/sysParameter/basic/query",
            "defaults": "/sysParameter/defaultSettings",
            "request_timeout": "/sysParameter/requestTimeOut",
            "sharing": "/sysParameter/shareBase",
        })

    def authentication_settings(self) -> dict[str, Any]:
        return self._configuration_group({
            "basic": "/perSetting/basic/query",
            "mfa": "/perSetting/mfa/query",
            "mfa_status": "/perSetting/mfaStatus",
            "hmac": "/perSetting/hmac/query",
        })

    def _configuration_group(self, endpoints: dict[str, str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, path in endpoints.items():
            try:
                result[name] = {
                    "available": True,
                    "configuration": redact_configuration(self.client.data("GET", path)),
                }
            except DataEaseError as exc:
                result[name] = {
                    "available": False,
                    "reason": exc.code,
                    "status": exc.details.get("status"),
                }
        return result

    def integration_status(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in ("wecom", "dingtalk", "lark", "larksuite"):
            try:
                data = self.client.data("GET", f"/{name}/info")
                safe = redact_configuration(data)
                enabled = data.get("enable") if isinstance(data, dict) else None
                result[name] = {"available": True, "enabled": enabled, "configuration": safe}
            except DataEaseError as exc:
                result[name] = {"available": False, "reason": exc.code, "status": exc.details.get("status")}
        return result

    def scheduled_reports(self) -> Any:
        return redact_configuration(
            self.client.data("POST", "/report/pager/1/100", {"keyword": "", "timeDesc": True})
        )

    def webhooks(self) -> list[dict[str, Any]]:
        data = self.client.data("POST", "/webhook/pager/1/100", {"keyword": ""})
        records = data.get("records", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        return [
            {
                key: item.get(key)
                for key in ("id", "name", "contentType", "ssl")
                if key in item
            }
            for item in records
            if isinstance(item, dict)
        ]

    def sso_authentication(self) -> Any:
        return redact_configuration(self.client.data("GET", "/setting/authentication/grid"))

    def inventory(self) -> dict[str, Any]:
        checks: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("organizations", self.organizations),
            ("datasources", self.datasources),
            ("dashboards", lambda: self.resources("dashboard")),
            ("datav", lambda: self.resources("dataV")),
            ("users", lambda: self.users(size=20)),
            ("roles", self.roles),
            ("data_filling", self.filling_forms),
            ("system_settings", self.system_settings),
            ("authentication", self.authentication_settings),
            ("integrations", self.integration_status),
            ("sso_authentication", self.sso_authentication),
            ("scheduled_reports", self.scheduled_reports),
            ("webhooks", self.webhooks),
        )
        result: dict[str, Any] = {}
        for name, callback in checks:
            try:
                data = callback()
                result[name] = {"ok": True, "count": len(data) if isinstance(data, list) else None, "data": data}
            except DataEaseError as exc:
                result[name] = {"ok": False, "error": exc.to_dict()}
        return result
