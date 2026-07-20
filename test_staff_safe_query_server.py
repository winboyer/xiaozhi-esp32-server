#!/usr/bin/env python3
"""
工地安全数据智能查询测试 HTTP 服务

启动后可通过 HTTP 请求触发测试查询，避免每次测试都要手动运行脚本。

启动方式：
    python test_staff_safe_query_server.py

接口：
    GET  /test/status          - 检查服务状态
    POST /test/query           - 提交单个查询测试
    POST /test/run-all         - 运行所有预设查询
    GET  /test/catalog         - 查看接口目录
    GET  /                     - 测试页面（HTML）

新增塔机静态数据查询：
    POST /test/building-progress  - 查询楼栋施工进度
    POST /test/crane-height       - 查询塔吊安装高度
    POST /test/device-status      - 查询设备运行状态
"""

import json
import sys
import os
import time
import base64
import uuid
import re
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, quote, urlencode

# ==================== 配置 ====================
BASE_URL = "http://127.0.0.1:8003"
SERVER_PORT = 8004

# ---- 塔机静态数据 API 配置 (来自 test_taji_static_data.py) ----
TAJI_AUTH_BASE_URL = "http://115.159.67.12:8081"
TAJI_DATA_BASE_URL = "http://115.159.67.12:8084"
TAJI_USERNAME = "jiangjunci"
TAJI_PASSWORD = "ZJWF2025"
TAJI_PROJECT_ID = "P000000073"

# 缓存 access_token (避免每次查询都重新登录)
_taji_token_cache = {"token": None, "expires_at": 0}

# ---- 电梯设备数据 API 配置 (来自 test_elevator_static_data.py) ----
ELEVATOR_QUERY_URL = "http://115.159.67.12:8090/api/device/query-exec"
ELEVATOR_DEVICE_ID = "tw_lifter_0616"
ELEVATOR_DEVICE_NUMBER = "0114004712251229001"  # 默认设备编号(1号楼左笼), 保留兼容

# 4个电梯设备列表
ELEVATOR_DEVICES = [
    {"building": "1号楼", "cage": "左笼", "device_number": "0114004712251229001"},
    {"building": "1号楼", "cage": "右笼", "device_number": "0114004612251229001"},
    {"building": "3号楼", "cage": "左笼", "device_number": "0114004612259160001"},
    {"building": "3号楼", "cage": "右笼", "device_number": "0114004712259160001"},
]

# ---- 大屏/定位/设备/人员数据 API 配置 (来自 test_staff_safe_data.py, RSA 签名认证) ----
DATA_API_BASE_URL = "https://dw.yzw.cn/open"
DATA_API_ACCESS_KEY = "be69162bdd4e46619ac95824a88b1ec2"
DATA_API_PROJECT_KEY = "e3ae0e4a0ab6478da33bce089237a9ed"
DATA_API_PRIVATE_KEY_BASE64 = (
    "MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGBAMjBwnRaM3p+uDJQ0WsESmaOIbgNOtvkIMacRuJK+okoIqJFeWQhjPvimnTaQdvHFuYemaLllkH5tWNTlxM4cwSDw7OISc/2wGcfn8jX+QWu46MohsfNGudBG+/izia3I3QtwZmlSDBRjOYK2KbmO853zMxZnyj2b5lLCo/nixnjAgMBAAECgYAPbPf2MCu7DCHQiyFneDDUhYC1kp3eevGolFlL/QsYK+A3y/loxlbKnSq7sz0scbVJB4cYzn+HrUDEE46AGK4zQt5B4EAqtDsyC0Lwjpo2O4ObrLPeSN+CehUZ4fnXqnPq+/+vwjflzysYPh8ij7FYGOhme2QpPgBlVNX9zYlQgQJBAOMFE3jN2WazdXZfmfQIJPjC6F0fIEhXgSyhqpxeB5iMOyu5jmI2HhMVmqUogvj3WNjwxeuO87DpoMDehoBBQIECQQDiYmt9UMEEIw3ko6zklUM6KOJuf4CuniCplW9B7W14QgSYF/fjQ+5J6MHSPIR5n4JSc5ih72qgfobSHtj+uyhjAkB8iLlQyKNcyk9CW1lJ2/nkGI99HekIpi/vOtQrqQ1DqpF+//BSgdtnnq9RsHKAfrdXcmUwPiACSXbstmVUD/eBAkBHNPnmcu4jZPtLvYf2ZlS9CHsgko5hXm+bp9tU+1+BghJ73J4mKAndyY6dmFd7Agc19BJAbVQ2o1W45ecPSMNNAkEAmxqzT4nt0pujXBP5XsLuta0WT9XszMNC1yJef1kcTCMHQGntmNHhD/oOheGyFGc+hOB6AfZbAim9GyCgBxQDMQ=="
)

# ---- RSA 私钥 (延迟加载, 来自 test_staff_safe_data.py) ----
_data_api_private_key = None

def _data_api_get_private_key():
    """加载 RSA 私钥, 自动尝试 PKCS#1 和 PKCS#8 格式"""
    global _data_api_private_key
    if _data_api_private_key is not None:
        return _data_api_private_key
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    formats = [
        ("PKCS#1", "-----BEGIN RSA PRIVATE KEY-----\n" + DATA_API_PRIVATE_KEY_BASE64 + "\n-----END RSA PRIVATE KEY-----"),
        ("PKCS#8", "-----BEGIN PRIVATE KEY-----\n" + DATA_API_PRIVATE_KEY_BASE64 + "\n-----END PRIVATE KEY-----"),
    ]
    for fmt_name, pem_str in formats:
        try:
            key = serialization.load_pem_private_key(pem_str.encode(), password=None, backend=default_backend())
            _data_api_private_key = key
            return key
        except Exception:
            pass
    return None

def _data_api_generate_sign(access_key: str, timestamp: str, nonce: str) -> str:
    """RSA SHA256WithRSA 签名 → Base64"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    private_key = _data_api_get_private_key()
    sign_source = access_key + timestamp + nonce
    signature = private_key.sign(sign_source.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(signature).decode()

def _data_api_build_request(path: str, extra_params: dict = None):
    """构建带 RSA 签名的请求 URL"""
    timestamp = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    raw_sign = _data_api_generate_sign(DATA_API_ACCESS_KEY, timestamp, nonce)
    encoded_sign = quote(raw_sign, safe="")
    parts = []
    if extra_params and "projectKey" in extra_params:
        parts.append(f"projectKey={quote(str(extra_params['projectKey']), safe='')}")
    parts.append(f"accessKey={quote(DATA_API_ACCESS_KEY, safe='')}")
    parts.append(f"timestamp={quote(timestamp, safe='')}")
    parts.append(f"nonce={quote(nonce, safe='')}")
    parts.append(f"sign={encoded_sign}")
    if extra_params:
        for key, val in extra_params.items():
            if key != "projectKey":
                parts.append(f"{key}={quote(str(val), safe='')}")
    full_url = f"{DATA_API_BASE_URL}/{path.lstrip('/')}?{'&'.join(parts)}"
    return full_url

def _data_api_post(path: str, extra_params: dict = None):
    """发送带 RSA 签名的 POST 请求, 返回响应 JSON"""
    url = _data_api_build_request(path, extra_params)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    resp = requests.post(url, json=extra_params, headers=headers, timeout=30)
    if resp.status_code == 200:
        return resp.json()
    print(f"  [数据API] POST {path} 失败: {resp.status_code}")
    return None

# 测试查询语句
TEST_QUERIES = [
    {"query": "查询今天人员总览", "description": "人员总览查询"},
    {"query": "看看最近告警记录", "description": "告警记录查询"},
    {"query": "今天班组出勤情况", "description": "班组出勤查询"},
    {"query": "人员定位24小时走势", "description": "人员定位统计查询"},
    {"query": "基站物资信息", "description": "基站物资查询"},
    {"query": "设备信息统计", "description": "设备统计查询"},
    {"query": "组织架构", "description": "组织架构查询"},
    {"query": "今天考勤统计", "description": "考勤统计查询"},
    # ---- 新增: 塔机静态数据查询 (默认查询所有数据) ----
    {"query": "查询全部楼栋施工进度", "description": "楼栋施工进度查询"},
    {"query": "查询全部塔吊安装高度", "description": "塔吊安装高度查询"},
    {"query": "查询全部设备运行状态", "description": "设备运行状态查询"},
]


# ==================== 塔机静态数据 API 函数 ====================

def _taji_load_public_key_from_pem(pem_str: str):
    """从 PEM 格式字符串加载 RSA 公钥"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend

    if not pem_str or not isinstance(pem_str, str):
        return None

    pem_clean = pem_str.strip()
    if "-----BEGIN" not in pem_clean:
        pem_clean = "-----BEGIN PUBLIC KEY-----\n" + pem_clean + "\n-----END PUBLIC KEY-----"

    try:
        public_key = serialization.load_pem_public_key(
            pem_clean.encode("utf-8"), backend=default_backend()
        )
        return public_key
    except Exception:
        if "-----BEGIN RSA PUBLIC KEY-----" not in pem_clean:
            try:
                pem_pkcs1 = pem_clean.replace(
                    "-----BEGIN PUBLIC KEY-----", "-----BEGIN RSA PUBLIC KEY-----"
                ).replace(
                    "-----END PUBLIC KEY-----", "-----END RSA PUBLIC KEY-----"
                )
                public_key = serialization.load_pem_public_key(
                    pem_pkcs1.encode("utf-8"), backend=default_backend()
                )
                return public_key
            except Exception:
                pass
        return None


def _taji_rsa_encrypt_pkcs1(public_key, plaintext: str) -> str:
    """RSA PKCS1v15 加密 (主方案, 与 Java Cipher RSA/ECB/PKCS1Padding 兼容)"""
    from cryptography.hazmat.primitives.asymmetric import padding

    plaintext_bytes = plaintext.encode("utf-8")
    key_size_bytes = public_key.key_size // 8
    max_plaintext_size = key_size_bytes - 11  # PKCS1v15 开销

    if len(plaintext_bytes) > max_plaintext_size:
        raise ValueError(
            f"明文过长 ({len(plaintext_bytes)} bytes), "
            f"RSA {public_key.key_size}-bit 最大加密 {max_plaintext_size} bytes"
        )

    ciphertext = public_key.encrypt(
        plaintext_bytes,
        padding.PKCS1v15(),
    )
    return base64.b64encode(ciphertext).decode("utf-8")


def _taji_rsa_encrypt_oaep(public_key, plaintext: str) -> str:
    """RSA OAEP/SHA-256 加密 (备选方案)"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    plaintext_bytes = plaintext.encode("utf-8")
    ciphertext = public_key.encrypt(
        plaintext_bytes,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode("utf-8")


def _taji_encrypt_login_data(public_key, username: str, password: str, encrypt_func_name: str = "pkcs1") -> dict:
    """加密登录凭证, 根据 encrypt_func_name 选择加密模式"""
    login_plaintext = json.dumps({
        "username": username,
        "password": password,
        "captcha": "",
        "checkKey": "",
        "token": "",
    }, ensure_ascii=False)

    if encrypt_func_name == "pkcs1":
        encrypted = _taji_rsa_encrypt_pkcs1(public_key, login_plaintext)
    else:
        encrypted = _taji_rsa_encrypt_oaep(public_key, login_plaintext)
    return {"encrypted_data": encrypted}


def _taji_get_access_token() -> str:
    """
    获取塔机数据 API 的 access_token (带缓存)
    工作流: 获取 RSA 公钥 → RSA 加密登录 → 返回 token
    """
    global _taji_token_cache

    # 检查缓存 (提前 5 分钟过期)
    now = time.time()
    if _taji_token_cache["token"] and now < _taji_token_cache["expires_at"] - 300:
        return _taji_token_cache["token"]

    # Step 1: 获取 RSA 公钥
    pub_key_url = f"{TAJI_AUTH_BASE_URL}/api/user/auth/public-key"
    try:
        resp = requests.get(pub_key_url, headers={"accept": "application/json"}, timeout=30)
        if resp.status_code != 200:
            print(f"  [塔机API] 获取公钥失败: {resp.status_code}")
            return None
        data = resp.json()
        pub_key_str = data.get("data", {}).get("public_key")
        if not pub_key_str:
            print(f"  [塔机API] 未找到公钥字段")
            return None
    except requests.RequestException as e:
        print(f"  [塔机API] 获取公钥异常: {e}")
        return None

    # 加载公钥
    public_key = _taji_load_public_key_from_pem(pub_key_str)
    if not public_key:
        print(f"  [塔机API] 公钥加载失败")
        return None

    # Step 2: 登录 (先尝试 PKCS1v15, 失败再尝试 OAEP, 与 test_taji_static_data.py 一致)
    login_url = f"{TAJI_AUTH_BASE_URL}/api/user/auth/login"
    login_headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
    }

    def _do_login(encrypt_mode: str) -> str:
        """执行一次登录尝试, 返回 token 或 None"""
        login_body = _taji_encrypt_login_data(public_key, TAJI_USERNAME, TAJI_PASSWORD, encrypt_func_name=encrypt_mode)
        resp = requests.post(login_url, json=login_body, headers=login_headers, timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return (
            data.get("data", {}).get("access_token")
            or data.get("data", {}).get("accessToken")
            or data.get("access_token")
            or data.get("accessToken")
            or data.get("token")
        )

    try:
        # 主方案: PKCS1v15
        token = _do_login("pkcs1")
        if not token:
            print(f"  [塔机API] PKCS1v15 登录失败, 尝试 OAEP/SHA-256...")
            token = _do_login("oaep")

        if token:
            _taji_token_cache = {"token": token, "expires_at": now + 3600}
            return token
        else:
            print(f"  [塔机API] 所有加密模式登录均失败")
            return None
    except requests.RequestException as e:
        print(f"  [塔机API] 登录异常: {e}")
        return None


def _taji_get_buildings(token: str) -> list:
    """
    获取所有楼栋信息 (循环分页)
    GET /api/data/buildings?project_id={project_id}
    """
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    all_buildings = []
    page = 1
    page_size = 100

    while True:
        url = f"{TAJI_DATA_BASE_URL}/api/data/buildings"
        params = {"page": page, "page_size": page_size, "project_id": TAJI_PROJECT_ID}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code != 200:
                break
            data = resp.json()
            items = (
                data.get("data", {}).get("list")
                or data.get("data", {}).get("records")
                or data.get("data", {}).get("items")
                or data.get("list")
                or data.get("data")
            )
            if isinstance(items, list):
                all_buildings.extend(items)
                if len(items) < page_size:
                    break
                page += 1
            else:
                break
        except requests.RequestException:
            break

    return all_buildings


def _taji_get_devices(token: str) -> list:
    """
    获取所有设备信息 (循环分页)
    GET /api/data/deviceinfos?project_id={project_id}
    """
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    all_devices = []
    page = 1
    page_size = 100

    while True:
        url = f"{TAJI_DATA_BASE_URL}/api/data/deviceinfos"
        params = {"page": page, "page_size": page_size, "project_id": TAJI_PROJECT_ID}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code != 200:
                break
            data = resp.json()
            items = (
                data.get("data", {}).get("list")
                or data.get("data", {}).get("records")
                or data.get("data", {}).get("items")
                or data.get("list")
                or data.get("data")
            )
            if isinstance(items, list):
                all_devices.extend(items)
                if len(items) < page_size:
                    break
                page += 1
            else:
                break
        except requests.RequestException:
            break

    return all_devices


# ==================== extra_fields 解析工具 ====================
def _parse_extra_fields(device: dict) -> list:
    """解析设备的 extra_fields, 自动处理 JSON 字符串和 list 两种格式"""
    device_info = device.get("device_info") or device.get("deviceInfo") or {}
    extra_fields_raw = device_info.get("extra_fields") or device_info.get("extraFields") or "[]"

    if isinstance(extra_fields_raw, str):
        try:
            return json.loads(extra_fields_raw)
        except (json.JSONDecodeError, TypeError):
            return []
    elif isinstance(extra_fields_raw, list):
        return extra_fields_raw
    return []


def _get_crane_height(device: dict) -> str:
    """从设备信息中提取塔机高度"""
    extra_fields = _parse_extra_fields(device)
    for field in extra_fields:
        if isinstance(field, dict) and field.get("label") == "塔机高度":
            return field.get("value", "")
    return ""


def _get_device_name(device: dict) -> str:
    """提取设备显示名称"""
    return device.get("device_name", "") or device.get("deviceName", "") or device.get("name", "")


def _get_building_name(building: dict) -> str:
    """提取楼栋显示名称"""
    return building.get("building_name", "") or building.get("buildingName", "") or building.get("name", "")


def _parse_online_status(status) -> str:
    """解析在线状态"""
    if status == 1 or status == "1":
        return "运行中"
    elif status == 0 or status == "0":
        return "已离线/停止"
    else:
        return f"未知状态 ({status})"


def _match_number(name: str, target: str) -> bool:
    """模糊匹配: 提取数字判断是否匹配"""
    numbers = re.findall(r'\d+', target)
    if numbers:
        for num in numbers:
            if num in name:
                return True
    return False


# ==================== 查询 1: 楼栋施工进度 ====================
def query_building_construction_progress(building_name: str = None) -> dict:
    """
    查询楼栋施工进度

    流程:
      1. 登录获取 access_token
      2. 调用 GET /api/data/buildings 获取所有楼栋
      3. 如果 building_name 为 None, 返回所有楼栋的施工进度
      4. 否则按 building_name 匹配单个楼栋, 返回 current_construction_floor 和 total_floor

    Args:
        building_name: 楼栋名称 (如 "1号楼"), 为 None 时返回所有楼栋

    Returns:
        结构化查询结果
    """
    start_time = time.time()

    try:
        token = _taji_get_access_token()
        if not token:
            return {
                "success": False,
                "error": "无法获取塔机数据 API 的 access_token",
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        buildings = _taji_get_buildings(token)
        if not buildings:
            return {
                "success": False,
                "error": "未获取到任何楼栋数据",
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        # 如果 building_name 为 None 或空, 返回所有楼栋
        if not building_name or not building_name.strip():
            all_progress = []
            for b in buildings:
                b_name = _get_building_name(b)
                current_floor = b.get("current_construction_floor") or b.get("currentConstructionFloor")
                total_floor = b.get("total_floor") or b.get("totalFloor")
                all_progress.append({
                    "building_name": b_name,
                    "current_construction_floor": current_floor,
                    "total_floor": total_floor,
                    "progress_display": f"{b_name} 当前施工至第 {current_floor} 层, 共 {total_floor} 层",
                })
            return {
                "success": True,
                "query_type": "楼栋施工进度",
                "all_buildings": True,
                "total_count": len(all_progress),
                "buildings": all_progress,
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        # 匹配指定楼栋
        name_clean = building_name.strip()
        matched = None
        for b in buildings:
            b_name = _get_building_name(b)
            if name_clean in b_name or b_name in name_clean:
                matched = b
                break

        if not matched:
            # 尝试提取数字模糊匹配
            for b in buildings:
                b_name = _get_building_name(b)
                if _match_number(b_name, name_clean):
                    matched = b
                    break

        if not matched:
            return {
                "success": False,
                "error": f"未找到与 '{building_name}' 匹配的楼栋信息",
                "available_buildings": [_get_building_name(b) for b in buildings[:20]],
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        building_display_name = _get_building_name(matched)
        current_floor = matched.get("current_construction_floor") or matched.get("currentConstructionFloor")
        total_floor = matched.get("total_floor") or matched.get("totalFloor")

        return {
            "success": True,
            "query_type": "楼栋施工进度",
            "building_name": building_display_name,
            "current_construction_floor": current_floor,
            "total_floor": total_floor,
            "progress_display": f"{building_display_name} 当前施工至第 {current_floor} 层, 共 {total_floor} 层",
            "raw_data": matched,
            "elapsed_seconds": round(time.time() - start_time, 2),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"查询楼栋施工进度异常: {str(e)}",
            "elapsed_seconds": round(time.time() - start_time, 2),
        }


# ==================== 查询 2: 塔吊安装高度 ====================
def query_crane_installation_height(device_name: str = None) -> dict:
    """
    查询塔吊的安装高度

    流程:
      1. 登录获取 access_token
      2. 调用 GET /api/data/deviceinfos 获取所有设备
      3. 如果 device_name 为 None, 返回所有塔吊的安装高度
      4. 否则按 device_name 匹配单个塔吊

    高度数据来源: device_info.extra_fields (JSON 字符串) 中 label="塔机高度" 的 value

    Args:
        device_name: 设备名称 (如 "塔吊1"), 为 None 时返回所有设备

    Returns:
        结构化查询结果
    """
    start_time = time.time()

    try:
        token = _taji_get_access_token()
        if not token:
            return {
                "success": False,
                "error": "无法获取塔机数据 API 的 access_token",
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        devices = _taji_get_devices(token)
        if not devices:
            return {
                "success": False,
                "error": "未获取到任何设备数据",
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        # 如果 device_name 为 None 或空, 返回所有设备高度
        if not device_name or not device_name.strip():
            all_heights = []
            for d in devices:
                d_name = _get_device_name(d)
                height = _get_crane_height(d)
                all_heights.append({
                    "device_name": d_name,
                    "crane_height": height if height else "无数据",
                })
            return {
                "success": True,
                "query_type": "塔吊安装高度",
                "all_devices": True,
                "total_count": len(all_heights),
                "devices": all_heights,
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        # 匹配指定设备
        name_clean = device_name.strip()
        matched = None
        for d in devices:
            d_name = _get_device_name(d)
            if name_clean in d_name or d_name in name_clean:
                matched = d
                break

        if not matched:
            for d in devices:
                d_name = _get_device_name(d)
                if _match_number(d_name, name_clean):
                    matched = d
                    break

        if not matched:
            return {
                "success": False,
                "error": f"未找到与 '{device_name}' 匹配的设备信息",
                "available_devices": [_get_device_name(d) for d in devices[:20]],
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        device_display_name = _get_device_name(matched)
        crane_height = _get_crane_height(matched)

        if not crane_height:
            return {
                "success": False,
                "error": f"设备 '{device_display_name}' 的 extra_fields 中未找到 '塔机高度' 信息",
                "device_name": device_display_name,
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        return {
            "success": True,
            "query_type": "塔吊安装高度",
            "device_name": device_display_name,
            "crane_height": crane_height,
            "height_display": f"{device_display_name} 的塔机安装高度为 {crane_height}",
            "raw_data": matched,
            "elapsed_seconds": round(time.time() - start_time, 2),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"查询塔吊安装高度异常: {str(e)}",
            "elapsed_seconds": round(time.time() - start_time, 2),
        }


# ==================== 查询 3: 设备运行状态 ====================
def query_device_online_status(device_name: str = None) -> dict:
    """
    查询设备的运行状态

    流程:
      1. 登录获取 access_token
      2. 调用 GET /api/data/deviceinfos 获取所有设备
      3. 如果 device_name 为 None, 返回所有设备的运行状态
      4. 否则按 device_name 匹配单个设备

    Args:
        device_name: 设备名称 (如 "塔吊1"), 为 None 时返回所有设备

    Returns:
        结构化查询结果
    """
    start_time = time.time()

    try:
        token = _taji_get_access_token()
        if not token:
            return {
                "success": False,
                "error": "无法获取塔机数据 API 的 access_token",
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        devices = _taji_get_devices(token)
        if not devices:
            return {
                "success": False,
                "error": "未获取到任何设备数据",
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        # 如果 device_name 为 None 或空, 返回所有设备状态
        if not device_name or not device_name.strip():
            all_status = []
            for d in devices:
                d_name = _get_device_name(d)
                online_status = d.get("online_status") or d.get("onlineStatus")
                all_status.append({
                    "device_name": d_name,
                    "online_status": online_status,
                    "status_text": _parse_online_status(online_status),
                })
            return {
                "success": True,
                "query_type": "设备运行状态",
                "all_devices": True,
                "total_count": len(all_status),
                "devices": all_status,
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        # 匹配指定设备
        name_clean = device_name.strip()
        matched = None
        for d in devices:
            d_name = _get_device_name(d)
            if name_clean in d_name or d_name in name_clean:
                matched = d
                break

        if not matched:
            for d in devices:
                d_name = _get_device_name(d)
                if _match_number(d_name, name_clean):
                    matched = d
                    break

        if not matched:
            return {
                "success": False,
                "error": f"未查到设备信息: 未找到与 '{device_name}' 匹配的设备",
                "available_devices": [_get_device_name(d) for d in devices[:20]],
                "elapsed_seconds": round(time.time() - start_time, 2),
            }

        device_display_name = _get_device_name(matched)
        online_status = matched.get("online_status") or matched.get("onlineStatus")
        status_text = _parse_online_status(online_status)

        return {
            "success": True,
            "query_type": "设备运行状态",
            "device_name": device_display_name,
            "online_status": online_status,
            "status_display": f"{device_display_name} 当前状态: {status_text}",
            "raw_data": matched,
            "elapsed_seconds": round(time.time() - start_time, 2),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"查询设备运行状态异常: {str(e)}",
            "elapsed_seconds": round(time.time() - start_time, 2),
        }


# ==================== 电梯设备查询函数 (来自 test_elevator_static_data.py) ====================

def _elevator_default_start_time() -> str:
    """返回当天 00:00:00 格式的起始时间"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d 00:00:00")


def _elevator_query_device(key: str, query_params: dict = None) -> dict:
    """
    发起电梯设备查询请求

    POST /api/device/query-exec?id=tw_lifter_0616

    Body 格式:
      { "key": "tw_xxx", "params": { ... } }
    """
    url = ELEVATOR_QUERY_URL
    query_string = {"id": ELEVATOR_DEVICE_ID}
    if query_params is None:
        query_params = {}
    body = {"key": key, "params": query_params}

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, params=query_string, json=body, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        print(f"  [电梯API] POST 失败: {resp.status_code}")
        return None
    except requests.RequestException as e:
        print(f"  [电梯API] 请求异常: {e}")
        return None


# ==================== 电梯查询 1: 在线状态 ====================
def query_elevator_online_status() -> dict:
    """
    查询电梯在线状态 (tw_online)

    Body: {"key": "tw_online", "params": {}}
    """
    start_time = time.time()
    try:
        data = _elevator_query_device("tw_online", {})
        if data is None:
            return {
                "success": False,
                "error": "电梯在线状态查询失败",
                "elapsed_seconds": round(time.time() - start_time, 2),
            }
        return {
            "success": True,
            "query_type": "电梯在线状态",
            "device_id": ELEVATOR_DEVICE_ID,
            "raw_data": data,
            "elapsed_seconds": round(time.time() - start_time, 2),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"查询电梯在线状态异常: {str(e)}",
            "elapsed_seconds": round(time.time() - start_time, 2),
        }


# ==================== 电梯查询 2: 运行数据 ====================
def query_elevator_runtime() -> dict:
    """
    查询电梯运行数据 (tw_runtime)

    Body: {"key": "tw_runtime", "params": {}}
    """
    start_time = time.time()
    try:
        data = _elevator_query_device("tw_runtime", {})
        if data is None:
            return {
                "success": False,
                "error": "电梯运行数据查询失败",
                "elapsed_seconds": round(time.time() - start_time, 2),
            }
        return {
            "success": True,
            "query_type": "电梯运行数据",
            "device_id": ELEVATOR_DEVICE_ID,
            "raw_data": data,
            "elapsed_seconds": round(time.time() - start_time, 2),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"查询电梯运行数据异常: {str(e)}",
            "elapsed_seconds": round(time.time() - start_time, 2),
        }


# ==================== 电梯查询 3: 运行数据（按小时） ====================
def query_elevator_hourly_stats(
    device_number: str = ELEVATOR_DEVICE_NUMBER,
    start_time_str: str = None,
    end_time_str: str = "",
    limit: int = 0,
    offset: int = 0,
) -> dict:
    """
    查询电梯运行数据-按小时 (tw_hourly_stats)

    Body: {"key": "tw_hourly_stats", "params": { device_number, start_time, end_time, limit, offset }}
    """
    start_time_ts = time.time()
    if start_time_str is None:
        start_time_str = _elevator_default_start_time()
    params = {
        "device_number": device_number,
        "start_time": start_time_str,
        "end_time": end_time_str,
        "limit": limit,
        "offset": offset,
    }
    try:
        data = _elevator_query_device("tw_hourly_stats", params)
        if data is None:
            return {
                "success": False,
                "error": "电梯运行数据(按小时)查询失败",
                "elapsed_seconds": round(time.time() - start_time_ts, 2),
            }
        return {
            "success": True,
            "query_type": "电梯运行数据(按小时)",
            "device_id": ELEVATOR_DEVICE_ID,
            "device_number": device_number,
            "start_time": start_time_str,
            "raw_data": data,
            "elapsed_seconds": round(time.time() - start_time_ts, 2),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"查询电梯运行数据(按小时)异常: {str(e)}",
            "elapsed_seconds": round(time.time() - start_time_ts, 2),
        }


# ==================== 电梯查询 4: 笼内人流量（按分钟） ====================
def query_elevator_minute_traffic(
    device_number: str = ELEVATOR_DEVICE_NUMBER,
    start_time_str: str = None,
    end_time_str: str = "",
    limit: int = 0,
    offset: int = 0,
) -> dict:
    """
    查询笼内人流量-按分钟 (tw_minute_traffic)

    Body: {"key": "tw_minute_traffic", "params": { device_number, start_time, end_time, limit, offset }}
    """
    start_time_ts = time.time()
    if start_time_str is None:
        start_time_str = _elevator_default_start_time()
    params = {
        "device_number": device_number,
        "start_time": start_time_str,
        "end_time": end_time_str,
        "limit": limit,
        "offset": offset,
    }
    try:
        data = _elevator_query_device("tw_minute_traffic", params)
        if data is None:
            return {
                "success": False,
                "error": "笼内人流量(按分钟)查询失败",
                "elapsed_seconds": round(time.time() - start_time_ts, 2),
            }
        return {
            "success": True,
            "query_type": "笼内人流量(按分钟)",
            "device_id": ELEVATOR_DEVICE_ID,
            "device_number": device_number,
            "start_time": start_time_str,
            "raw_data": data,
            "elapsed_seconds": round(time.time() - start_time_ts, 2),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"查询笼内人流量(按分钟)异常: {str(e)}",
            "elapsed_seconds": round(time.time() - start_time_ts, 2),
        }


# ==================== 电梯多设备批量查询 ====================

def query_elevator_raw(query_type: str) -> dict:
    """
    查询电梯设备的原始数据

    一次 API 调用查询所有电梯设备, 结果字段 result 为设备编号到状态的映射。

    如 tw_online 返回:
      {"code": 0, "result": {"0114004612251229001": "online", ...}}

    Args:
        query_type: "elevator_online" | "elevator_runtime" | "elevator_hourly" | "elevator_traffic"

    Returns:
        {"success": True, "data": <API 返回的完整 JSON>} 或 {"success": False, "error": "..."}
    """
    start_time = time.time()

    # 根据查询类型确定 key
    key_map = {
        "elevator_online": "tw_online",
        "elevator_runtime": "tw_runtime",
        "elevator_hourly": "tw_hourly_stats",
        "elevator_traffic": "tw_minute_traffic",
    }
    key = key_map.get(query_type, "tw_online")

    # 一次 API 调用即可获取所有设备数据
    data = _elevator_query_device(key, {})
    if data is None:
        return {
            "success": False,
            "error": "电梯设备数据查询失败",
            "elapsed_seconds": round(time.time() - start_time, 2),
        }

    return {
        "success": True,
        "query_type": query_type,
        "data": data,
        "elapsed_seconds": round(time.time() - start_time, 2),
    }


# ==================== 电梯查询 5: 当前时刻笼内人数 ====================
def query_elevator_current_people_count() -> dict:
    """
    查询当前时刻 4 个电梯笼内各有多少人

    流程:
      1. 对每个设备调用 tw_minute_traffic, 查询最近 10 分钟数据
      2. 从 data.std.records 中取最新一条记录
      3. 用 AvgPersonNum 作为当前笼内平均人数
      4. 汇总生成口语化总结

    数据格式参考:
      {
        "code": 200,
        "data": {
          "std": {
            "total": 531,
            "records": [
              {"AvgPersonNum": "0.0", "DeviceNumber": "...", "MaxPersonNum": 0,
               "MinPersonNum": 0, "Minute": "2026-06-16 18:51", "SampleCount": 1},
              ...
            ]
          }
        }
      }

    Returns:
        {"success": True, "devices": [...], "data_summary": "...", ...} 或 {"success": False, "error": "..."}
    """
    from datetime import datetime, timedelta
    from datetime import datetime, timedelta

    start_time = time.time()
    now = datetime.now()

    # 一次无参 API 调用获取所有设备的全量数据（传 device_number 会导致 records 为 null）
    raw_result = query_elevator_raw("elevator_traffic")
    if not raw_result.get("success"):
        return {"success": False, "error": raw_result.get("error", "电梯当前笼内人数查询失败"), "elapsed_seconds": round(time.time() - start_time, 2)}

    api_data = raw_result.get("data", {})
    all_records = None
    if isinstance(api_data, dict):
        inner = api_data.get("data")
        if isinstance(inner, dict):
            std = inner.get("std")
            if isinstance(std, dict):
                all_records = std.get("records")
            if all_records is None:
                all_records = inner.get("records")
        elif isinstance(inner, list):
            all_records = inner
        if all_records is None:
            all_records = api_data.get("records")

    if not isinstance(all_records, list) or len(all_records) == 0:
        return {"success": False, "error": "未获取到电梯 records 数据", "elapsed_seconds": round(time.time() - start_time, 2)}

    def _safe_get(d, *keys):
        for k in keys:
            v = d.get(k)
            if v is not None:
                return v
        return None

    # 按 DeviceNumber 分组，每组取最新一条
    device_groups = {}
    for r in all_records:
        if not isinstance(r, dict):
            continue
        dn = r.get("DeviceNumber", "")
        if not dn:
            continue
        minute = r.get("Minute", "")
        if dn not in device_groups or minute > device_groups[dn].get("Minute", ""):
            device_groups[dn] = r

    device_results = []
    total_people = 0.0

    for dev in ELEVATOR_DEVICES:
        dn = dev["device_number"]
        building = dev["building"]
        cage = dev["cage"]
        label = f"{building}{cage}"

        latest = device_groups.get(dn)

        if latest is not None:
            avg_person_num = _safe_get(latest, "AvgPersonNum", "avgPersonNum", "avg_person_num")
            record_minute = _safe_get(latest, "Minute", "minute")
            max_person_num = _safe_get(latest, "MaxPersonNum", "maxPersonNum", "max_person_num")
            min_person_num = _safe_get(latest, "MinPersonNum", "minPersonNum", "min_person_num")
            sample_count = _safe_get(latest, "SampleCount", "sampleCount", "sample_count")

            if avg_person_num is not None:
                try:
                    avg_person_num = float(avg_person_num)
                except (ValueError, TypeError):
                    avg_person_num = None
            if max_person_num is not None and not isinstance(max_person_num, (int, float)):
                try:
                    max_person_num = int(max_person_num)
                except (ValueError, TypeError):
                    pass
            if min_person_num is not None and not isinstance(min_person_num, (int, float)):
                try:
                    min_person_num = int(min_person_num)
                except (ValueError, TypeError):
                    pass
            if sample_count is not None and not isinstance(sample_count, (int, float)):
                try:
                    sample_count = int(sample_count)
                except (ValueError, TypeError):
                    pass

            if avg_person_num is not None:
                total_people += avg_person_num
                device_results.append({
                    "building": building,
                    "cage": cage,
                    "label": label,
                    "DeviceNumber": dn,
                    "AvgPersonNum": avg_person_num,
                    "MaxPersonNum": max_person_num,
                    "MinPersonNum": min_person_num,
                    "SampleCount": sample_count,
                    "Minute": record_minute,
                    "status": "ok",
                })
            else:
                device_results.append({
                    "building": building, "cage": cage, "label": label,
                    "DeviceNumber": dn,
                    "AvgPersonNum": None, "MaxPersonNum": None, "MinPersonNum": None,
                    "SampleCount": None, "Minute": None,
                    "status": "no_data",
                })
        else:
            device_results.append({
                "building": building, "cage": cage, "label": label,
                "DeviceNumber": dn,
                "AvgPersonNum": None, "MaxPersonNum": None, "MinPersonNum": None,
                "SampleCount": None, "Minute": None,
                "status": "no_data",
            })

    # 生成口语化摘要    # 生成口语化摘要    # 生成口语化摘要    # 生成口语化摘要    # 生成口语化摘要    # 生成口语化摘要    # 生成口语化摘要
    query_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    ok_devices = [d for d in device_results if d["status"] == "ok"]
    no_data_devices = [d for d in device_results if d["status"] == "no_data"]

    parts = [f"当前时间 {query_time_str}，"]
    if ok_devices:
        detail_parts = []
        for d in ok_devices:
            avg_val = d["AvgPersonNum"]
            if avg_val == int(avg_val):
                avg_str = str(int(avg_val))
            else:
                avg_str = f"{avg_val:.1f}"

            # 构建 max/min 信息
            max_val = d.get("MaxPersonNum")
            min_val = d.get("MinPersonNum")
            stat_info = ""
            if max_val is not None and min_val is not None:
                try:
                    max_v = int(max_val)
                    min_v = int(min_val)
                    if max_v == min_v:
                        stat_info = f"，最大/最小均为{max_v}人"
                    else:
                        stat_info = f"，最大{max_v}人，最小{min_v}人"
                except (ValueError, TypeError):
                    pass

            data_time = d.get("Minute", "")
            detail_parts.append(f"{d['label']}平均{avg_str}人{stat_info}（{data_time}）")
        parts.append("；".join(detail_parts))
        if len(ok_devices) == 4:
            total_val = total_people
            if total_val == int(total_val):
                total_str = str(int(total_val))
            else:
                total_str = f"{total_val:.1f}"
            parts.append(f"。合计 {total_str} 人。")
        else:
            parts.append("。")
    if no_data_devices:
        n_labels = [d["label"] for d in no_data_devices]
        parts.append(f" {'、'.join(n_labels)}暂无数据。")

    summary_text = "".join(parts)
    elapsed = round(time.time() - start_time, 2)

    return {
        "success": True,
        "query_type": "电梯当前笼内人数",
        "query_time": query_time_str,
        "total_devices": len(ELEVATOR_DEVICES),
        "devices_with_data": len(ok_devices),
        "total_avg_people": round(total_people, 1),
        "devices": device_results,
        "data_summary": summary_text,
        "返回数据总结": summary_text,
        "elapsed_seconds": elapsed,
    }


# ==================== 智能查询解析 ====================
def _parse_query_text(query_text: str) -> dict:
    """
    解析查询文本, 判断属于哪种查询类型并提取参数

    Returns:
        {"type": "building_progress"|"crane_height"|"device_status"|"personnel_names"|"personnel_locations"|None, "param": ...}
    """
    text = query_text.strip()

    # ---- 模式1: 楼栋施工进度 ----
    # 先匹配"全部/所有楼栋"模式
    if re.search(r'(?:全部|所有)楼栋.*施工进度|楼栋施工进度.*(?:全部|所有|总览)', text):
        return {"type": "building_progress", "param": None}
    # 匹配有具体编号的
    building_specific = [
        r'查询\s*(\S+号楼?).*施工进度',
        r'(\S+号楼?).*施工进度',
        r'查询\s*(\S+号楼?).*施工.*(?:楼层|进度)',
        r'(\S+号楼?).*当前.*(?:施工|楼层)',
        r'(\S+号楼?).*(?:建到|盖到).*层',
        r'查询\s*(\S*?\d+\S*?(?:楼|栋|#)).*施工',
        r'(\S*?\d+\S*?(?:楼|栋|#)).*施工.*进度',
    ]
    for pattern in building_specific:
        m = re.search(pattern, text)
        if m:
            return {"type": "building_progress", "param": m.group(1)}
    # 匹配通用"楼栋施工进度" (无具体编号)
    if re.search(r'楼栋施工进度|查询.*施工进度|施工进度查询', text) and not re.search(r'(?:塔吊|塔机|设备)', text):
        return {"type": "building_progress", "param": None}

    # ---- 模式2: 塔吊/塔机安装高度 ----
    # 匹配"全部/所有塔吊/塔机"模式
    if re.search(r'(?:全部|所有)(?:塔吊|塔机).*(?:安装)?高度|(?:塔吊|塔机).*安装高度.*(?:全部|所有|总览)', text):
        return {"type": "crane_height", "param": None}
    # 匹配有具体编号的塔机/塔吊（如「塔机1」「塔吊8」）
    crane_specific = [
        r'(?:塔吊|塔机)\s*(\d+).*(?:安装)?高度',
        r'查询\s*(?:塔吊|塔机)\s*(\d+).*(?:安装)?高度',
        r'(?:塔吊|塔机)\s*(\d+).*高度',
        r'查询\s*(?:塔吊|塔机)\s*(\d+).*高度',
    ]
    for pattern in crane_specific:
        m = re.search(pattern, text)
        if m:
            # 只捕获数字，重建为完整设备名（如「塔机1」）
            num = m.group(1)
            # 判断是塔机还是塔吊
            prefix = "塔机" if "塔机" in text else "塔吊"
            return {"type": "crane_height", "param": f"{prefix}{num}"}
    # 匹配通用「塔吊/塔机安装高度」/「查询塔机高度」等无具体编号的查询
    if re.search(r'(?:塔吊|塔机).*(?:安装)?高度|(?:安装)?高度.*(?:塔吊|塔机)', text):
        return {"type": "crane_height", "param": None}

    # ---- 模式3: 电梯数据查询 (必须在设备运行状态之前, 避免被在线状态等关键词语拦截) ----
    # 电梯在线状态
    if re.search(r'电梯.*(?:在线|运行状态|状态)|(?:在线|运行)状态.*电梯', text):
        return {"type": "elevator_online", "param": None}
    # 电梯运行数据按小时
    if re.search(r'电梯.*(?:运行数据|小时|时序|按小时)|(?:按小时|小时).*电梯', text):
        return {"type": "elevator_hourly", "param": None}
    # 电梯当前时刻笼内人数 (查询当前有多少人) — 必须放在 elevator_traffic 之前, 避免"人数"被误匹配
    if re.search(r'(?:查询|当前|现在).*(?:电梯|笼内).*(?:有多少人|几人|人数)|(?:电梯).*(?:当前|现在).*(?:笼内|人数|几人)|(?:笼内).*(?:当前|现在).*(?:有多少人|人数)', text):
        return {"type": "elevator_current_people", "param": None}
    # 电梯笼内人流量/电梯人流量/笼内人流量
    if re.search(r'(?:电梯|笼内).*(?:人流量|人流)|(?:人流量|人流).*(?:电梯|笼内)', text):
        return {"type": "elevator_traffic", "param": None}
    # 通用电梯运行数据
    if re.search(r'电梯.*(?:运行|数据|统计)|(?:查询|获取).*电梯', text):
        return {"type": "elevator_runtime", "param": None}

    # ---- 模式4: 设备运行状态 (塔机/塔吊设备) ----
    # 匹配"全部/所有设备"模式
    if re.search(r'(?:全部|所有)设备.*运行状态|设备.*运行状态.*(?:全部|所有|总览)', text):
        return {"type": "device_status", "param": None}
    # 匹配有具体编号的
    status_specific = [
        r'查询\s*(\S*(?:塔吊|塔机|设备)\S*).*运行状态',
        r'查询\s*(\S*(?:塔吊|塔机|设备)\S*).*(?:今天|当前)',
        r'(\S*(?:塔吊|塔机|设备)\S*).*运行状态',
        r'(\S*(?:塔吊|塔机|设备)\S*).*(?:是否|在).*运行',
        r'(\S*(?:塔吊|塔机|设备)\S*).*在线状态',
    ]
    for pattern in status_specific:
        m = re.search(pattern, text)
        if m:
            return {"type": "device_status", "param": m.group(1)}
    # 匹配通用"设备运行状态" (无具体编号, 但不包含电梯关键词)
    if re.search(r'设备运行状态|运行状态.*(?:查询|显示)|在线状态.*(?:查询|显示)', text) and "电梯" not in text:
        return {"type": "device_status", "param": None}

    # ---- 模式5: 人员定位统计查询 (需要在本地获取原始数据, LLM 总结走后端) ----
    if re.search(r'(?:全部|所有)?人员.*(?:位置|定位|在哪|信息)|人员.*(?:位置|定位).*(?:查询|列表|统计|走势|总览)', text):
        return {"type": "personnel_position", "param": None}

    return {"type": None, "param": None}


# ==================== 查询 4: 人员定位数据获取 ====================
def query_personnel_position_raw() -> dict:
    """
    查询人员定位原始数据

    后端 LLM 意图分析会将"人员定位24小时走势"匹配到:
      - snapshootProjectPersonCountV3 (24H每分钟人数趋势)
      - personCurLocationV2 (当前人员列表 + 区域位置)

    本地需要同时获取两个接口的原始数据, 确保 raw_data 与 LLM 总结来源一致。

    Returns:
        {"success": True, "data": {...}, "original_data": {...}} 或 {"success": False, "error": "..."}
    """
    start_time = time.time()
    try:
        # 接口1: 24H走势数据 (后端 LLM 分析的主接口, 需要 startDate/endDate)
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")
        snapshoot_data = _data_api_post(
            "location/snapshootProjectPersonCountV3",
            {"projectKey": DATA_API_PROJECT_KEY, "startDate": f"{today} 00:00:00", "endDate": f"{today} 23:59:59"}
        )

        # 接口2: 当前人员列表 (补充人员位置信息)
        person_data = _data_api_post(
            "location/personCurLocation/v2",
            {"projectKey": DATA_API_PROJECT_KEY}
        )

        if not snapshoot_data and not person_data:
            return {"success": False, "error": "调用人员定位API失败", "elapsed_seconds": round(time.time() - start_time, 2)}

        # ---- 处理 personCurLocationV2 数据 ----
        processed_person_data = None
        if person_data:
            if isinstance(person_data, dict):
                result = person_data.get("data") or person_data
            elif isinstance(person_data, list):
                result = person_data
            else:
                result = {}

            # 确保 result 是 dict，防止 API 直接返回 list 导致 .get() 失败
            if isinstance(result, list):
                result = {"stayPersonPageVos": result, "stayPersonCountVos": []}
            elif not isinstance(result, dict):
                result = {"stayPersonPageVos": [], "stayPersonCountVos": []}

            # stayPersonCountVos: 按 areaName 合并求和
            count_vos = result.get("stayPersonCountVos") or []
            area_merged = {}
            for vo in count_vos:
                if isinstance(vo, dict):
                    area = vo.get("areaName", "未知区域")
                    online = int(vo.get("onlinePersonNum", 0))
                    offline = int(vo.get("offlinePersonNum", 0))
                    total = int(vo.get("totalPersonNum", 0))
                    if area not in area_merged:
                        area_merged[area] = {"areaName": area, "onlinePersonNum": 0, "offlinePersonNum": 0, "totalPersonNum": 0}
                    area_merged[area]["onlinePersonNum"] += online
                    area_merged[area]["offlinePersonNum"] += offline
                    area_merged[area]["totalPersonNum"] += total
            merged_count_vos = list(area_merged.values())

            # stayPersonPageVos: 只保留 personName, areaName, gatewayPositionName
            # 如果 gatewayPositionName 为空则不展示该字段
            page_vos = result.get("stayPersonPageVos") or []
            simplified_page_vos = []
            gateway_stats = {}  # 按 gatewayPositionName 统计人数
            for vo in page_vos:
                if isinstance(vo, dict):
                    name = vo.get("personName", "")
                    if not name:
                        continue
                    gateway = vo.get("gatewayPositionName", "")
                    if not gateway:
                        continue
                    person_entry = {"personName": name}
                    if vo.get("areaName"):
                        person_entry["areaName"] = vo.get("areaName")
                    person_entry["gatewayPositionName"] = gateway
                    gateway_stats[gateway] = gateway_stats.get(gateway, 0) + 1
                    simplified_page_vos.append(person_entry)

            processed_person_data = {
                "stayPersonCountVos": merged_count_vos,
                "stayPersonPageVos": simplified_page_vos,
                "gatewayPositionDistribution": gateway_stats,
            }

        # 构建 raw_data (包含两个接口的数据)
        raw_data = {}
        if snapshoot_data:
            # 提取 data 数组中的 onlineCount, 做趋势摘要
            # 适配多种响应格式: {data: {data: [...]}} 或 {data: [...]} 或直接 [...]
            if isinstance(snapshoot_data, dict):
                snapshoot_result = snapshoot_data.get("data") or snapshoot_data
                if isinstance(snapshoot_result, dict):
                    data_list = snapshoot_result.get("data") or []
                elif isinstance(snapshoot_result, list):
                    data_list = snapshoot_result
                else:
                    data_list = []
            elif isinstance(snapshoot_data, list):
                data_list = snapshoot_data
            else:
                data_list = []
            trend_summary = {}
            if isinstance(data_list, list) and len(data_list) > 0:
                online_counts = []
                for item in data_list:
                    if isinstance(item, dict):
                        oc = item.get("onlineCount")
                        if oc is not None:
                            online_counts.append(int(oc))
                if online_counts:
                    trend_summary = {
                        "total_data_points": len(online_counts),
                        "max_online": max(online_counts),
                        "min_online": min(online_counts),
                        "avg_online": round(sum(online_counts) / len(online_counts), 1),
                        "latest_online": online_counts[-1],
                        "trend": "上升" if len(online_counts) >= 2 and online_counts[-1] > online_counts[0] else ("下降" if len(online_counts) >= 2 and online_counts[-1] < online_counts[0] else "平稳"),
                    }
            raw_data["snapshootProjectPersonCountV3"] = {
                "trend_summary": trend_summary,
                "data_point_count": len(data_list),
            }
        if processed_person_data:
            raw_data["personCurLocationV2"] = processed_person_data

        return {
            "success": True,
            "data": raw_data,
            "original_data": {"snapshoot": snapshoot_data, "personCur": person_data},
            "elapsed_seconds": round(time.time() - start_time, 2),
        }
    except Exception as e:
        return {"success": False, "error": f"查询人员定位异常: {str(e)}", "elapsed_seconds": round(time.time() - start_time, 2)}


# ==================== 原有核心函数 ====================

def test_status():
    """检查 /staff-safe/status 状态"""
    try:
        resp = requests.get(f"{BASE_URL}/staff-safe/status", timeout=10)
        return resp.json()
    except requests.RequestException as e:
        return {"success": False, "message": f"请求失败: {e}"}


def _summarize_local_result(query_type: str, result: dict) -> str:
    """从本地查询的结构化结果生成口语化文本总结"""
    if not result.get("success"):
        return result.get("error", "查询失败")

    if query_type == "building_progress":
        if result.get("all_buildings"):
            buildings = result.get("buildings", [])
            if not buildings:
                return "当前项目暂无楼栋施工数据。"
            total = len(buildings)
            parts = [f"当前项目共 {total} 栋楼，"]
            in_progress = [b for b in buildings if b.get("current_construction_floor", 0) > 0]
            not_started = [b for b in buildings if b.get("current_construction_floor", 0) == 0]
            if in_progress:
                parts.append(f"其中 {len(in_progress)} 栋已开始施工")
                detail_parts = []
                for b in in_progress:
                    name = b.get("building_name", "未知")
                    current = b.get("current_construction_floor", 0)
                    total_floor = b.get("total_floor", 0)
                    if total_floor:
                        detail_parts.append(f"{name}施工至第{current}层（共{total_floor}层）")
                    else:
                        detail_parts.append(f"{name}施工至第{current}层")
                parts.append("：" + "，".join(detail_parts))
                if not_started:
                    n_names = [b.get("building_name", "未知") for b in not_started]
                    parts.append(f"；另外 {'、'.join(n_names)} 尚未开始施工")
                parts.append("。")
            else:
                parts.append("均未开始施工。")
            return "".join(parts)
        else:
            name = result.get("building_name", "未知楼栋")
            current = result.get("current_construction_floor", 0)
            total_floor = result.get("total_floor", 0)
            if total_floor:
                return f"{name}当前施工至第{current}层，共{total_floor}层。"
            else:
                return f"{name}当前施工至第{current}层。"

    elif query_type == "crane_height":
        if result.get("all_devices"):
            devices = result.get("devices", [])
            if not devices:
                return "当前项目暂无塔机/塔吊设备数据。"
            valid = [d for d in devices if d.get("crane_height") and d["crane_height"] != "无数据"]
            no_data = [d for d in devices if not d.get("crane_height") or d["crane_height"] == "无数据"]
            parts = []
            if valid:
                valid.sort(key=lambda x: float(x["crane_height"].replace("m", "").strip() or 0), reverse=True)
                total = len(valid)
                parts.append(f"当前项目共 {total} 台塔机/塔吊有高度数据")
                detail_parts = []
                for d in valid:
                    detail_parts.append(f"{d['device_name']}{d['crane_height']}")
                parts.append("：" + "，".join(detail_parts) + "。")
            else:
                parts.append("当前项目暂无塔机/塔吊的安装高度数据。")
            if no_data:
                n_names = [d.get("device_name", "未知") for d in no_data]
                parts.append(f" 其中 {'、'.join(n_names)} 暂无高度数据。")
            return "".join(parts)
        else:
            name = result.get("device_name", "未知设备")
            height = result.get("crane_height", "")
            if height:
                return f"{name}的塔机安装高度为{height}。"
            else:
                return f"{name}暂无安装高度数据。"

    elif query_type == "device_status":
        if result.get("all_devices"):
            devices = result.get("devices", [])
            if not devices:
                return "当前项目暂无设备状态数据。"
            total = len(devices)
            running = [d for d in devices if d.get("status_text") == "运行中"]
            offline = [d for d in devices if d.get("status_text") != "运行中"]
            parts = [f"当前项目共 {total} 台设备"]
            if running:
                r_names = [d.get("device_name", "未知") for d in running]
                parts.append(f"，其中 {len(running)} 台运行中：{'、'.join(r_names)}")
            if offline:
                o_parts = []
                for d in offline:
                    o_parts.append(f"{d.get('device_name', '未知')}（{d.get('status_text', '未知')}）")
                parts.append(f"，{len(offline)} 台离线/停止：{'、'.join(o_parts)}")
            parts.append("。")
            return "".join(parts)
        else:
            name = result.get("device_name", "未知设备")
            status = result.get("status_display", "")
            if status:
                return status
            return f"{name}当前状态：{result.get('status_text', '未知')}。"

    return "查询完成。"


def test_query(query_text: str, description: str) -> dict:
    """运行单个查询测试，返回结构化结果"""
    start_time = time.time()

    # 先尝试本地解析, 如果是塔机静态数据查询则先获取数据，再走 LLM 总结
    parsed = _parse_query_text(query_text)
    local_result = None

    if parsed["type"] in ("building_progress", "crane_height", "device_status"):
        if parsed["type"] == "building_progress":
            local_result = query_building_construction_progress(parsed["param"])
        elif parsed["type"] == "crane_height":
            local_result = query_crane_installation_height(parsed["param"])
        elif parsed["type"] == "device_status":
            local_result = query_device_online_status(parsed["param"])

        if local_result is not None:
            local_result["description"] = description
            local_result["query"] = query_text
            local_result["data_summary"] = _summarize_local_result(parsed["type"], local_result)
            local_result["返回数据总结"] = local_result["data_summary"]
            return local_result

    # 电梯当前时刻笼内人数查询
    if parsed["type"] == "elevator_current_people":
        result = query_elevator_current_people_count()
        result["description"] = description
        result["query"] = query_text
        return result

    # 电梯数据查询: 本地获取数据并直接生成总结, 不调用后端 LLM
    if parsed["type"] in ("elevator_online", "elevator_runtime", "elevator_hourly", "elevator_traffic"):
        raw_result = query_elevator_raw(parsed["type"])
        if not raw_result["success"]:
            return {
                "success": False,
                "description": description,
                "query": query_text,
                "status_code": 0,
                "elapsed_seconds": round(time.time() - start_time, 2),
                "error": raw_result.get("error", "电梯数据获取失败"),
            }

        # 递归查找 result 字段 (适配任意嵌套层级)
        def _find_result(obj, depth=0):
            if depth > 6 or not isinstance(obj, dict):
                return {}
            if "result" in obj and isinstance(obj["result"], dict):
                return obj["result"]
            for val in obj.values():
                if isinstance(val, dict):
                    found = _find_result(val, depth + 1)
                    if found:
                        return found
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            found = _find_result(item, depth + 1)
                            if found:
                                return found
            return {}

        api_data = raw_result.get("data", {})
        result_map = _find_result(api_data) if isinstance(api_data, dict) else {}
        # 额外打印调试信息
        if not result_map:
            print(f"  [电梯] 未找到 result 字段, api_data 结构: {json.dumps(api_data, ensure_ascii=False)[:300]}")

        # 构建设备编号到楼栋/笼位的映射
        dn_to_info = {d["device_number"]: f"{d['building']}{d['cage']}" for d in ELEVATOR_DEVICES}

        online_list = []
        offline_list = []
        for dn, status in result_map.items():
            info = dn_to_info.get(dn, dn)
            if status in ("online", "1", 1):
                online_list.append(f"{info}")
            else:
                offline_list.append(f"{info}({status})")

        # 生成本地总结文本
        elapsed = raw_result.get("elapsed_seconds", 0)
        total = len(result_map)
        if total == 0:
            summary_text = f"电梯设备数据查询为空（耗时 {elapsed:.2f} 秒）。"
        else:
            parts = [f"共 {total} 个电梯设备，"]
            if online_list:
                parts.append(f"在线 {len(online_list)} 个：{'、'.join(online_list)}")
            if offline_list:
                parts.append(f"，离线/异常 {len(offline_list)} 个：{'、'.join(offline_list)}")
            parts.append(f"（耗时 {elapsed:.2f} 秒）。")
            summary_text = "".join(parts)

        return {
            "success": True,
            "description": description,
            "query": query_text,
            "status_code": 200,
            "elapsed_seconds": round(time.time() - start_time, 2),
            "data_summary": summary_text,
            "返回数据总结": summary_text,
            "raw_data": raw_result.get("data"),
        }

    elif parsed["type"] == "personnel_position":
        # 本地获取原始数据 + 后端 LLM 总结
        raw_result = query_personnel_position_raw()
        if not raw_result["success"]:
            return {
                "success": False,
                "description": description,
                "query": query_text,
                "status_code": 0,
                "elapsed_seconds": round(time.time() - start_time, 2),
                "error": raw_result.get("error", "人员定位数据获取失败"),
            }

        # 提取 gatewayPositionDistribution 信息
        gateway_dist = {}
        if raw_result.get("data", {}).get("personCurLocationV2", {}).get("gatewayPositionDistribution"):
            gateway_dist = raw_result["data"]["personCurLocationV2"]["gatewayPositionDistribution"]

        # 将 gateway 分布信息注入查询文本, 由后端 LLM 统一总结
        enhanced_query = query_text
        if gateway_dist:
            dist_parts = ["人员基站位置分布:"]
            for loc, count in sorted(gateway_dist.items(), key=lambda x: -x[1]):
                dist_parts.append(f"{loc} {count}人")
            enhanced_query = f"{query_text}（人员基站位置分布：{'，'.join(dist_parts[1:])}）"

        llm_result = None
        llm_elapsed = 0
        try:
            resp = requests.post(
                f"{BASE_URL}/staff-safe/query",
                json={"query": enhanced_query},
                timeout=120,
            )
            if resp.status_code == 200:
                llm_result = resp.json()
                llm_elapsed = round(time.time() - start_time, 2)
        except Exception:
            pass

        summary_text = llm_result.get("返回数据总结", "") if llm_result else ""

        # 后端 LLM 只总结它自己调用的 API 返回数据（24H走势），
        # 不会把查询文本里注入的 gatewayPositionDistribution 纳入总结。
        # 需要本地生成基站分布摘要，追加到 data_summary 中。
        if gateway_dist:
            dist_parts = []
            for loc, count in sorted(gateway_dist.items(), key=lambda x: -x[1]):
                dist_parts.append(f"{loc} {count}人")
            gateway_summary = f"\n\n【人员基站位置分布】{'，'.join(dist_parts)}。"
            summary_text = summary_text + gateway_summary

        return {
            "success": True,
            "description": description,
            "query": query_text,
            "status_code": 200 if llm_result else 0,
            "elapsed_seconds": round(time.time() - start_time, 2),
            "request_time": llm_result.get("请求时间", "") if llm_result else "",
            "data_summary": summary_text,
            "返回数据总结": summary_text,
            "involved_data": llm_result.get("涉及数据", {}) if llm_result else {},
            "raw_data": raw_result.get("data"),
            "llm_elapsed_seconds": llm_elapsed,
        }
    # 否则走原有的后端查询
    try:
        resp = requests.post(
            f"{BASE_URL}/staff-safe/query",
            json={"query": query_text},
            timeout=120,
        )
        elapsed = round(time.time() - start_time, 2)

        if resp.status_code == 200:
            data = resp.json()
            return {
                "success": True,
                "description": description,
                "query": query_text,
                "status_code": resp.status_code,
                "elapsed_seconds": elapsed,
                "request_time": data.get("请求时间", ""),
                "data_summary": data.get("返回数据总结", ""),
                "involved_data": data.get("涉及数据", {}),
                "raw_response": data,
            }
        else:
            error_data = resp.json() if resp.text else {}
            return {
                "success": False,
                "description": description,
                "query": query_text,
                "status_code": resp.status_code,
                "elapsed_seconds": elapsed,
                "error": error_data.get("message", resp.text[:300]),
            }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "description": description,
            "query": query_text,
            "status_code": 0,
            "elapsed_seconds": time.time() - start_time,
            "error": "请求超时（120秒）",
        }
    except requests.RequestException as e:
        return {
            "success": False,
            "description": description,
            "query": query_text,
            "status_code": 0,
            "elapsed_seconds": time.time() - start_time,
            "error": f"请求失败: {str(e)}",
        }


def run_all_tests() -> dict:
    """运行所有预设查询"""
    results = []
    passed = 0
    failed = 0
    start_time = time.time()

    for test in TEST_QUERIES:
        result = test_query(test["query"], test["description"])
        results.append(result)
        if result["success"]:
            passed += 1
        else:
            failed += 1

    return {
        "total": len(TEST_QUERIES),
        "passed": passed,
        "failed": failed,
        "elapsed_seconds": round(time.time() - start_time, 2),
        "results": results,
    }


def get_api_catalog() -> list:
    """获取接口目录"""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "main/xiaozhi-server"))
    try:
        from plugins_func.functions.staff_safe_query import API_CATALOG

        categories = {}
        for api in API_CATALOG:
            cat = api["category"]
            if cat not in categories:
                categories[cat] = {}
            categories[cat].append({
                "api_id": api["api_id"],
                "method": api["method"],
                "description": api["description"],
                "keywords": api.get("keywords", []),
            })
        return [{"category": cat, "apis": apis} for cat, apis in categories.items()]
    except ImportError as e:
        return [{"error": f"无法导入 API_CATALOG: {e}"}]


# ==================== HTTP 请求处理器 ====================

class TestHandler(BaseHTTPRequestHandler):
    """测试服务 HTTP 请求处理器"""

    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[{time.strftime('%H:%M:%S')}] {args[0]}")

    def _send_json(self, data: dict, status: int = 200):
        """发送 JSON 响应"""
        response = json.dumps(data, ensure_ascii=False, indent=2)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(response.encode("utf-8"))

    def _send_html(self, html: str):
        """发送 HTML 响应"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _read_body(self) -> dict:
        """读取请求体 JSON"""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length)
        return json.loads(body)

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """处理 GET 请求"""
        path = urlparse(self.path).path

        if path == "/" or path == "/test":
            self._send_html(HTML_PAGE)
        elif path == "/test/status":
            result = test_status()
            self._send_json(result)
        elif path == "/test/catalog":
            result = get_api_catalog()
            self._send_json({"success": True, "catalog": result})
        else:
            self._send_json({"error": "Not Found", "path": path}, 404)

    def do_POST(self):
        """处理 POST 请求"""
        path = urlparse(self.path).path

        if path == "/test/query":
            body = self._read_body()
            query_text = body.get("query", "").strip()
            description = body.get("description", query_text or "自定义查询")
            if not query_text:
                self._send_json({"success": False, "error": "缺少 query 参数"}, 400)
                return

            print(f"\n  执行查询: {description}")
            print(f"  查询内容: {query_text}")
            result = test_query(query_text, description)
            self._send_json(result)

        elif path == "/test/run-all":
            print(f"\n  运行全部 {len(TEST_QUERIES)} 个预设查询...")
            result = run_all_tests()
            summary = {k: v for k, v in result.items() if k != "results"}
            print(f"  完成: 通过 {summary['passed']}, 失败 {summary['failed']}")
            self._send_json(result)

        # ---- 新增: 楼栋施工进度查询 ----
        elif path == "/test/building-progress":
            body = self._read_body()
            building_name = body.get("building_name", "").strip()
            if not building_name:
                self._send_json({"success": False, "error": "缺少 building_name 参数"}, 400)
                return
            print(f"\n  查询楼栋施工进度: {building_name}")
            result = query_building_construction_progress(building_name)
            self._send_json(result)

        # ---- 新增: 塔吊安装高度查询 ----
        elif path == "/test/crane-height":
            body = self._read_body()
            device_name = body.get("device_name", "").strip()
            if not device_name:
                self._send_json({"success": False, "error": "缺少 device_name 参数"}, 400)
                return
            print(f"\n  查询塔吊安装高度: {device_name}")
            result = query_crane_installation_height(device_name)
            self._send_json(result)

        # ---- 新增: 设备运行状态查询 ----
        elif path == "/test/device-status":
            body = self._read_body()
            device_name = body.get("device_name", "").strip()
            if not device_name:
                self._send_json({"success": False, "error": "缺少 device_name 参数"}, 400)
                return
            print(f"\n  查询设备运行状态: {device_name}")
            result = query_device_online_status(device_name)
            self._send_json(result)

        # ---- 新增: 电梯在线状态查询 ----
        elif path == "/test/elevator-online":
            print(f"\n  查询电梯在线状态 (tw_lifter_0616)")
            result = query_elevator_online_status()
            self._send_json(result)

        # ---- 新增: 电梯运行数据查询 ----
        elif path == "/test/elevator-runtime":
            print(f"\n  查询电梯运行数据 (tw_lifter_0616)")
            result = query_elevator_runtime()
            self._send_json(result)

        # ---- 新增: 电梯运行数据(按小时)查询 ----
        elif path == "/test/elevator-hourly":
            body = self._read_body()
            device_number = body.get("device_number", ELEVATOR_DEVICE_NUMBER)
            start_time_str = body.get("start_time", "").strip() or None
            end_time_str = body.get("end_time", "")
            limit = body.get("limit", 0)
            offset = body.get("offset", 0)
            print(f"\n  查询电梯运行数据(按小时): device={device_number} start={start_time_str}")
            result = query_elevator_hourly_stats(device_number, start_time_str, end_time_str, limit, offset)
            self._send_json(result)

        # ---- 新增: 电梯笼内人流量(按分钟)查询 ----
        elif path == "/test/elevator-traffic":
            body = self._read_body()
            device_number = body.get("device_number", ELEVATOR_DEVICE_NUMBER)
            start_time_str = body.get("start_time", "").strip() or None
            end_time_str = body.get("end_time", "")
            limit = body.get("limit", 0)
            offset = body.get("offset", 0)
            print(f"\n  查询电梯笼内人流量(按分钟): device={device_number} start={start_time_str}")
            result = query_elevator_minute_traffic(device_number, start_time_str, end_time_str, limit, offset)
            self._send_json(result)

        # ---- 新增: 电梯当前时刻笼内人数 ----
        elif path == "/test/elevator-current-people":
            print(f"\n  查询电梯当前时刻笼内人数")
            result = query_elevator_current_people_count()
            self._send_json(result)

        else:
            self._send_json({"error": "Not Found", "path": path}, 404)


# ==================== HTML 测试页面 ====================

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>工地安全数据查询测试</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; color: #333; }
.container { max-width: 900px; margin: 0 auto; padding: 20px; }
h1 { text-align: center; margin: 20px 0; color: #1a73e8; }
h2 { font-size: 16px; margin-bottom: 12px; color: #555; }
.section-title { font-size: 14px; color: #888; margin: 16px 0 8px 0; padding-bottom: 4px; border-bottom: 1px solid #eee; }
.card { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.status-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
.badge-ok { background: #e6f7e6; color: #389e0d; }
.badge-error { background: #fff1f0; color: #cf1322; }
.btn { display: inline-block; padding: 8px 20px; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; margin-right: 8px; margin-bottom: 8px; }
.btn-primary { background: #1a73e8; color: #fff; }
.btn-primary:hover { background: #1557b0; }
.btn-success { background: #389e0d; color: #fff; }
.btn-success:hover { background: #2d7a0a; }
.btn-outline { background: #fff; color: #1a73e8; border: 1px solid #1a73e8; }
.btn-outline:hover { background: #e8f0fe; }
.btn-taji { background: #fa8c16; color: #fff; border: 1px solid #fa8c16; }
.btn-taji:hover { background: #e87a0d; }
.btn-taji-green { background: #13c2c2; color: #fff; border: 1px solid #13c2c2; }
.btn-taji-green:hover { background: #0ea5a5; }
input, textarea { width: 100%; padding: 10px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 14px; margin-bottom: 10px; }
textarea { resize: vertical; min-height: 60px; }
.input-group { display: flex; gap: 8px; align-items: flex-start; }
.input-group input { flex: 1; }
.input-group button { flex-shrink: 0; margin-top: 0; }
.result-box { background: #fafafa; border: 1px solid #e8e8e8; border-radius: 6px; padding: 12px; margin-top: 10px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; font-size: 13px; line-height: 1.6; }
.loading { display: inline-block; width: 14px; height: 14px; border: 2px solid #1a73e8; border-radius: 50%; border-top-color: transparent; animation: spin 0.8s linear infinite; margin-left: 8px; vertical-align: middle; }
@keyframes spin { to { transform: rotate(360deg); } }
.hidden { display: none; }
.passed { color: #389e0d; }
.failed { color: #cf1322; }
</style>
</head>
<body>
<div class="container">
    <h1>🏗️ 工地安全数据查询测试</h1>

    <!-- 状态卡片 -->
    <div class="card">
        <h2>📡 服务状态</h2>
        <div class="status-row">
            <button class="btn btn-primary" onclick="checkStatus()">检查状态</button>
            <span id="status-badge"></span>
            <span id="status-loading" class="loading hidden"></span>
        </div>
        <div id="status-result" class="result-box hidden"></div>
    </div>

    <!-- 自定义查询 -->
    <div class="card">
        <h2>🔍 自定义查询</h2>
        <textarea id="custom-query" placeholder="输入查询内容，如：查询今天人员总览">查询今天人员总览</textarea>
        <button class="btn btn-primary" onclick="submitQuery()">发起查询</button>
        <span id="query-loading" class="loading hidden"></span>
        <div id="query-result" class="result-box hidden"></div>
    </div>

    <!-- 预设查询 -->
    <div class="card">
        <h2>📋 预设查询</h2>
        <div class="section-title">--- 安全数据查询 ---</div>
        <div id="preset-buttons"></div>
        <div class="section-title">--- 塔机静态数据查询（新增）---</div>
        <div id="taji-preset-buttons"></div>
        <span id="preset-loading" class="loading hidden"></span>
        <div id="preset-result" class="result-box hidden"></div>
    </div>

    <!-- 塔机静态数据直接查询卡片 -->
    <div class="card">
        <h2>🏗️ 塔机静态数据查询（直接查询）</h2>

        <div class="section-title">查询楼栋施工进度</div>
        <div class="input-group">
            <input id="building-name" placeholder="输入楼栋名称，如：1号楼" value="1号楼">
            <button class="btn btn-taji" onclick="queryBuilding()">查询施工进度</button>
        </div>
        <div id="building-result" class="result-box hidden"></div>
        <span id="building-loading" class="loading hidden"></span>

        <div class="section-title" style="margin-top:16px;">查询塔吊安装高度</div>
        <div class="input-group">
            <input id="crane-name" placeholder="输入塔吊名称，如：塔吊1" value="塔吊1">
            <button class="btn btn-taji" onclick="queryCraneHeight()">查询安装高度</button>
        </div>
        <div id="crane-result" class="result-box hidden"></div>
        <span id="crane-loading" class="loading hidden"></span>

        <div class="section-title" style="margin-top:16px;">查询设备运行状态</div>
        <div class="input-group">
            <input id="device-status-name" placeholder="输入设备名称，如：塔吊1" value="塔吊1">
            <button class="btn btn-taji-green" onclick="queryDeviceStatus()">查询运行状态</button>
        </div>
        <div id="device-status-result" class="result-box hidden"></div>
        <span id="device-status-loading" class="loading hidden"></span>
    </div>

    <!-- 电梯设备数据查询卡片 -->
    <div class="card">
        <h2>🛗 电梯设备数据查询（tw_lifter_0616）</h2>

        <div class="section-title">电梯在线状态</div>
        <button class="btn btn-taji" onclick="queryElevatorOnline()">查询在线状态</button>
        <span id="elevator-online-loading" class="loading hidden"></span>
        <div id="elevator-online-result" class="result-box hidden"></div>

        <div class="section-title" style="margin-top:16px;">电梯运行数据</div>
        <button class="btn btn-taji" onclick="queryElevatorRuntime()">查询运行数据</button>
        <span id="elevator-runtime-loading" class="loading hidden"></span>
        <div id="elevator-runtime-result" class="result-box hidden"></div>

        <div class="section-title" style="margin-top:16px;">电梯运行数据（按小时）</div>
        <div class="input-group">
            <input id="elevator-hourly-start" placeholder="起始时间，如 2026-06-16 00:00:00（留空默认当天0点）">
            <button class="btn btn-taji-green" onclick="queryElevatorHourly()">查询</button>
        </div>
        <span id="elevator-hourly-loading" class="loading hidden"></span>
        <div id="elevator-hourly-result" class="result-box hidden"></div>

        <div class="section-title" style="margin-top:16px;">笼内人流量（按分钟）</div>
        <div class="input-group">
            <input id="elevator-traffic-start" placeholder="起始时间，如 2026-06-16 00:00:00（留空默认当天0点）">
            <button class="btn btn-taji-green" onclick="queryElevatorTraffic()">查询</button>
        </div>
        <span id="elevator-traffic-loading" class="loading hidden"></span>
        <div id="elevator-traffic-result" class="result-box hidden"></div>

        <div class="section-title" style="margin-top:16px;">当前时刻笼内人数（4个电梯）</div>
        <button class="btn btn-taji" onclick="queryElevatorCurrentPeople()">查询当前笼内人数</button>
        <span id="elevator-people-loading" class="loading hidden"></span>
        <div id="elevator-people-result" class="result-box hidden"></div>
    </div>

    <!-- 批量测试 -->
    <div class="card">
        <h2>🚀 批量测试</h2>
        <button class="btn btn-success" onclick="runAll()">运行全部预设查询</button>
        <button class="btn btn-outline" onclick="showCatalog()">查看接口目录</button>
        <span id="batch-loading" class="loading hidden"></span>
        <div id="batch-result" class="result-box hidden"></div>
    </div>
</div>

<script>
const BASE = '';

function show(el) { document.getElementById(el).classList.remove('hidden'); }
function hide(el) { document.getElementById(el).classList.add('hidden'); }

async function checkStatus() {
    show('status-loading'); hide('status-result');
    try {
        const res = await fetch(BASE + '/test/status');
        const data = await res.json();
        const badge = document.getElementById('status-badge');
        if (data.status === 'running') {
            badge.innerHTML = '<span class="badge badge-ok">运行中</span>';
        } else {
            badge.innerHTML = '<span class="badge badge-error">未就绪</span>';
        }
        document.getElementById('status-result').textContent = JSON.stringify(data, null, 2);
        show('status-result');
    } catch(e) {
        document.getElementById('status-badge').innerHTML = '<span class="badge badge-error">连接失败</span>';
        document.getElementById('status-result').textContent = '错误: ' + e.message;
        show('status-result');
    }
    hide('status-loading');
}

async function submitQuery() {
    const query = document.getElementById('custom-query').value.trim();
    if (!query) return alert('请输入查询内容');
    show('query-loading'); hide('query-result');
    try {
        const res = await fetch(BASE + '/test/query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query: query, description: '自定义查询'})
        });
        const data = await res.json();
        document.getElementById('query-result').textContent = JSON.stringify(data, null, 2);
        show('query-result');
    } catch(e) {
        document.getElementById('query-result').textContent = '错误: ' + e.message;
        show('query-result');
    }
    hide('query-loading');
}

async function presetQuery(desc, query) {
    show('preset-loading'); hide('preset-result');
    try {
        const res = await fetch(BASE + '/test/query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query: query, description: desc})
        });
        const data = await res.json();
        document.getElementById('preset-result').textContent = JSON.stringify(data, null, 2);
        show('preset-result');
    } catch(e) {
        document.getElementById('preset-result').textContent = '错误: ' + e.message;
        show('preset-result');
    }
    hide('preset-loading');
}

// ---- 新增: 塔机静态数据直接查询 ----
async function queryBuilding() {
    const name = document.getElementById('building-name').value.trim();
    if (!name) return alert('请输入楼栋名称');
    show('building-loading'); hide('building-result');
    try {
        const res = await fetch(BASE + '/test/building-progress', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({building_name: name})
        });
        const data = await res.json();
        document.getElementById('building-result').textContent = JSON.stringify(data, null, 2);
        show('building-result');
    } catch(e) {
        document.getElementById('building-result').textContent = '错误: ' + e.message;
        show('building-result');
    }
    hide('building-loading');
}

async function queryCraneHeight() {
    const name = document.getElementById('crane-name').value.trim();
    if (!name) return alert('请输入塔吊名称');
    show('crane-loading'); hide('crane-result');
    try {
        const res = await fetch(BASE + '/test/crane-height', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({device_name: name})
        });
        const data = await res.json();
        document.getElementById('crane-result').textContent = JSON.stringify(data, null, 2);
        show('crane-result');
    } catch(e) {
        document.getElementById('crane-result').textContent = '错误: ' + e.message;
        show('crane-result');
    }
    hide('crane-loading');
}

async function queryDeviceStatus() {
    const name = document.getElementById('device-status-name').value.trim();
    if (!name) return alert('请输入设备名称');
    show('device-status-loading'); hide('device-status-result');
    try {
        const res = await fetch(BASE + '/test/device-status', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({device_name: name})
        });
        const data = await res.json();
        document.getElementById('device-status-result').textContent = JSON.stringify(data, null, 2);
        show('device-status-result');
    } catch(e) {
        document.getElementById('device-status-result').textContent = '错误: ' + e.message;
        show('device-status-result');
    }
    hide('device-status-loading');
}

async function runAll() {
    show('batch-loading'); hide('batch-result');
    try {
        const res = await fetch(BASE + '/test/run-all', {method: 'POST'});
        const data = await res.json();
        document.getElementById('batch-result').textContent = JSON.stringify(data, null, 2);
        show('batch-result');
    } catch(e) {
        document.getElementById('batch-result').textContent = '错误: ' + e.message;
        show('batch-result');
    }
    hide('batch-loading');
}

async function showCatalog() {
    show('batch-loading'); hide('batch-result');
    try {
        const res = await fetch(BASE + '/test/catalog');
        const data = await res.json();
        document.getElementById('batch-result').textContent = JSON.stringify(data, null, 2);
        show('batch-result');
    } catch(e) {
        document.getElementById('batch-result').textContent = '错误: ' + e.message;
        show('batch-result');
    }
    hide('batch-loading');
}

// ---- 新增: 电梯设备直接查询 ----
async function queryElevatorOnline() {
    show('elevator-online-loading'); hide('elevator-online-result');
    try {
        const res = await fetch(BASE + '/test/elevator-online', { method: 'POST' });
        const data = await res.json();
        document.getElementById('elevator-online-result').textContent = JSON.stringify(data, null, 2);
        show('elevator-online-result');
    } catch(e) {
        document.getElementById('elevator-online-result').textContent = '错误: ' + e.message;
        show('elevator-online-result');
    }
    hide('elevator-online-loading');
}

async function queryElevatorRuntime() {
    show('elevator-runtime-loading'); hide('elevator-runtime-result');
    try {
        const res = await fetch(BASE + '/test/elevator-runtime', { method: 'POST' });
        const data = await res.json();
        document.getElementById('elevator-runtime-result').textContent = JSON.stringify(data, null, 2);
        show('elevator-runtime-result');
    } catch(e) {
        document.getElementById('elevator-runtime-result').textContent = '错误: ' + e.message;
        show('elevator-runtime-result');
    }
    hide('elevator-runtime-loading');
}

async function queryElevatorHourly() {
    const startTime = document.getElementById('elevator-hourly-start').value.trim() || null;
    show('elevator-hourly-loading'); hide('elevator-hourly-result');
    try {
        const body = {};
        if (startTime) { body.start_time = startTime; }
        const res = await fetch(BASE + '/test/elevator-hourly', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
        const data = await res.json();
        document.getElementById('elevator-hourly-result').textContent = JSON.stringify(data, null, 2);
        show('elevator-hourly-result');
    } catch(e) {
        document.getElementById('elevator-hourly-result').textContent = '错误: ' + e.message;
        show('elevator-hourly-result');
    }
    hide('elevator-hourly-loading');
}

async function queryElevatorTraffic() {
    const startTime = document.getElementById('elevator-traffic-start').value.trim() || null;
    show('elevator-traffic-loading'); hide('elevator-traffic-result');
    try {
        const body = {};
        if (startTime) { body.start_time = startTime; }
        const res = await fetch(BASE + '/test/elevator-traffic', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body)
        });
        const data = await res.json();
        document.getElementById('elevator-traffic-result').textContent = JSON.stringify(data, null, 2);
        show('elevator-traffic-result');
    } catch(e) {
        document.getElementById('elevator-traffic-result').textContent = '错误: ' + e.message;
        show('elevator-traffic-result');
    }
    hide('elevator-traffic-loading');
}

async function queryElevatorCurrentPeople() {
    show('elevator-people-loading'); hide('elevator-people-result');
    try {
        const res = await fetch(BASE + '/test/elevator-current-people', { method: 'POST' });
        const data = await res.json();
        document.getElementById('elevator-people-result').textContent = JSON.stringify(data, null, 2);
        show('elevator-people-result');
    } catch(e) {
        document.getElementById('elevator-people-result').textContent = '错误: ' + e.message;
        show('elevator-people-result');
    }
    hide('elevator-people-loading');
}

// 初始化预设查询按钮
const presets = [
    {desc: '人员总览查询', query: '查询今天人员总览'},
    {desc: '告警记录查询', query: '看看最近告警记录'},
    {desc: '班组出勤查询', query: '今天班组出勤情况'},
    {desc: '人员定位查询', query: '人员定位24小时走势'},
    {desc: '基站物资查询', query: '基站物资信息'},
    {desc: '设备统计查询', query: '设备信息统计'},
    {desc: '组织架构查询', query: '组织架构'},
    {desc: '考勤统计查询', query: '今天考勤统计'},
];
const div = document.getElementById('preset-buttons');
presets.forEach(p => {
    const btn = document.createElement('button');
    btn.className = 'btn btn-outline';
    btn.textContent = p.desc;
    btn.onclick = () => presetQuery(p.desc, p.query);
    div.appendChild(btn);
});

// 新增: 塔机静态数据预设查询按钮 (默认查询全部)
const tajiPresets = [
    {desc: '全部楼栋施工进度', query: '查询全部楼栋施工进度'},
    {desc: '全部塔吊安装高度', query: '查询全部塔吊安装高度'},
    {desc: '全部设备运行状态', query: '查询全部设备运行状态'},
];
const tajiDiv = document.getElementById('taji-preset-buttons');
tajiPresets.forEach(p => {
    const btn = document.createElement('button');
    btn.className = 'btn btn-taji';
    btn.textContent = p.desc;
    btn.onclick = () => presetQuery(p.desc, p.query);
    tajiDiv.appendChild(btn);
});

// 页面加载时自动检查状态
checkStatus();
</script>
</body>
</html>"""


# ==================== 启动入口 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("  工地安全数据查询测试 HTTP 服务")
    print("=" * 60)
    print(f"  测试页面:          http://127.0.0.1:{SERVER_PORT}/")
    print(f"  状态检查:          http://127.0.0.1:{SERVER_PORT}/test/status")
    print(f"  自定义查询:        POST http://127.0.0.1:{SERVER_PORT}/test/query")
    print(f"  批量测试:          POST http://127.0.0.1:{SERVER_PORT}/test/run-all")
    print(f"  接口目录:          GET  http://127.0.0.1:{SERVER_PORT}/test/catalog")
    print(f"  --- 新增塔机静态数据查询 ---")
    print(f"  楼栋施工进度:      POST http://127.0.0.1:{SERVER_PORT}/test/building-progress")
    print(f"  塔吊安装高度:      POST http://127.0.0.1:{SERVER_PORT}/test/crane-height")
    print(f"  设备运行状态:      POST http://127.0.0.1:{SERVER_PORT}/test/device-status")
    print(f"  --- 新增电梯设备数据查询 (tw_lifter_0616) ---")
    print(f"  电梯在线状态:      POST http://127.0.0.1:{SERVER_PORT}/test/elevator-online")
    print(f"  电梯运行数据:      POST http://127.0.0.1:{SERVER_PORT}/test/elevator-runtime")
    print(f"  电梯运行(按小时):   POST http://127.0.0.1:{SERVER_PORT}/test/elevator-hourly")
    print(f"  电梯笼内人流量:    POST http://127.0.0.1:{SERVER_PORT}/test/elevator-traffic")
    print(f"  电梯当前笼内人数:  POST http://127.0.0.1:{SERVER_PORT}/test/elevator-current-people")
    print("=" * 60)
    print()

    server = HTTPServer(("0.0.0.0", SERVER_PORT), TestHandler)
    print(f"服务已启动，访问 http://127.0.0.1:{SERVER_PORT}/ 打开测试页面")
    print("按 Ctrl+C 停止服务\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()