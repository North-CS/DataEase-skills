from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from .client import DataEaseClient
from .errors import DataEaseError


Version = tuple[int, int, int]


def parse_version(value: Any) -> Version:
    if isinstance(value, dict):
        value = value.get("version") or value.get("currentVersion") or value.get("data")
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(value or ""))
    if not match:
        raise DataEaseError(
            "无法识别 DataEase 版本",
            code="unknown_version",
            stage="versioning",
            details={"value_type": type(value).__name__},
        )
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def format_version(value: Version) -> str:
    return ".".join(str(item) for item in value)


@dataclass(frozen=True)
class VersionAdapter:
    name: str
    minimum: Version
    maximum: Version | None
    verified_through: Version
    visual_detail_mode: str
    linkage_resource_table: bool
    features: frozenset[str]
    # Features that have an explicit live verification at this adapter's
    # minimum version even though the full adapter has a lower general
    # mutation ceiling.  This prevents one verified workflow from silently
    # enabling unrelated high-risk writes on a newer release.
    verified_features: frozenset[str] = frozenset()

    def matches(self, version: Version) -> bool:
        return version >= self.minimum and (self.maximum is None or version < self.maximum)

    def is_verified(self, version: Version, feature: str | None = None) -> bool:
        return version <= self.verified_through or (
            feature is not None and feature in self.verified_features and version == self.minimum
        )

    def require(
        self,
        feature: str,
        version: Version,
        *,
        mutation: bool = False,
        client: DataEaseClient | None = None,
    ) -> None:
        if feature not in self.features:
            raise DataEaseError(
                f"DataEase {format_version(version)} 不支持能力: {feature}",
                code="capability_unavailable",
                stage="versioning",
                details={"adapter": self.name, "feature": feature},
            )
        allow_unverified = bool(
            client is not None and getattr(client.settings, "allow_unverified_version", False)
        ) or os.environ.get("DATAEASE_ALLOW_UNVERIFIED_VERSION", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        if mutation and not self.is_verified(version, feature) and not allow_unverified:
            raise DataEaseError(
                "当前 DataEase 版本高于适配层已验证版本；默认只允许读取，请先验证后再显式设置 DATAEASE_ALLOW_UNVERIFIED_VERSION=true",
                code="unverified_version_mutation",
                stage="versioning",
                details={
                    "version": format_version(version),
                    "adapter": self.name,
                    "verified_through": format_version(self.verified_through),
                },
            )

    def visual_detail(
        self,
        client: DataEaseClient,
        resource_id: str,
        busi_type: str,
        version: Version,
    ) -> dict[str, Any]:
        self.require("visual_component_edit", version)
        if self.visual_detail_mode == "legacy-get":
            value = client.data("GET", f"/dataVisualization/findById/{resource_id}/{busi_type}")
        else:
            value = client.data(
                "POST",
                "/dataVisualization/findById",
                {
                    "id": str(resource_id),
                    "busiFlag": busi_type,
                    "resourceTable": "snapshot",
                    "source": "main-edit",
                    "taskId": None,
                },
            )
        if not isinstance(value, dict):
            raise DataEaseError("可视化详情接口未返回对象", code="invalid_response", stage="versioning")
        return value

    def linkage_all_path(self, resource_id: str, resource_table: str = "core") -> str:
        if self.linkage_resource_table:
            return f"/linkage/getVisualizationAllLinkageInfo/{resource_id}/{resource_table}"
        return f"/linkage/getVisualizationAllLinkageInfo/{resource_id}"

    def public_info(self, version: Version) -> dict[str, Any]:
        return {
            "detected_version": format_version(version),
            "adapter": self.name,
            "verified": self.is_verified(version),
            "verified_through": format_version(self.verified_through),
            "verified_features": sorted(self.verified_features),
            "visual_detail_mode": self.visual_detail_mode,
            "linkage_resource_table": self.linkage_resource_table,
            "features": sorted(self.features),
        }


BASE_FEATURES = frozenset(
    {
        "visual_component_edit",
        "dataset_modeling",
        "calculated_fields",
        "sql_dataset",
        "dataset_parameters",
        "file_datasource",
        "row_column_permissions",
        "resource_permissions",
        "json_backup_restore",
        "solution_orchestration",
    }
)

ADAPTERS = (
    VersionAdapter(
        name="v2.7",
        minimum=(2, 7, 0),
        maximum=(2, 8, 0),
        verified_through=(2, 7, 1),
        visual_detail_mode="legacy-get",
        linkage_resource_table=False,
        features=BASE_FEATURES,
    ),
    VersionAdapter(
        name="v2.8-v2.9",
        minimum=(2, 8, 0),
        maximum=(2, 10, 0),
        verified_through=(2, 9, 0),
        visual_detail_mode="request-post",
        linkage_resource_table=False,
        features=BASE_FEATURES | {"plugin_management"},
    ),
    VersionAdapter(
        name="v2.10.0-v2.10.9",
        minimum=(2, 10, 0),
        maximum=(2, 10, 10),
        verified_through=(2, 10, 9),
        visual_detail_mode="request-post",
        linkage_resource_table=False,
        features=BASE_FEATURES | {"plugin_management", "dataset_export"},
    ),
    VersionAdapter(
        name="v2.10.10+",
        minimum=(2, 10, 10),
        maximum=(2, 10, 26),
        verified_through=(2, 10, 25),
        visual_detail_mode="request-post",
        linkage_resource_table=True,
        features=BASE_FEATURES | {"plugin_management", "dataset_export"},
    ),
    VersionAdapter(
        name="v2.10.26",
        minimum=(2, 10, 26),
        maximum=(2, 10, 27),
        verified_through=(2, 10, 25),
        visual_detail_mode="request-post",
        linkage_resource_table=True,
        features=BASE_FEATURES | {"plugin_management", "dataset_export"},
        verified_features=frozenset({"file_datasource"}),
    ),
    VersionAdapter(
        name="v2.10.27+",
        minimum=(2, 10, 27),
        maximum=None,
        verified_through=(2, 10, 25),
        visual_detail_mode="request-post",
        linkage_resource_table=True,
        features=BASE_FEATURES | {"plugin_management", "dataset_export"},
    ),
)


def select_adapter(value: Any) -> tuple[Version, VersionAdapter]:
    version = parse_version(value)
    for adapter in ADAPTERS:
        if adapter.matches(version):
            return version, adapter
    raise DataEaseError(
        f"DataEase {format_version(version)} 不在当前适配范围（最低 2.7.0）",
        code="unsupported_version",
        stage="versioning",
        details={"version": format_version(version), "minimum": "2.7.0"},
    )


def adapter_for_client(client: DataEaseClient) -> tuple[Version, VersionAdapter]:
    return select_adapter(client.data("GET", "/license/version"))
