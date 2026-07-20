#!/usr/bin/env python3
"""
塔机静态数据查询测试 - 完整认证工作流

工作流程:
  1. GET  /api/user/auth/public-key  获取 RSA 公钥
  2. POST /api/user/auth/login        RSA 加密登录, 获取 access_token
  3. GET  /api/data/buildings         查询楼栋基本信息 (分页)
  4. GET  /api/data/deviceinfos       查询设备基本信息 (分页)

加密流程: 原始明文 → JSON序列化 → RSA公钥加密 → Base64 → { encrypted_data }
"""

import json
import time
import base64
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

# ==================== 配置 ====================
AUTH_BASE_URL = "http://115.159.67.12:8081"
DATA_BASE_URL = "http://115.159.67.12:8084"

USERNAME = "jiangjunci"
PASSWORD = "ZJWF2025"
PROJECT_ID = "P000000073"

# ==================== RSA 加密工具 ====================
def load_public_key_from_pem(pem_str: str):
    """
    从 PKCS#8 PEM 格式字符串加载 RSA 公钥

    支持格式:
      - PKCS#8: -----BEGIN PUBLIC KEY-----
      - PKCS#1: -----BEGIN RSA PUBLIC KEY-----

    Args:
        pem_str: PEM 格式的公钥字符串

    Returns:
        RSA 公钥对象, 失败返回 None
    """
    if not pem_str or not isinstance(pem_str, str):
        return None

    # 清理公钥字符串
    pem_clean = pem_str.strip()

    # 确保有正确的 PEM 头尾
    if "-----BEGIN" not in pem_clean:
        # 可能是纯 base64 编码的 DER 格式, 尝试包装
        pem_clean = "-----BEGIN PUBLIC KEY-----\n" + pem_clean + "\n-----END PUBLIC KEY-----"

    try:
        public_key = serialization.load_pem_public_key(
            pem_clean.encode("utf-8"),
            backend=default_backend()
        )
        key_size = public_key.key_size
        print(f"  ✓ RSA 公钥加载成功 (PKCS#8 PEM, {key_size}-bit)")
        return public_key
    except Exception as e:
        print(f"  ✗ PKCS#8 公钥加载失败: {e}")
        # 尝试 PKCS#1 格式
        if "-----BEGIN RSA PUBLIC KEY-----" not in pem_clean:
            try:
                pem_pkcs1 = pem_clean.replace(
                    "-----BEGIN PUBLIC KEY-----", "-----BEGIN RSA PUBLIC KEY-----"
                ).replace(
                    "-----END PUBLIC KEY-----", "-----END RSA PUBLIC KEY-----"
                )
                public_key = serialization.load_pem_public_key(
                    pem_pkcs1.encode("utf-8"),
                    backend=default_backend()
                )
                print(f"  ✓ RSA 公钥加载成功 (PKCS#1 格式, {public_key.key_size}-bit)")
                return public_key
            except Exception:
                pass
        return None


def rsa_encrypt(public_key, plaintext: str) -> str:
    """
    使用 RSA 公钥加密数据 (PKCS1v15 填充)

    加密流程: 明文 → UTF-8编码 → RSA公钥加密(PKCS1v15) → Base64

    说明: 大多数 Java/Spring 后端使用 PKCS1v15 填充,
          与 JSEncrypt 和 Java Cipher "RSA/ECB/PKCS1Padding" 兼容。

    Args:
        public_key: RSA 公钥对象
        plaintext: 明文字符串

    Returns:
        Base64 编码的密文

    Raises:
        ValueError: 加密失败时抛出
    """
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


def rsa_encrypt_oaep(public_key, plaintext: str) -> str:
    """
    使用 RSA 公钥加密数据 (OAEP/SHA-256 填充, 备选方案)

    Args:
        public_key: RSA 公钥对象
        plaintext: 明文字符串

    Returns:
        Base64 编码的密文

    Raises:
        ValueError: 加密失败时抛出
    """
    plaintext_bytes = plaintext.encode("utf-8")
    key_size_bytes = public_key.key_size // 8
    max_plaintext_size = key_size_bytes - 2 * 32 - 2  # OAEP SHA-256 开销

    if len(plaintext_bytes) > max_plaintext_size:
        raise ValueError(
            f"明文过长 ({len(plaintext_bytes)} bytes), "
            f"RSA {public_key.key_size}-bit OAEP 最大加密 {max_plaintext_size} bytes"
        )

    ciphertext = public_key.encrypt(
        plaintext_bytes,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode("utf-8")


def encrypt_login_data(public_key, username: str, password: str) -> dict:
    """
    加密登录凭证 (PKCS1v15 填充, 主方案)

    流程: 明文 JSON → RSA 公钥加密(PKCS1v15) → Base64 → { encrypted_data }

    与 Java Cipher "RSA/ECB/PKCS1Padding" 和 JSEncrypt 兼容。

    Args:
        public_key: RSA 公钥对象
        username: 用户名
        password: 密码

    Returns:
        加密后的请求体 {"encrypted_data": "..."}
    """
    login_plaintext = json.dumps({
        "username": username,
        "password": password,
        "captcha": "",
        "checkKey": "",
        "token": "",
    }, ensure_ascii=False)

    encrypted = rsa_encrypt(public_key, login_plaintext)
    return {"encrypted_data": encrypted}


def encrypt_login_data_oaep(public_key, username: str, password: str) -> dict:
    """
    加密登录凭证 (OAEP/SHA-256 填充, 备选方案)

    Args:
        public_key: RSA 公钥对象
        username: 用户名
        password: 密码

    Returns:
        加密后的请求体 {"encrypted_data": "..."}
    """
    login_plaintext = json.dumps({
        "username": username,
        "password": password,
        "captcha": "",
        "checkKey": "",
        "token": "",
    }, ensure_ascii=False)

    encrypted = rsa_encrypt_oaep(public_key, login_plaintext)
    return {"encrypted_data": encrypted}


# ==================== 请求辅助 ====================
def _print_response(resp, method: str, desc: str):
    """格式化打印响应"""
    print(f"\n{'─'*60}")
    print(f"[{method}] {desc}")
    print(f"  状态码: {resp.status_code}")
    print(f"  耗时: {resp.elapsed.total_seconds():.2f}s")
    try:
        data = resp.json()
        resp_str = json.dumps(data, ensure_ascii=False, indent=2)
        if len(resp_str) > 5000:
            print(f"  响应(截取 5000 字符):\n{resp_str[:5000]}...")
        else:
            print(f"  响应:\n{resp_str}")
    except (json.JSONDecodeError, ValueError):
        text = resp.text[:3000]
        print(f"  响应(文本):\n{text}")


# ==================== Step 1: 获取 RSA 公钥 ====================
def step1_get_public_key() -> str:
    """
    Step 1: 获取 RSA 公钥

    GET /api/user/auth/public-key

    Returns:
        PEM 格式的公钥字符串
    """
    url = f"{AUTH_BASE_URL}/api/user/auth/public-key"
    print(f"\n{'█'*30}")
    print(f"█  Step 1: 获取 RSA 公钥")
    print(f"█  GET {url}")
    print(f"{'█'*30}")

    try:
        resp = requests.get(url, headers={"accept": "application/json"}, timeout=30)
        _print_response(resp, "GET", "获取 RSA 公钥")

        if resp.status_code != 200:
            print(f"  ⚠ 获取公钥失败, 状态码: {resp.status_code}")
            return None

        data = resp.json()
        # 尝试从不同字段提取公钥 (字段名: data.public_key)
        pub_key = (
            data.get("data", {}).get("public_key")
        )

        if isinstance(pub_key, str) and "PUBLIC KEY" in pub_key:
            print(f"\n  ✓ 成功提取 RSA 公钥 (长度: {len(pub_key)})")
            return pub_key
        elif isinstance(pub_key, str):
            print(f"\n  ✓ 提取到公钥 (长度: {len(pub_key)})")
            return pub_key
        else:
            print(f"\n  ⚠ 未找到公钥字段, 原始响应结构: {list(data.keys())}")
            print(f"  尝试作为纯文本公钥...")
            return resp.text

    except requests.RequestException as e:
        print(f"  请求失败: {e}")
        return None


# ==================== Step 2: 用户登录 ====================
def step2_login(public_key_str: str, encrypt_func_name: str = "oaep") -> str:
    """
    Step 2: 用户登录, 获取 access_token

    POST /api/user/auth/login

    Args:
        public_key_str: PEM 格式的 RSA 公钥
        encrypt_func_name: 加密模式 "oaep" 或 "pkcs1"

    Returns:
        access_token 字符串, 失败返回 None
    """
    url = f"{AUTH_BASE_URL}/api/user/auth/login"
    print(f"\n{'█'*30}")
    print(f"█  Step 2: 用户登录 (加密模式: {encrypt_func_name})")
    print(f"█  POST {url}")
    print(f"{'█'*30}")

    try:
        public_key = load_public_key_from_pem(public_key_str)
        print(f"  ✓ RSA 公钥加载成功")
    except Exception as e:
        print(f"  ✗ 公钥加载失败: {e}")
        # 尝试用原始字符串直接加载
        try:
            public_key = load_public_key_from_pem(public_key_str.strip())
            print(f"  ✓ 二次尝试加载成功")
        except Exception as e2:
            print(f"  ✗ 二次尝试也失败: {e2}")
            return None

    # 加密登录数据
    try:
        if encrypt_func_name == "pkcs1":
            login_body = encrypt_login_data(public_key, USERNAME, PASSWORD)
        else:
            login_body = encrypt_login_data_oaep(public_key, USERNAME, PASSWORD)

        print(f"  ✓ 登录数据加密完成")
        print(f"  encrypted_data 长度: {len(login_body['encrypted_data'])}")
    except Exception as e:
        print(f"  ✗ 加密失败: {e}")
        return None

    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, json=login_body, headers=headers, timeout=30)
        _print_response(resp, "POST", "用户登录")

        if resp.status_code != 200:
            print(f"  ⚠ 登录失败, 状态码: {resp.status_code}")
            return None

        data = resp.json()
        
        # 打印完整登录响应（方便查看可用项目等信息）
        print(f"\n  --- 登录完整响应 ---")
        print(f"  顶层字段: {list(data.keys())}")
        if "data" in data and isinstance(data["data"], dict):
            print(f"  data 字段: {list(data['data'].keys())}")
        
        token = (
            data.get("data", {}).get("access_token")
            or data.get("data", {}).get("accessToken")
            or data.get("access_token")
            or data.get("accessToken")
            or data.get("token")
        )

        if token:
            print(f"\n  ✓ 登录成功! access_token: {token[:20]}...{token[-10:]}")
            
            # 尝试提取用户可访问的项目列表
            user_projects = (
                data.get("data", {}).get("projects")
                or data.get("data", {}).get("projectList")
                or data.get("data", {}).get("accessibleProjects")
                or data.get("projects")
            )
            if user_projects:
                print(f"  ✓ 可用项目列表:")
                for proj in user_projects[:10]:  # 最多显示10个
                    if isinstance(proj, dict):
                        pid = proj.get("projectId") or proj.get("project_id") or proj.get("id")
                        pname = proj.get("projectName") or proj.get("project_name") or proj.get("name")
                        print(f"      - {pid}: {pname}")
                    else:
                        print(f"      - {proj}")
            
            return token
        else:
            print(f"\n  ⚠ 未找到 access_token")
            return None

    except requests.RequestException as e:
        print(f"  请求失败: {e}")
        return None


# ==================== Step 3: 查询楼栋基本信息 ====================
def step3_get_buildings(access_token: str, page: int = 1, page_size: int = 10, loop_all: bool = False):
    """
    Step 3: 获取楼栋基本信息

    GET /api/data/buildings?page={page}&page_size={page_size}&project_id={project_id}

    Args:
        access_token: Bearer token
        page: 页码
        page_size: 每页条数
        loop_all: 是否循环获取所有页

    Returns:
        楼栋数据列表
    """
    print(f"\n{'█'*30}")
    print(f"█  Step 3: 查询楼栋基本信息")
    print(f"█  project_id={PROJECT_ID}, page={page}, page_size={page_size}")
    print(f"{'█'*30}")

    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    all_buildings = []
    current_page = page

    while True:
        url = f"{DATA_BASE_URL}/api/data/buildings"
        params = {
            "page": current_page,
            "page_size": page_size,
            "project_id": PROJECT_ID,
        }

        print(f"\n  请求第 {current_page} 页...")
        print(f"  GET {url}")
        print(f"  Params: {json.dumps(params)}")

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            _print_response(resp, "GET", f"楼栋信息 (第 {current_page} 页)")

            if resp.status_code != 200:
                print(f"  ⚠ 请求失败, 状态码: {resp.status_code}")
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
                print(f"  ✓ 本页获取 {len(items)} 条记录")

                if not loop_all or len(items) < page_size:
                    break
                current_page += 1
            else:
                print(f"  ⚠ 数据格式异常, 无法提取列表")
                if not loop_all:
                    all_buildings = data
                break

        except requests.RequestException as e:
            print(f"  请求失败: {e}")
            break

    print(f"\n  ✓ 共获取 {len(all_buildings)} 条楼栋记录")
    return all_buildings


# ==================== Step 4: 查询设备基本信息 ====================
def step4_get_deviceinfos(access_token: str, page: int = 1, page_size: int = 10, loop_all: bool = False):
    """
    Step 4: 获取设备基本信息

    GET /api/data/deviceinfos?page={page}&page_size={page_size}&project_id={project_id}

    Args:
        access_token: Bearer token
        page: 页码
        page_size: 每页条数
        loop_all: 是否循环获取所有页

    Returns:
        设备数据列表
    """
    print(f"\n{'█'*30}")
    print(f"█  Step 4: 查询设备基本信息")
    print(f"█  project_id={PROJECT_ID}, page={page}, page_size={page_size}")
    print(f"{'█'*30}")

    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }

    all_devices = []
    current_page = page

    while True:
        url = f"{DATA_BASE_URL}/api/data/deviceinfos"
        params = {
            "page": current_page,
            "page_size": page_size,
            "project_id": PROJECT_ID,
        }

        print(f"\n  请求第 {current_page} 页...")
        print(f"  GET {url}")
        print(f"  Params: {json.dumps(params)}")

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            _print_response(resp, "GET", f"设备信息 (第 {current_page} 页)")

            if resp.status_code != 200:
                print(f"  ⚠ 请求失败, 状态码: {resp.status_code}")
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
                print(f"  ✓ 本页获取 {len(items)} 条记录")

                if not loop_all or len(items) < page_size:
                    break
                current_page += 1
            else:
                print(f"  ⚠ 数据格式异常, 无法提取列表")
                if not loop_all:
                    all_devices = data
                break

        except requests.RequestException as e:
            print(f"  请求失败: {e}")
            break

    print(f"\n  ✓ 共获取 {len(all_devices)} 条设备记录")
    return all_devices


# ==================== 主流程 ====================
def run_full_workflow(loop_all_pages: bool = False):
    """
    运行完整的认证+查询工作流

    Args:
        loop_all_pages: 是否循环获取所有分页数据
    """
    print("=" * 60)
    print("  塔机静态数据查询 - 完整认证工作流")
    print(f"  Auth Server : {AUTH_BASE_URL}")
    print(f"  Data Server : {DATA_BASE_URL}")
    print(f"  Username    : {USERNAME}")
    print(f"  Project ID  : {PROJECT_ID}")
    print("=" * 60)

    # ---- Step 1: 获取 RSA 公钥 ----
    public_key = step1_get_public_key()
    if not public_key:
        print("\n❌ Step 1 失败, 无法获取公钥, 流程终止")
        return

    # ---- Step 2: 用户登录 (PKCS1v15 为主, OAEP 为备选) ----
    access_token = step2_login(public_key, encrypt_func_name="pkcs1")
    if not access_token:
        # 尝试 OAEP 备选方案
        print("\n  ⚠ PKCS1v15 加密登录失败, 尝试 OAEP/SHA-256 填充...")
        access_token = step2_login(public_key, encrypt_func_name="oaep")

    if not access_token:
        print("\n❌ Step 2 失败, 登录未成功, 流程终止")
        return

    # ---- Step 3: 查询楼栋信息 ----
    buildings = step3_get_buildings(access_token, page=1, page_size=10, loop_all=loop_all_pages)

    # ---- Step 4: 查询设备信息 ----
    devices = step4_get_deviceinfos(access_token, page=1, page_size=10, loop_all=loop_all_pages)

    # ---- 汇总 ----
    print("\n" + "=" * 60)
    print("  工作流执行完毕!")
    print(f"  楼栋记录数: {len(buildings) if isinstance(buildings, list) else 'N/A'}")
    print(f"  设备记录数: {len(devices) if isinstance(devices, list) else 'N/A'}")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    # 支持命令行参数
    loop_all = "--loop-all" in sys.argv or "-a" in sys.argv

    run_full_workflow(loop_all_pages=loop_all)