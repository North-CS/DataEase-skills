from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from .errors import DataEaseError


def _parse_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise DataEaseError(
        f"无法解析布尔配置值: {value}",
        code="invalid_configuration",
        stage="configuration",
    )


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_prefix: str = "/de2api"
    access_key: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)
    username: str = ""
    password: str = field(default="", repr=False)
    login_origin: int = 0
    request_mode: str = "auto"
    proxy_mode: str = "auto"
    no_proxy: str = ""
    org_id: str = ""
    x_de_token: str = field(default="", repr=False)
    timeout: float = 30.0
    verify_ssl: bool = True
    ca_bundle: str = ""
    output_dir: Path = Path("output")
    skill_root: Path = Path(".")

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> "Settings":
        skill_root = Path(__file__).resolve().parents[2]
        env_path = Path(env_file) if env_file else skill_root / ".env"
        file_values = _read_env_file(env_path)

        def value(name: str, default: str = "") -> str:
            return os.environ.get(name, file_values.get(name, default))

        def value_or_default(name: str, default: str) -> str:
            configured = value(name, default).strip()
            return configured or default

        output_value = value("DATAEASE_OUTPUT_DIR")
        output_dir = Path(output_value).expanduser() if output_value else skill_root / "output"
        settings = cls(
            base_url=value("DATAEASE_BASE_URL").rstrip("/"),
            api_prefix="/" + value_or_default("DATAEASE_API_PREFIX", "/de2api").strip("/"),
            access_key=value("DATAEASE_ACCESS_KEY"),
            secret_key=value("DATAEASE_SECRET_KEY"),
            username=value("DATAEASE_USERNAME"),
            password=value("DATAEASE_PASSWORD"),
            login_origin=int(value_or_default("DATAEASE_LOGIN_ORIGIN", "0")),
            request_mode=value_or_default("DATAEASE_REQUEST_MODE", "auto"),
            proxy_mode=value_or_default("DATAEASE_PROXY_MODE", "auto"),
            no_proxy=value("DATAEASE_NO_PROXY", value("NO_PROXY")),
            org_id=value("DATAEASE_ORG_ID"),
            x_de_token=value("DATAEASE_X_DE_TOKEN"),
            timeout=float(value_or_default("DATAEASE_TIMEOUT", "30")),
            verify_ssl=_parse_bool(value_or_default("DATAEASE_VERIFY_SSL", "true"), True),
            ca_bundle=value("DATAEASE_CA_BUNDLE"),
            output_dir=output_dir.resolve(),
            skill_root=skill_root,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.base_url:
            raise DataEaseError(
                "缺少 DATAEASE_BASE_URL",
                code="missing_configuration",
                stage="configuration",
            )
        has_ask = bool(self.access_key and self.secret_key)
        has_password = bool(self.username and self.password)
        if not (has_ask or has_password or self.x_de_token):
            raise DataEaseError(
                "请配置 AK/SK、用户名/密码或 DATAEASE_X_DE_TOKEN",
                code="missing_credentials",
                stage="configuration",
            )
        if bool(self.access_key) != bool(self.secret_key):
            raise DataEaseError(
                "DATAEASE_ACCESS_KEY 与 DATAEASE_SECRET_KEY 必须成对配置",
                code="invalid_credentials",
                stage="configuration",
            )
        if self.request_mode not in {"auto", "gateway", "backend"}:
            raise DataEaseError(
                f"不支持的 DATAEASE_REQUEST_MODE: {self.request_mode}",
                code="invalid_configuration",
                stage="configuration",
            )
        if self.proxy_mode not in {"auto", "environment", "direct"}:
            raise DataEaseError(
                f"不支持的 DATAEASE_PROXY_MODE: {self.proxy_mode}",
                code="invalid_configuration",
                stage="configuration",
            )
        if self.timeout <= 0:
            raise DataEaseError(
                "DATAEASE_TIMEOUT 必须大于 0",
                code="invalid_configuration",
                stage="configuration",
            )

    @property
    def verify(self) -> bool | str:
        return self.ca_bundle or self.verify_ssl

    @property
    def secrets(self) -> tuple[str, ...]:
        return self.access_key, self.secret_key, self.password, self.x_de_token

    def with_overrides(self, **kwargs: object) -> "Settings":
        updated = replace(self, **{key: value for key, value in kwargs.items() if value not in (None, "")})
        updated.validate()
        return updated

    def public_dict(self) -> dict[str, object]:
        auth_mode = "token" if self.x_de_token else "password" if self.username and self.password else "ak_sk"
        return {
            "base_url": self.base_url,
            "api_prefix": self.api_prefix,
            "auth_mode": auth_mode,
            "request_mode": self.request_mode,
            "proxy_mode": self.proxy_mode,
            "org_id": self.org_id or None,
            "timeout": self.timeout,
            "verify_ssl": bool(self.verify_ssl or self.ca_bundle),
            "ca_bundle": bool(self.ca_bundle),
            "output_dir": str(self.output_dir),
        }
