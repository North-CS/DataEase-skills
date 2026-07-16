from __future__ import annotations

from typing import Any, Iterable


SENSITIVE_MARKERS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "secretkey",
    "secret_key",
    "appsecret",
    "app_secret",
    "accesskey",
    "access_key",
    "apikey",
    "api_key",
    "token",
    "authorization",
    "signature",
    "privatekey",
    "private_key",
    "clientsecret",
    "client_secret",
)


def is_sensitive_key(key: object) -> bool:
    normalized = str(key).replace("-", "_").lower()
    return any(marker in normalized for marker in SENSITIVE_MARKERS)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("***REDACTED***" if is_sensitive_key(key) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


def redact_configuration(value: Any) -> Any:
    """Redact secret field names and key/value-shaped setting records."""
    if isinstance(value, dict):
        semantic_key = next(
            (
                item
                for key, item in value.items()
                if str(key).replace("-", "_").lower() in {"key", "pkey", "param_key", "name", "code"}
                and isinstance(item, str)
            ),
            "",
        )
        secret_record = is_sensitive_key(semantic_key)
        result: dict[Any, Any] = {}
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            is_value_slot = normalized in {"value", "pval", "val", "param_value", "setting_value"}
            if is_sensitive_key(key) or (secret_record and is_value_slot):
                result[key] = "***REDACTED***"
            else:
                result[key] = redact_configuration(item)
        return result
    if isinstance(value, list):
        return [redact_configuration(item) for item in value]
    if isinstance(value, tuple):
        return [redact_configuration(item) for item in value]
    return value


def sanitize_text(text: str, secrets: Iterable[str]) -> str:
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "***REDACTED***")
    return result
