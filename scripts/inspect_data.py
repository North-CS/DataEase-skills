#!/usr/bin/env python3
"""
DataEase 数据集探索脚本
支持 AK/SK 和密码登录两种认证方式
"""
import os
import json
import sys
import argparse
import subprocess
import base64
import hashlib
import hmac
import time
import uuid
import shutil
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Add scripts to path for engine import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def load_dotenv():
    """加载 .env 文件"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")


def base64url(raw):
    """Base64 URL-safe 编码"""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def sign_jwt(payload, secret_key):
    """使用 HMAC-SHA256 签名 JWT"""
    header = {"alg": "HS256", "typ": "JWT"}
    header_part = base64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_part = base64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_part}.{payload_part}.{base64url(signature)}"


def aes_cipher_name(secret_key):
    """根据密钥长度返回 AES 加密算法名称"""
    length = len(secret_key.encode("utf-8"))
    if length == 16:
        return "aes-128-cbc"
    if length == 24:
        return "aes-192-cbc"
    if length == 32:
        return "aes-256-cbc"
    raise ValueError("Secret Key 长度必须是 16、24 或 32 字节")


def aes_encrypt(plain_text, secret_key, iv):
    """AES 加密"""
    if shutil.which("openssl") is None:
        raise RuntimeError("当前环境缺少 openssl 命令，无法生成鉴权签名")
    if len(iv.encode("utf-8")) != 16:
        raise ValueError("Access Key 长度必须是 16 字节，才能作为 AES IV")

    cmd = [
        "openssl", "enc", f"-{aes_cipher_name(secret_key)}",
        "-base64", "-A", "-nosalt",
        "-K", secret_key.encode("utf-8").hex(),
        "-iv", iv.encode("utf-8").hex(),
    ]
    proc = subprocess.run(cmd, input=plain_text.encode("utf-8"), capture_output=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(stderr or "openssl 加密失败")
    return proc.stdout.decode("utf-8").strip()


def build_ask_auth(access_key, secret_key):
    """构建 ASK 认证信息"""
    source = f"{access_key}|{uuid.uuid4()}|{int(time.time() * 1000)}"
    signature = aes_encrypt(source, secret_key, access_key)
    token = sign_jwt({"accessKey": access_key, "signature": signature}, secret_key)
    return {
        "access_key": access_key,
        "signature": signature,
        "x_de_ask_token": token,
    }


def get_headers_ask(ask_auth):
    """构建 ASK 认证请求头"""
    return {
        "Accept": "application/json;charset=UTF-8",
        "Content-Type": "application/json",
        "accessKey": ask_auth["access_key"],
        "signature": ask_auth["signature"],
        "X-DE-ASK-TOKEN": ask_auth["x_de_ask_token"],
    }


def fetch_dekey(base_url, api_prefix):
    """获取 dekey 用于密码登录"""
    url = f"{base_url.rstrip('/')}{api_prefix}/dekey"
    request = Request(url, headers={"Accept": "application/json;charset=UTF-8"}, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            data = payload.get("data")
            if not isinstance(data, str) or not data:
                raise ValueError("dekey 接口未返回有效字符串")
            return data
    except HTTPError as err:
        raise RuntimeError(f"获取 dekey 失败: {err.code}")


def split_dekey(dekey):
    """拆分 dekey"""
    separator = base64.urlsafe_b64encode(b"-pk_separator-").decode("ascii")
    if separator and separator in dekey:
        parts = dekey.split(separator, 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], parts[1]
    raise ValueError("dekey 格式不符合预期")


def format_public_key(public_key):
    """格式化公钥"""
    body = "\n".join(public_key[index:index + 64] for index in range(0, len(public_key), 64))
    return f"-----BEGIN PUBLIC KEY-----\n{body}\n-----END PUBLIC KEY-----\n"


def rsa_encrypt(plain_text, public_key):
    """RSA 加密"""
    import tempfile
    if shutil.which("openssl") is None:
        raise RuntimeError("当前环境缺少 openssl 命令")

    with tempfile.TemporaryDirectory(prefix="dataease-pubkey-") as tmpdir:
        key_path = Path(tmpdir) / "public.pem"
        key_path.write_text(format_public_key(public_key), encoding="utf-8")
        proc = subprocess.run(
            ["openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", str(key_path)],
            input=plain_text.encode("utf-8"),
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "RSA 加密失败")
        return base64.b64encode(proc.stdout).decode("ascii")


def login_with_password(base_url, api_prefix, username, password):
    """使用密码登录获取 x-de-token"""
    dekey = fetch_dekey(base_url, api_prefix)
    encrypted_pk, aes_key_str = split_dekey(dekey)

    # 解密获取公钥
    cmd = [
        "openssl", "enc", f"-{aes_cipher_name(aes_key_str)}", "-d",
        "-base64", "-A", "-nosalt",
        "-K", aes_key_str.encode("utf-8").hex(),
        "-iv", b"0000000000000000".hex(),
    ]
    proc = subprocess.run(cmd, input=encrypted_pk.encode("utf-8"), capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError("解密 dekey 失败")
    public_key = proc.stdout.decode("utf-8").strip()

    # RSA 加密用户名和密码
    encrypted_name = rsa_encrypt(username, dekey)
    encrypted_pwd = rsa_encrypt(password, dekey)
    login_origin = int(os.environ.get("DATAEASE_LOGIN_ORIGIN", "0"))

    payload = {
        "name": encrypted_name,
        "pwd": encrypted_pwd,
        "origin": login_origin,
    }

    url = f"{base_url.rstrip('/')}{api_prefix}/login/localLogin"
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            if result.get("code") not in (None, 0):
                raise RuntimeError(f"登录失败: {result.get('msg', '未知错误')}")
            return result.get("data")
    except HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"登录请求失败: {err.code} - {body}")


def get_headers_token(x_de_token):
    """构建 Token 认证请求头"""
    return {
        "Accept": "application/json;charset=UTF-8",
        "Content-Type": "application/json",
        "X-DE-TOKEN": x_de_token,
    }


def make_request(url, headers, payload=None, method="POST"):
    """发送 HTTP 请求"""
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"请求失败: {err.code} - {body}")


def list_datasets(base_url, api_prefix, headers):
    """列出所有数据集"""
    url = f"{base_url.rstrip('/')}{api_prefix}/datasetTree/tree"
    payload = {"busiFlag": "dataset"}
    result = make_request(url, headers, payload)

    nodes = result.get('data', [])
    datasets = []

    def collect_leaf(items):
        for item in items:
            if item.get('leaf'):
                datasets.append({"name": item.get('name'), "id": item.get('id')})
            children = item.get('children', [])
            if children:
                collect_leaf(children)

    collect_leaf(nodes)
    return datasets


def get_dataset_fields(base_url, api_prefix, headers, dataset_id):
    """获取数据集字段"""
    # 先尝试详情接口
    url = f"{base_url.rstrip('/')}{api_prefix}/datasetTree/details/{dataset_id}"
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            fields = result.get('data', {}).get('allFields', [])
            if fields:
                return fields
    except Exception:
        pass

    # 回退到字段列表接口
    url = f"{base_url.rstrip('/')}{api_prefix}/datasetField/listByDatasetGroup/{dataset_id}"
    result = make_request(url, headers, method="POST")
    return result.get('data', [])


def resolve_dataset_id(base_url, api_prefix, headers, name_or_id):
    """解析数据集名称为 ID"""
    if str(name_or_id).isdigit() and len(str(name_or_id)) > 10:
        return name_or_id

    datasets = list_datasets(base_url, api_prefix, headers)
    for ds in datasets:
        if ds['name'] == name_or_id:
            return ds['id']

    raise ValueError(f"未找到数据集: {name_or_id}")


def main():
    load_dotenv()

    base_url = os.environ.get("DATAEASE_BASE_URL", "")
    api_prefix = os.environ.get("DATAEASE_API_PREFIX", "/de2api")
    access_key = os.environ.get("DATAEASE_ACCESS_KEY", "")
    secret_key = os.environ.get("DATAEASE_SECRET_KEY", "")
    username = os.environ.get("DATAEASE_USERNAME", "")
    password = os.environ.get("DATAEASE_PASSWORD", "")

    if not base_url:
        print("Error: 请设置 DATAEASE_BASE_URL")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="探索 DataEase 数据集和字段")
    parser.add_argument("--list-datasets", action="store_true", help="列出所有数据集")
    parser.add_argument("--dataset", type=str, help="查看指定数据集的字段")
    args = parser.parse_args()

    # 认证：优先 AK/SK，否则用密码登录
    try:
        if access_key and secret_key:
            ask_auth = build_ask_auth(access_key, secret_key)
            headers = get_headers_ask(ask_auth)
            auth_mode = "AK/SK"
        elif username and password:
            x_de_token = login_with_password(base_url, api_prefix, username, password)
            headers = get_headers_token(x_de_token)
            auth_mode = "密码登录"
        else:
            print("Error: 请配置 AK/SK (DATAEASE_ACCESS_KEY + DATAEASE_SECRET_KEY) 或用户名密码 (DATAEASE_USERNAME + DATAEASE_PASSWORD)")
            sys.exit(1)
    except Exception as e:
        print(f"认证失败: {e}")
        sys.exit(1)

    if args.list_datasets:
        try:
            datasets = list_datasets(base_url, api_prefix, headers)
            print(json.dumps(datasets, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"获取数据集列表失败: {e}")
            sys.exit(1)

    elif args.dataset:
        try:
            dataset_id = resolve_dataset_id(base_url, api_prefix, headers, args.dataset)
            fields = get_dataset_fields(base_url, api_prefix, headers, dataset_id)
            result = [
                {"name": f['name'], "id": f['id'], "type": f.get('deType'), "dataeaseName": f.get('dataeaseName')}
                for f in fields
            ]
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"获取数据集字段失败: {e}")
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
