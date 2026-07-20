#!/usr/bin/env python3
"""
大屏/定位/设备/人员接口测试 - 带 RSA 签名认证

参考 Java 签名逻辑:
  timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds().ToString()
  nonce = Guid.NewGuid().ToString("N")
  signSource = AccessKey + timestamp + nonce
  sign = GenerateRSASign(signSource, PrivateKey)
  encodedSign = UnityWebRequest.EscapeURL(sign)
"""

import base64
import json
import time
import uuid
import requests
from urllib.parse import quote, urlencode

# ==================== 配置 ====================
BASE_URL = "https://dw.yzw.cn/open"
ACCESS_KEY = "be69162bdd4e46619ac95824a88b1ec2"
PROJECT_KEY = "e3ae0e4a0ab6478da33bce089237a9ed"
PRIVATE_KEY_BASE64 = (
    "MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGBAMjBwnRaM3p+uDJQ0WsESmaOIbgNOtvkIMacRuJK+okoIqJFeWQhjPvimnTaQdvHFuYemaLllkH5tWNTlxM4cwSDw7OISc/2wGcfn8jX+QWu46MohsfNGudBG+/izia3I3QtwZmlSDBRjOYK2KbmO853zMxZnyj2b5lLCo/nixnjAgMBAAECgYAPbPf2MCu7DCHQiyFneDDUhYC1kp3eevGolFlL/QsYK+A3y/loxlbKnSq7sz0scbVJB4cYzn+HrUDEE46AGK4zQt5B4EAqtDsyC0Lwjpo2O4ObrLPeSN+CehUZ4fnXqnPq+/+vwjflzysYPh8ij7FYGOhme2QpPgBlVNX9zYlQgQJBAOMFE3jN2WazdXZfmfQIJPjC6F0fIEhXgSyhqpxeB5iMOyu5jmI2HhMVmqUogvj3WNjwxeuO87DpoMDehoBBQIECQQDiYmt9UMEEIw3ko6zklUM6KOJuf4CuniCplW9B7W14QgSYF/fjQ+5J6MHSPIR5n4JSc5ih72qgfobSHtj+uyhjAkB8iLlQyKNcyk9CW1lJ2/nkGI99HekIpi/vOtQrqQ1DqpF+//BSgdtnnq9RsHKAfrdXcmUwPiACSXbstmVUD/eBAkBHNPnmcu4jZPtLvYf2ZlS9CHsgko5hXm+bp9tU+1+BghJ73J4mKAndyY6dmFd7Agc19BJAbVQ2o1W45ecPSMNNAkEAmxqzT4nt0pujXBP5XsLuta0WT9XszMNC1yJef1kcTCMHQGntmNHhD/oOheGyFGc+hOB6AfZbAim9GyCgBxQDMQ=="
)

# ---- 私钥加载（延迟初始化） ----
_private_key = None


def _get_private_key():
    """加载 RSA 私钥, 自动尝试 PKCS#1 和 PKCS#8 格式"""
    global _private_key
    if _private_key is not None:
        return _private_key

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend

    formats = [
        ("PKCS#1", "-----BEGIN RSA PRIVATE KEY-----\n" + PRIVATE_KEY_BASE64 + "\n-----END RSA PRIVATE KEY-----"),
        ("PKCS#8", "-----BEGIN PRIVATE KEY-----\n" + PRIVATE_KEY_BASE64 + "\n-----END PRIVATE KEY-----"),
    ]

    for fmt_name, pem_str in formats:
        try:
            key = serialization.load_pem_private_key(
                pem_str.encode(), password=None, backend=default_backend()
            )
            print(f"[INFO] 私钥加载成功 (格式: {fmt_name})")
            _private_key = key
            return key
        except Exception as e:
            print(f"[WARN] {fmt_name} 格式加载失败: {e}")

    raise ValueError("无法加载私钥，请检查密钥格式")


# ---- 签名算法 ----
def generate_sign(access_key: str, timestamp: str, nonce: str) -> str:
    """生成 RSA-SHA256 签名（返回原始 Base64，不做 URL 编码）

    对应 Java:
      signSource = AccessKey + timestamp + nonce
      sign = GenerateRSAsign(signSource, PrivateKey)  // SHA256withRSA → Base64
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    private_key = _get_private_key()
    sign_source = access_key + timestamp + nonce

    signature = private_key.sign(
        sign_source.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )

    return base64.b64encode(signature).decode()


def build_request(path: str, extra_params: dict = None):
    """
    构建带签名的请求 URL（参数顺序与 Java 端保持一致）

    URL 模板: {baseUrl}/{path}?projectKey={projectKey}&accessKey={accessKey}&timestamp={timestamp}&nonce={nonce}&sign={encodedSign}
    """
    timestamp = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    raw_sign = generate_sign(ACCESS_KEY, timestamp, nonce)
    encoded_sign = quote(raw_sign, safe="")  # 对应 Java UnityWebRequest.EscapeURL

    # 按模板顺序拼接参数：projectKey → accessKey → timestamp → nonce → sign
    parts = []

    # projectKey 放最前面（与 Java 端模板一致）
    if extra_params and "projectKey" in extra_params:
        parts.append(f"projectKey={quote(str(extra_params['projectKey']), safe='')}")

    parts.append(f"accessKey={quote(ACCESS_KEY, safe='')}")
    parts.append(f"timestamp={quote(timestamp, safe='')}")
    parts.append(f"nonce={quote(nonce, safe='')}")
    parts.append(f"sign={encoded_sign}")

    # 其余业务参数追加在后面
    if extra_params:
        for key, val in extra_params.items():
            if key != "projectKey":
                parts.append(f"{key}={quote(str(val), safe='')}")

    full_url = f"{BASE_URL}/{path.lstrip('/')}?{'&'.join(parts)}"
    return full_url


# ---- 请求辅助 ----
def _print_response(resp):
    """格式化打印响应"""
    print(f"  状态码: {resp.status_code}")
    print(f"  耗时: {resp.elapsed.total_seconds():.2f}s")
    try:
        data = resp.json()
        code = data.get("code") or data.get("status") or data.get("resultCode")
        msg = data.get("msg") or data.get("message") or ""
        print(f"  业务码: {code}  消息: {msg}")
        resp_str = json.dumps(data, ensure_ascii=False, indent=2)
        print(f"  响应:\n{resp_str}")
    except (json.JSONDecodeError, ValueError):
        text = resp.text[:2000]
        print(f"  响应(文本):\n{text}")


def test_get(path: str, desc: str, extra_params: dict = None):
    """发送 GET 请求"""
    url = build_request(path, extra_params)
    print(f"\n{'─'*60}")
    print(f"[GET] {desc}")
    print(f"  Path: /{path}")
    print(f"  URL: {url}")
    try:
        resp = requests.get(url, timeout=30)
        _print_response(resp)
    except requests.RequestException as e:
        print(f"  请求失败: {e}")


def test_post(path: str, desc: str, extra_params: dict = None):
    """发送 POST 请求"""
    url = build_request(path, extra_params)
    print(f"\n{'─'*60}")
    print(f"[POST] {desc}")
    print(f"  Path: /{path}")
    print(f"  URL: {url}")
    if extra_params:
        print(f"  Params: {json.dumps(extra_params, ensure_ascii=False)}")
    try:
        resp = requests.post(url, json=extra_params, timeout=30)
        _print_response(resp)
    except requests.RequestException as e:
        print(f"  请求失败: {e}")


# ==================== 全部接口测试 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("  大屏/定位/设备/人员 接口测试 (RSA 签名认证)")
    print(f"  Base URL : {BASE_URL}")
    print(f"  AccessKey: {ACCESS_KEY}")
    print(f"  ProjectKey: {PROJECT_KEY}")
    print("=" * 60)

    # ---- 大屏相关 ----
    print("\n" + "▌" * 30)
    print("▌  一、大屏相关")
    print("▌" * 30)

    test_get("bigScreen/BigsHome/personOverall",
             "首页人数总览",
             {"projectKey": PROJECT_KEY})

    test_get("bigScreen/BigsHome/todayPersonHourStat",
             "当天人员时间分布",
             {"projectKey": PROJECT_KEY})

    test_get("bigScreen/BigsHome/todayTeamsAtteStat",
             "今日班组出勤情况",
             {"projectKey": PROJECT_KEY})

    test_get("bigScreen/BigsHome/weekEnterpriseAtteStat",
             "近七日参建方人员出勤情况",
             {"projectKey": PROJECT_KEY})

    test_get("bigScreen/bigAlarm/getAlarmRecord",
             "分页获取告警记录",
             {"projectKey": PROJECT_KEY, "pageNum": 1, "pageSize": 50})

    test_get("bigScreen/bigAlarm/getMonthRecordSubType",
             "近三十天预警类型分析",
             {"projectKey": PROJECT_KEY})

    test_get("bigScreen/bigAlarm/getMonthRecordStatus",
             "近三十日报警处理情况",
             {"projectKey": PROJECT_KEY})

    # 从 weekEnterpriseAtteStat 响应中提取的企业ID示例
    test_get("bigScreen/bigAlarm/getMonthEnterpriseRecordNum",
             "近三十天参建公司下班组告警数量",
             {"projectKey": PROJECT_KEY, "enterpriseId": "2057708839361163266"})

    # 从 todayTeamsAtteStat 响应中提取的班组ID示例
    test_get("bigScreen/bigAlarm/getMonthOrganRecordNum",
             "近三十天班组各告警数量",
             {"projectKey": PROJECT_KEY, "organId": "2057708845082193921"})

    test_get("bigScreen/BigsLayer/layerAreaPersonList",
             "作业面人员列表",
             {"projectKey": PROJECT_KEY, "cadId": "2057688579069906945", "areaId": "2057688579069906945"})

    # ---- 定位相关 ----
    print("\n" + "▌" * 30)
    print("▌  二、定位相关")
    print("▌" * 30)

    test_post("location/snapshootProjectPersonCountV3",
              "今日人员定位-24H走势图(每分钟人数)",
              {"projectKey": PROJECT_KEY, "startDate": "2026-06-01 00:00:00", "endDate": "2026-06-03 23:59:59"})

    test_post("location/personCurLocation/v2",
              "今日人员定位-人员列表",
              {"projectKey": PROJECT_KEY})

    test_post("location/track",
              "人员轨迹",
              {"projectKey": PROJECT_KEY, "day": "2026-06-03", "platformPersonId": "2946882"})
    # ["2946882", "18790049", "16134388", "19244306", "17251731"]
    # ---- 部署相关/物资信息 ----
    print("\n" + "▌" * 30)
    print("▌  三、部署相关/物资信息")
    print("▌" * 30)

    test_get("device/gateway/pageByProjectId",
             "基站物资信息",
             {"projectKey": PROJECT_KEY})

    test_get("asset/quantityStatistics",
             "设备信息统计",
             {"projectKey": PROJECT_KEY})

    # ---- 运维相关/设备运维信息 ----
    print("\n" + "▌" * 30)
    print("▌  四、运维相关/设备运维信息")
    print("▌" * 30)

    test_get("device/gateway/page",
             "主基站信息(分页)",
             {"projectKey": PROJECT_KEY, "pageNum": 1, "pageSize": 10})

    test_post("device/label/page",
              "标签信息(分页)",
              {"projectKey": PROJECT_KEY, "pageNum": 1, "pageSize": 10})

    # ---- 项目相关 ----
    print("\n" + "▌" * 30)
    print("▌  五、项目相关")
    print("▌" * 30)

    test_post("person/page",
              "分页获取人员库",
              {"projectKey": PROJECT_KEY, "pageNum": 1, "pageSize": 10})

    # ---- 组织架构 ----
    print("\n" + "▌" * 30)
    print("▌  六、组织架构")
    print("▌" * 30)

    test_get("organ/tree",
             "获取参建公司及其班组",
             {"projectKey": PROJECT_KEY})

    # ---- 统计相关 ----
    print("\n" + "▌" * 30)
    print("▌  七、统计相关")
    print("▌" * 30)

    test_post("report/attendance/attendanceDay",
              "作业面日考勤统计",
              {"projectKey": PROJECT_KEY, "date": "2026-06-03"})

    print("\n" + "=" * 60)
    print("  全部接口测试完成!")
    print("=" * 60)