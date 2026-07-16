from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

from cryptography.hazmat.primitives import padding as symmetric_padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asymmetric_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .errors import DataEaseError


def _base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _sign_jwt(payload: dict[str, str], secret_key: str) -> str:
    header_part = _base64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload_part = _base64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(secret_key.encode(), signing_input, hashlib.sha256).digest()
    return f"{header_part}.{payload_part}.{_base64url(signature)}"


def aes_encrypt(plain_text: str, secret_key: str, iv: str) -> str:
    key_bytes = secret_key.encode("utf-8")
    iv_bytes = iv.encode("utf-8")
    if len(key_bytes) not in (16, 24, 32):
        raise DataEaseError("Secret Key 必须是 16、24 或 32 字节", code="invalid_credentials", stage="authentication")
    if len(iv_bytes) != 16:
        raise DataEaseError("Access Key 必须是 16 字节", code="invalid_credentials", stage="authentication")
    padder = symmetric_padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plain_text.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key_bytes), modes.CBC(iv_bytes)).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode("ascii")


def build_ask_headers(access_key: str, secret_key: str) -> dict[str, str]:
    source = f"{access_key}|{uuid.uuid4()}|{int(time.time() * 1000)}"
    signature = aes_encrypt(source, secret_key, access_key)
    token = _sign_jwt({"accessKey": access_key, "signature": signature}, secret_key)
    return {
        "Accept": "application/json;charset=UTF-8",
        "Content-Type": "application/json",
        "accessKey": access_key,
        "signature": signature,
        "x-de-ask-token": token,
    }


def split_dekey(dekey: str) -> tuple[str, str]:
    separator = base64.urlsafe_b64encode(b"-pk_separator-").decode("ascii")
    parts = dekey.split(separator, 1)
    if len(parts) != 2 or not all(parts):
        raise DataEaseError("DataEase dekey 格式不符合预期", code="invalid_dekey", stage="authentication")
    return parts[0], parts[1]


def decrypt_dekey_public_key(cipher_text: str, key: str) -> str:
    key_bytes = key.encode("utf-8")
    if len(key_bytes) not in (16, 24, 32):
        raise DataEaseError("DataEase dekey 中的 AES key 长度不合法", code="invalid_dekey", stage="authentication")
    decryptor = Cipher(algorithms.AES(key_bytes), modes.CBC(b"0000000000000000")).decryptor()
    padded = decryptor.update(base64.b64decode(cipher_text)) + decryptor.finalize()
    unpadder = symmetric_padding.PKCS7(algorithms.AES.block_size).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8").strip()


def rsa_encrypt(plain_text: str, public_key: str) -> str:
    body = "\n".join(public_key[index:index + 64] for index in range(0, len(public_key), 64))
    pem = f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----\n"
    key = serialization.load_pem_public_key(pem.encode("ascii"))
    encrypted = key.encrypt(plain_text.encode("utf-8"), asymmetric_padding.PKCS1v15())
    return base64.b64encode(encrypted).decode("ascii")
