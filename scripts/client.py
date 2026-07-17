"""Backward-compatible client wrapper over the DataEase Skill 2.1 core."""

from __future__ import annotations

from typing import Any

from dataease_skill.client import DataEaseClient as CoreClient
from dataease_skill.config import Settings


class DataEaseClient:
    def __init__(
        self,
        base_url: str,
        access_key: str = "",
        secret_key: str = "",
        *,
        settings: Settings | None = None,
    ):
        settings = settings or Settings.load().with_overrides(
            base_url=base_url.rstrip("/"),
            access_key=access_key,
            secret_key=secret_key,
        )
        self._core = CoreClient(settings)
        self.settings = settings
        self.base_url = settings.base_url
        self.api_prefix = settings.api_prefix
        self.access_key = settings.access_key
        self.secret_key = settings.secret_key
        if settings.org_id:
            self._core.switch_organization(settings.org_id)

    def _get_headers(self) -> dict[str, str]:
        return self._core._auth_headers()

    def _response(self, method: str, path: str, payload: Any = None, params: dict[str, Any] | None = None):
        url = f"{self.base_url}{self.api_prefix}/{path.lstrip('/')}"
        return self._core.session.request(
            method,
            url,
            headers=self._get_headers(),
            json=payload,
            params=params,
            verify=self.settings.verify,
            timeout=self.settings.timeout,
        )

    def get(self, path: str, params: dict[str, Any] | None = None):
        return self._response("GET", path, params=params)

    def post(self, path: str, payload: Any = None):
        return self._response("POST", path, payload=payload)

    def get_dataset_fields(self, dataset_id: str):
        return self.post(f"/datasetField/listByDatasetGroup/{dataset_id}").json()

    def update_publish_status(
        self,
        dashboard_id: str,
        name: str,
        status: int = 1,
        type: str = "dashboard",
        mobile_layout: bool = False,
        active_view_ids: list[str] | None = None,
    ):
        response = self.post("/dataVisualization/updatePublishStatus", {
            "id": dashboard_id,
            "name": name,
            "mobileLayout": mobile_layout,
            "activeViewIds": active_view_ids or [],
            "status": status,
            "type": type,
        })
        response.raise_for_status()
        return response.json()
