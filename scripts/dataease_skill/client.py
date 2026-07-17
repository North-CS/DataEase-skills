from __future__ import annotations

import base64
import binascii
import ipaddress
import json
from typing import Any
from urllib.parse import parse_qsl, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests.utils import should_bypass_proxies

from .config import Settings
from .crypto import build_ask_headers, decrypt_dekey_public_key, rsa_encrypt, split_dekey
from .errors import DataEaseError
from .redact import is_sensitive_key, redact, sanitize_text


SUCCESS_CODES = {None, 0, "0", 200, "200"}


def _payload_secrets(value: Any, *, sensitive: bool = False) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            child_sensitive = sensitive or is_sensitive_key(key) or normalized in {
                "configuration",
                "api_configuration",
                "url",
                "callback",
                "call_back",
                "content",
                "msg_template",
                "email_list",
                "dingtalk_group_list",
                "lark_group_list",
                "larksuite_group_list",
            }
            if normalized in {"configuration", "api_configuration"} and isinstance(item, str):
                try:
                    decoded = json.loads(base64.b64decode(item, validate=True).decode("utf-8"))
                    values.extend(_payload_secrets(decoded, sensitive=True))
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
                    pass
            if normalized in {"url", "callback", "call_back"} and isinstance(item, str):
                values.extend(value for _, value in parse_qsl(urlparse(item).query) if value)
            values.extend(_payload_secrets(item, sensitive=child_sensitive))
    elif isinstance(value, (list, tuple)):
        for item in value:
            values.extend(_payload_secrets(item, sensitive=sensitive))
    elif sensitive and isinstance(value, str) and value:
        values.append(value)
    return tuple(dict.fromkeys(values))


def _sanitize_value(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_value(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item, secrets) for item in value]
    if isinstance(value, str):
        return sanitize_text(value, secrets)
    return value


def _is_private_target(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").strip().lower()
    if hostname in {"localhost"} or hostname.endswith((".localhost", ".local", ".internal")):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def _trust_environment_proxy(settings: Settings) -> bool:
    if settings.proxy_mode == "environment":
        return True
    if settings.proxy_mode == "direct":
        return False
    if _is_private_target(settings.base_url):
        return False
    return not should_bypass_proxies(settings.base_url, no_proxy=settings.no_proxy or None)


class DataEaseClient:
    """Unified DataEase HTTP client with redacted errors and scoped auth."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.trust_env = _trust_environment_proxy(settings)
        retry = Retry(
            total=2,
            connect=2,
            read=1,
            backoff_factor=0.3,
            status_forcelist=(429, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self._token = settings.x_de_token

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "DataEaseClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.settings.base_url}{self.settings.api_prefix}/{path.lstrip('/')}"

    def _auth_headers(self) -> dict[str, str]:
        if self._token:
            return {
                "Accept": "application/json;charset=UTF-8",
                "Content-Type": "application/json",
                "x-de-token": self._token,
            }
        if self.settings.username and self.settings.password:
            self._token = self.login_with_password()
            return self._auth_headers()
        return build_ask_headers(self.settings.access_key, self.settings.secret_key)

    def login_with_password(self) -> str:
        dekey_payload = self.request("GET", "/dekey", authenticated=False)
        dekey = dekey_payload.get("data") if isinstance(dekey_payload, dict) else None
        if not isinstance(dekey, str) or not dekey:
            raise DataEaseError("dekey 接口未返回有效数据", code="invalid_dekey", stage="authentication")
        encrypted_public_key, aes_key = split_dekey(dekey)
        public_key = decrypt_dekey_public_key(encrypted_public_key, aes_key)
        payload = {
            "name": rsa_encrypt(self.settings.username, public_key),
            "pwd": rsa_encrypt(self.settings.password, public_key),
            "origin": self.settings.login_origin,
        }
        result = self.request("POST", "/login/localLogin", payload=payload, authenticated=False)
        data = result.get("data") if isinstance(result, dict) else None
        token = data.get("token") if isinstance(data, dict) else data
        if not isinstance(token, str) or not token:
            if isinstance(data, dict) and data.get("mfa"):
                raise DataEaseError("该账号需要完成 MFA 验证", code="mfa_required", stage="authentication")
            if isinstance(data, dict) and data.get("invalidPwd"):
                raise DataEaseError("该账号密码已失效或必须修改", code="password_change_required", stage="authentication")
            raise DataEaseError("登录成功响应中没有 token", code="missing_token", stage="authentication")
        return token

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Any = None,
        params: dict[str, Any] | None = None,
        authenticated: bool = True,
        timeout: float | None = None,
        raw: bool = False,
        files: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> Any:
        headers = self._auth_headers() if authenticated else {
            "Accept": "application/json;charset=UTF-8",
            "Content-Type": "application/json",
        }
        if files:
            headers.pop("Content-Type", None)
        active_secrets = tuple(
            secret for secret in (*self.settings.secrets, *_payload_secrets(payload), *_payload_secrets(form)) if secret
        )
        url = self._url(path)
        try:
            response = self.session.request(
                method.upper(),
                url,
                headers=headers,
                json=None if files else payload,
                data=form if files else None,
                files=files,
                params=params,
                timeout=timeout or self.settings.timeout,
                verify=self.settings.verify,
            )
        except requests.Timeout as exc:
            raise DataEaseError(
                f"请求超时: {method.upper()} {path}",
                code="request_timeout",
                stage="http",
                retryable=True,
            ) from exc
        except requests.RequestException as exc:
            message = sanitize_text(str(exc), self.settings.secrets)
            raise DataEaseError(
                f"连接 DataEase 失败: {message}",
                code="connection_error",
                stage="http",
                retryable=True,
            ) from exc

        if raw:
            if response.status_code >= 400:
                self._raise_http_error(method, path, response, secrets=active_secrets)
            return response

        try:
            body = response.json()
        except ValueError as exc:
            if response.status_code >= 400:
                self._raise_http_error(method, path, response, secrets=active_secrets)
            raise DataEaseError(
                f"接口未返回 JSON: {method.upper()} {path}",
                code="invalid_response",
                stage="http",
                details={"status": response.status_code},
            ) from exc

        if response.status_code >= 400:
            self._raise_http_error(method, path, response, body, secrets=active_secrets)
        if isinstance(body, dict) and body.get("code") not in SUCCESS_CODES:
            raise DataEaseError(
                sanitize_text(str(body.get("msg") or "DataEase 接口返回失败"), active_secrets),
                code="api_error",
                stage="api",
                details={
                    "path": path,
                    "api_code": body.get("code"),
                    "response": redact(_sanitize_value(body, active_secrets)),
                },
            )
        return body

    def _raise_http_error(
        self,
        method: str,
        path: str,
        response: requests.Response,
        body: Any = None,
        secrets: tuple[str, ...] = (),
    ) -> None:
        if body is None:
            text = sanitize_text(response.text[:1000], secrets or self.settings.secrets)
            body = {"body": text}
        raise DataEaseError(
            f"DataEase HTTP {response.status_code}: {method.upper()} {path}",
            code="http_error",
            stage="http",
            retryable=response.status_code in {429, 502, 503, 504},
            details={
                "status": response.status_code,
                "path": path,
                "response": redact(_sanitize_value(body, secrets or self.settings.secrets)),
            },
        )

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, payload: Any = None) -> Any:
        return self.request("POST", path, payload=payload)

    def data(self, method: str, path: str, payload: Any = None) -> Any:
        result = self.request(method, path, payload=payload)
        return result.get("data") if isinstance(result, dict) and "data" in result else result

    def switch_organization(self, org_id: str) -> str:
        result = self.post(f"/user/switch/{org_id}")
        data = result.get("data") if isinstance(result, dict) else None
        token = data.get("token") if isinstance(data, dict) else data
        if not isinstance(token, str) or not token:
            raise DataEaseError("切换组织后未返回 token", code="missing_token", stage="organization")
        self._token = token
        return token

    def ensure_organization(self, org_id: str) -> bool:
        """Switch only when the authenticated context is not already in the target org."""
        target = str(org_id).strip()
        if not target:
            return False
        current = self.data("GET", "/user/info")
        current_id = None
        if isinstance(current, dict):
            current_id = current.get("oid") or current.get("defaultOid") or current.get("orgId")
        if current_id is not None and str(current_id) == target:
            return False
        self.switch_organization(target)
        return True

    def public_diagnostics(self) -> dict[str, Any]:
        return {
            "settings": self.settings.public_dict(),
            "token_context": bool(self._token),
            "session_headers": [key for key in self.session.headers if not key.lower().startswith("authorization")],
        }
