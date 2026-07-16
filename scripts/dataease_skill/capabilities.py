from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import DataEaseClient
from .errors import DataEaseError


@dataclass(frozen=True)
class Probe:
    name: str
    method: str
    path: str
    payload: Any = None
    edition: str = "community"


PROBES = (
    Probe("version", "GET", "/license/version"),
    Probe("current_user", "GET", "/user/info"),
    Probe("datasets", "POST", "/datasetTree/tree", {"busiFlag": "dataset"}),
    Probe("datasources", "POST", "/datasource/tree", {"busiFlag": "datasource"}),
    Probe("datasource_types", "GET", "/datasource/types"),
    Probe("dashboards", "POST", "/dataVisualization/tree", {"busiFlag": "dashboard", "resourceTable": "core"}),
    Probe("datav", "POST", "/dataVisualization/tree", {"busiFlag": "dataV", "resourceTable": "core"}),
    Probe("organizations", "POST", "/org/page/tree", {"keyword": "", "desc": True}, "xpack"),
    Probe("users", "POST", "/user/pager/1/1", {}, "xpack"),
    Probe("roles", "POST", "/role/query", {"keyword": ""}, "xpack"),
    Probe("system_settings", "GET", "/sysParameter/basic/query"),
    Probe("authentication_settings", "GET", "/perSetting/basic/query", edition="xpack"),
    Probe("mfa_settings", "GET", "/perSetting/mfa/query", edition="xpack"),
    Probe("hmac_settings", "GET", "/perSetting/hmac/query", edition="xpack"),
    Probe("email_settings", "GET", "/email/setting/query", edition="xpack"),
    Probe("sso_authentication", "GET", "/setting/authentication/grid", edition="xpack"),
    Probe("data_filling", "POST", "/data-filling/tree", {"busiFlag": "dataFilling"}, "xpack"),
    Probe("scheduled_reports", "POST", "/report/pager/1/1", {"keyword": "", "timeDesc": True}, "xpack"),
    Probe("webhooks", "POST", "/webhook/pager/1/1", {"keyword": ""}, "xpack"),
    Probe("wecom", "GET", "/wecom/info", edition="xpack"),
    Probe("dingtalk", "GET", "/dingtalk/info", edition="xpack"),
    Probe("lark", "GET", "/lark/info", edition="xpack"),
    Probe("larksuite", "GET", "/larksuite/info", edition="xpack"),
)


class CapabilityService:
    def __init__(self, client: DataEaseClient):
        self.client = client

    def scan(self) -> dict[str, Any]:
        capabilities: dict[str, Any] = {}
        version: Any = None
        for probe in PROBES:
            try:
                response = self.client.request(probe.method, probe.path, payload=probe.payload)
                capabilities[probe.name] = {"available": True, "edition": probe.edition, "adapter": "official-api"}
                if probe.name == "version":
                    version = response.get("data") if isinstance(response, dict) else response
            except DataEaseError as exc:
                status = exc.details.get("status")
                capabilities[probe.name] = {
                    "available": False,
                    "edition": probe.edition,
                    "reason": "permission_denied" if status in {401, 403} else "not_available" if status == 404 else exc.code,
                    "status": status,
                }
        return {
            "version": version,
            "capabilities": capabilities,
            "fallback_order": ["official-api", "versioned-internal-api", "browser-automation", "manual-guidance"],
        }
