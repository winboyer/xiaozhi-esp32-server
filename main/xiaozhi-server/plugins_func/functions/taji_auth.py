"""塔机静态数据 API - 共享认证与数据查询工具

提供 RSA 公钥获取、加密登录、Token 缓存，以及楼栋/设备数据的分页查询功能。
被 query_taji_height.py、query_building_progress.py、query_device_status.py 共用。
"""

import json
import time
import base64
from typing import Any, Dict, List, Optional

import requests
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

# ==================== 塔机 API 配置 ====================
TAJI_AUTH_BASE_URL = "http://115.159.67.12:8081"
TAJI_DATA_BASE_URL = "http://115.159.67.12:8084"
TAJI_USERNAME = "jiangjunci"
TAJI_PASSWORD = "ZJWF2025"
TAJI_PROJECT_ID = "P000000073"

# 登录 Token 缓存（模块级，所有引用方共享）
_cached_token: Optional[str] = None
_cached_public_key: Optional[Any] = None


# ==================== RSA 工具 ====================

def _load_public_key_from_pem(pem_str: str):
    """从 PEM 格式字符串加载 RSA 公钥"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend

    if not pem_str or not isinstance(pem_str, str):
        return None

    pem_clean = pem_str.strip()
    if "-----BEGIN" not in pem_clean:
        pem_clean = "-----BEGIN PUBLIC KEY-----\n" + pem_clean + "\n-----END PUBLIC KEY-----"

    try:
        return serialization.load_pem_public_key(
            pem_clean.encode("utf-8"), backend=default_backend()
        )
    except Exception:
        if "-----BEGIN RSA PUBLIC KEY-----" not in pem_clean:
            try:
                pem_pkcs1 = pem_clean.replace(
                    "-----BEGIN PUBLIC KEY-----", "-----BEGIN RSA PUBLIC KEY-----"
                ).replace(
                    "-----END PUBLIC KEY-----", "-----END RSA PUBLIC KEY-----"
                )
                return serialization.load_pem_public_key(
                    pem_pkcs1.encode("utf-8"), backend=default_backend()
                )
            except Exception:
                pass
        return None


def _rsa_encrypt(public_key, plaintext: str) -> str:
    """RSA PKCS1v15 加密"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    plaintext_bytes = plaintext.encode("utf-8")
    ciphertext = public_key.encrypt(plaintext_bytes, padding.PKCS1v15())
    return base64.b64encode(ciphertext).decode("utf-8")


def _rsa_encrypt_oaep(public_key, plaintext: str) -> str:
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


# ==================== 认证流程 ====================

def get_access_token() -> Optional[str]:
    """获取塔机 API 的 access_token（带缓存，先 PKCS1v15 后 OAEP 回退）"""
    global _cached_token, _cached_public_key

    if _cached_token:
        return _cached_token

    try:
        # Step 1: 获取 RSA 公钥
        resp = requests.get(
            f"{TAJI_AUTH_BASE_URL}/api/user/auth/public-key",
            headers={"accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        pub_key_str = resp.json().get("data", {}).get("public_key", "")
        if not pub_key_str:
            logger.bind(tag=TAG).error("获取公钥失败: 响应中无 public_key 字段")
            return None

        public_key = _load_public_key_from_pem(pub_key_str)
        if not public_key:
            logger.bind(tag=TAG).error("RSA 公钥加载失败")
            return None

        # Step 2: 加密登录
        login_plaintext = json.dumps({
            "username": TAJI_USERNAME,
            "password": TAJI_PASSWORD,
            "captcha": "",
            "checkKey": "",
            "token": "",
        }, ensure_ascii=False)

        def _do_login(encrypt_mode: str) -> Optional[str]:
            """执行一次登录尝试"""
            if encrypt_mode == "pkcs1":
                encrypted = _rsa_encrypt(public_key, login_plaintext)
            else:
                encrypted = _rsa_encrypt_oaep(public_key, login_plaintext)

            resp = requests.post(
                f"{TAJI_AUTH_BASE_URL}/api/user/auth/login",
                json={"encrypted_data": encrypted},
                headers={"accept": "application/json", "Content-Type": "application/json"},
                timeout=30,
            )
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

        # 主方案: PKCS1v15
        token = _do_login("pkcs1")
        if not token:
            logger.bind(tag=TAG).info("PKCS1v15 登录失败, 尝试 OAEP/SHA-256...")
            token = _do_login("oaep")

        if token:
            logger.bind(tag=TAG).info(f"塔机 API 登录成功, token: {token[:20]}...")
            _cached_token = token
            return token
        else:
            logger.bind(tag=TAG).error("所有加密模式登录均失败")
            return None

    except Exception as e:
        logger.bind(tag=TAG).error(f"塔机 API 认证异常: {e}")
        return None


# ==================== 数据查询 ====================

def query_deviceinfos(access_token: str) -> List[Dict[str, Any]]:
    """查询设备基本信息（全量分页）
    
    GET /api/data/deviceinfos?project_id={project_id}
    """
    all_devices = []
    page = 1
    page_size = 100

    while True:
        try:
            resp = requests.get(
                f"{TAJI_DATA_BASE_URL}/api/data/deviceinfos",
                headers={
                    "accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
                params={
                    "page": page,
                    "page_size": page_size,
                    "project_id": TAJI_PROJECT_ID,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            items = (
                data.get("data", {}).get("list")
                or data.get("data", {}).get("records")
                or data.get("data", {}).get("items")
                or data.get("list")
                or data.get("data")
            )
            # 兼容 data 直接是 list 的情况
            if isinstance(items, list):
                all_devices.extend(items)
                if len(items) < page_size:
                    break
                page += 1
            else:
                break

        except Exception as e:
            logger.bind(tag=TAG).error(f"查询设备信息失败 (page={page}): {e}")
            break

    return all_devices


def query_buildings(access_token: str) -> List[Dict[str, Any]]:
    """查询楼栋信息（全量分页）
    
    GET /api/data/buildings?project_id={project_id}
    """
    all_buildings = []
    page = 1
    page_size = 100

    while True:
        try:
            resp = requests.get(
                f"{TAJI_DATA_BASE_URL}/api/data/buildings",
                headers={
                    "accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
                params={
                    "page": page,
                    "page_size": page_size,
                    "project_id": TAJI_PROJECT_ID,
                },
                timeout=30,
            )
            resp.raise_for_status()
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

        except Exception as e:
            logger.bind(tag=TAG).error(f"查询楼栋信息失败 (page={page}): {e}")
            break

    return all_buildings


# ==================== 通用解析工具 ====================

def parse_extra_fields(device: dict) -> list:
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


def get_crane_height(device: dict) -> str:
    """从设备信息中提取塔机高度"""
    extra_fields = parse_extra_fields(device)
    for field in extra_fields:
        if isinstance(field, dict) and field.get("label") == "塔机高度":
            return field.get("value", "")
    return ""


def get_device_name(device: dict) -> str:
    """提取设备显示名称"""
    return device.get("device_name", "") or device.get("deviceName", "") or device.get("name", "")


def get_building_name(building: dict) -> str:
    """提取楼栋显示名称"""
    return building.get("building_name", "") or building.get("buildingName", "") or building.get("name", "")


def parse_online_status(status) -> str:
    """解析在线状态"""
    if status == 1 or status == "1":
        return "运行中"
    elif status == 0 or status == "0":
        return "已离线/停止"
    else:
        return f"未知状态 ({status})"


def match_number(name: str, target: str) -> bool:
    """模糊匹配: 提取数字判断是否匹配"""
    import re
    numbers = re.findall(r'\d+', target)
    if numbers:
        for num in numbers:
            if num in name:
                return True
    return False


def parse_taji_height(device: Dict[str, Any]) -> Dict[str, Any]:
    """从设备记录中提取塔机高度信息（结构化）"""
    result = {
        "device_id": device.get("id"),
        "device_name": device.get("device_name", ""),
        "online": device.get("online_status") == 1,
        "height": None,
        "height_raw": "",
        "update_time": "",
        "hidden": False,
    }

    device_info = device.get("device_info", {})
    if isinstance(device_info, dict):
        result["update_time"] = device_info.get("update_time", "")
        extra_fields_raw = device_info.get("extra_fields", "[]")
        try:
            extra_fields = json.loads(extra_fields_raw) if isinstance(extra_fields_raw, str) else extra_fields_raw
            for field in extra_fields:
                label = field.get("label", "")
                value = field.get("value", "")
                if "塔机高度" in label:
                    result["height_raw"] = value
                    height_str = value.replace("m", "").replace("M", "").strip()
                    try:
                        result["height"] = float(height_str)
                    except (ValueError, TypeError):
                        result["height"] = None
                if "是否隐藏" in label:
                    result["hidden"] = value in ("是", "true", "True", "1")
        except (json.JSONDecodeError, TypeError):
            pass

    return result