#!/usr/bin/env python3
"""
向阳村项目统一数据查询测试 HTTP 服务（人员数据 + 塔机作业）

基于 RSA 签名认证调用工地安全数据平台查询人员数据，并复用塔机作业接口查询塔机状态，
利用 LLM 对查询内容进行总结。单端口同时服务人员与塔机两类查询。

启动方式：
    python test_xiangyangcun_query_server.py

接口（路径前缀 /xiangyangcun，端口 8007）：
    GET  /xiangyangcun/status            - 服务状态（人员 + 塔机）
    GET  /xiangyangcun/catalog           - 统一接口目录
    POST /xiangyangcun/personnel/query   - 人员数据自然语言查询（LLM 意图 + 查询 + 总结）
    POST /xiangyangcun/taji/nl-query     - 塔机作业状态（自然语言 + LLM 解析）
    GET  /                               - 交互式测试页面

LLM 配置通过环境变量覆盖：
    LLM_BASE_URL / LLM_API_KEY / LLM_MODEL / LLM_TIMEOUT
"""

import base64
import json
import os
import re
import time
import uuid
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, quote

import requests

# 复用塔机作业查询逻辑（与人员数据合并为同一服务、同一端口）
from test_taji_work_status_server import (
    query_tower_crane_work_status,
    query_all_cranes,
    llm_parse_query,
    crane_status_summary,
    TOWER_CRANE_NAME_TO_SN,
)

# ==================== 配置 ====================
SERVER_PORT = 8007

# 向阳村项目数据平台（RSA 签名认证）
XIANGYANGCUN_API_BASE_URL = "https://dw.yzw.cn/open"
XIANGYANGCUN_ACCESS_KEY = "be69162bdd4e46619ac95824a88b1ec2"
XIANGYANGCUN_PROJECT_KEY = "b35df2e91ed642c595ca96d0bc2d9ed9"
XIANGYANGCUN_PRIVATE_KEY_BASE64 = (
    "MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGBAMjBwnRaM3p+uDJQ0WsESmaOIbgNOtvkIMacRuJK+okoIqJFeWQhjPvimnTaQdvHFuYemaLllkH5tWNTlxM4cwSDw7OISc/2wGcfn8jX+QWu46MohsfNGudBG+/izia3I3QtwZmlSDBRjOYK2KbmO853zMxZnyj2b5lLCo/nixnjAgMBAAECgYAPbPf2MCu7DCHQiyFneDDUhYC1kp3eevGolFlL/QsYK+A3y/loxlbKnSq7sz0scbVJB4cYzn+HrUDEE46AGK4zQt5B4EAqtDsyC0Lwjpo2O4ObrLPeSN+CehUZ4fnXqnPq+/+vwjflzysYPh8ij7FYGOhme2QpPgBlVNX9zYlQgQJBAOMFE3jN2WazdXZfmfQIJPjC6F0fIEhXgSyhqpxeB5iMOyu5jmI2HhMVmqUogvj3WNjwxeuO87DpoMDehoBBQIECQQDiYmt9UMEEIw3ko6zklUM6KOJuf4CuniCplW9B7W14QgSYF/fjQ+5J6MHSPIR5n4JSc5ih72qgfobSHtj+uyhjAkB8iLlQyKNcyk9CW1lJ2/nkGI99HekIpi/vOtQrqQ1DqpF+//BSgdtnnq9RsHKAfrdXcmUwPiACSXbstmVUD/eBAkBHNPnmcu4jZPtLvYf2ZlS9CHsgko5hXm+bp9tU+1+BghJ73J4mKAndyY6dmFd7Agc19BJAbVQ2o1W45ecPSMNNAkEAmxqzT4nt0pujXBP5XsLuta0WT9XszMNC1yJef1kcTCMHQGntmNHhD/oOheGyFGc+hOB6AfZbAim9GyCgBxQDMQ=="
)

# LLM 配置（DeepSeek / OpenAI 兼容接口）
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-655f2d0a7fa64b089c9155ce8931bb3b")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "30"))

# ==================== 人员数据接口目录 ====================

PERSONNEL_API_CATALOG = [
    {
        "api_id": "personOverall",
        "path": "bigScreen/BigsHome/personOverall",
        "method": "GET",
        "description": "首页人数总览",
        "params": {"projectKey": XIANGYANGCUN_PROJECT_KEY},
    },
    {
        "api_id": "todayPersonHourStat",
        "path": "bigScreen/BigsHome/todayPersonHourStat",
        "method": "GET",
        "description": "当天人员时间分布（每小时统计）",
        "params": {"projectKey": XIANGYANGCUN_PROJECT_KEY},
    },
    {
        "api_id": "todayTeamsAtteStat",
        "path": "bigScreen/BigsHome/todayTeamsAtteStat",
        "method": "GET",
        "description": "今日班组出勤情况",
        "params": {"projectKey": XIANGYANGCUN_PROJECT_KEY},
    },
    {
        "api_id": "weekEnterpriseAtteStat",
        "path": "bigScreen/BigsHome/weekEnterpriseAtteStat",
        "method": "GET",
        "description": "近七日参建方人员出勤情况",
        "params": {"projectKey": XIANGYANGCUN_PROJECT_KEY},
    },
    {
        "api_id": "layerAreaPersonList",
        "path": "bigScreen/BigsLayer/layerAreaPersonList",
        "method": "GET",
        "description": "作业面人员列表",
        "params": {"projectKey": XIANGYANGCUN_PROJECT_KEY},
    },
    {
        "api_id": "snapshootProjectPersonCountV3",
        "path": "location/snapshootProjectPersonCountV3",
        "method": "POST",
        "description": "今日人员定位-24H走势图（每分钟人数）",
        "params": {"projectKey": XIANGYANGCUN_PROJECT_KEY},
    },
    {
        "api_id": "personCurLocationV2",
        "path": "location/personCurLocation/v2",
        "method": "POST",
        "description": "今日人员定位-人员列表（支持按姓名查询人员所在位置）",
        "params": {"projectKey": XIANGYANGCUN_PROJECT_KEY},
    },
    {
        "api_id": "personPage",
        "path": "person/page",
        "method": "POST",
        "description": "分页获取人员库",
        "params": {"projectKey": XIANGYANGCUN_PROJECT_KEY, "pageNum": 1, "pageSize": 10},
    },
    {
        "api_id": "attendanceDay",
        "path": "report/attendance/attendanceDay",
        "method": "POST",
        "description": "作业面日考勤统计",
        "params": {"projectKey": XIANGYANGCUN_PROJECT_KEY},
    },
]

# api_id → 接口信息索引
_API_INDEX = {api["api_id"]: api for api in PERSONNEL_API_CATALOG}

# ==================== RSA 签名认证 ====================

_private_key = None


def _get_private_key():
    """加载 RSA 私钥，优先 PKCS#8，回退 PKCS#1。"""
    global _private_key
    if _private_key is not None:
        return _private_key

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend

    formats = [
        ("PKCS#8", "-----BEGIN PRIVATE KEY-----\n" + XIANGYANGCUN_PRIVATE_KEY_BASE64 + "\n-----END PRIVATE KEY-----"),
        ("PKCS#1", "-----BEGIN RSA PRIVATE KEY-----\n" + XIANGYANGCUN_PRIVATE_KEY_BASE64 + "\n-----END RSA PRIVATE KEY-----"),
    ]
    for fmt_name, pem_str in formats:
        try:
            key = serialization.load_pem_private_key(
                pem_str.encode(), password=None, backend=default_backend()
            )
            _private_key = key
            return key
        except Exception as exc:
            print(f"  [RSA] {fmt_name} 格式加载失败: {exc}")
    raise ValueError("无法加载 RSA 私钥，请检查密钥格式")


def _generate_sign(access_key: str, timestamp: str, nonce: str) -> str:
    """RSA-SHA256 签名 → Base64。"""
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


def _build_request(path: str, extra_params: dict = None) -> str:
    """构建带 RSA 签名的请求 URL。"""
    timestamp = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    raw_sign = _generate_sign(XIANGYANGCUN_ACCESS_KEY, timestamp, nonce)
    encoded_sign = quote(raw_sign, safe="")

    parts = []
    if extra_params and "projectKey" in extra_params:
        parts.append(f"projectKey={quote(str(extra_params['projectKey']), safe='')}")
    parts.append(f"accessKey={quote(XIANGYANGCUN_ACCESS_KEY, safe='')}")
    parts.append(f"timestamp={quote(timestamp, safe='')}")
    parts.append(f"nonce={quote(nonce, safe='')}")
    parts.append(f"sign={encoded_sign}")

    if extra_params:
        for key, val in extra_params.items():
            if key != "projectKey":
                parts.append(f"{key}={quote(str(val), safe='')}")

    return f"{XIANGYANGCUN_API_BASE_URL}/{path.lstrip('/')}?{'&'.join(parts)}"


def _call_api(api_info: dict, extra_params: dict = None):
    """调用人员数据接口。POST 时业务参数放 body，projectKey 留在 URL 签名中。"""
    path = api_info["path"]
    method = api_info["method"]
    base_params = dict(api_info.get("params", {}))
    body_params = {}
    if extra_params:
        body_params = dict(extra_params)
        body_params.pop("projectKey", None)

    url = _build_request(path, base_params)
    print(f"  [向阳村] 调用: [{method}] {path} | body={body_params}")

    try:
        if method == "GET":
            resp = requests.get(url, timeout=30)
        else:
            resp = requests.post(url, json=body_params, timeout=30)
        resp.raise_for_status()
        return {"success": True, "http_status": resp.status_code, "data": resp.json()}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "接口调用超时"}
    except requests.exceptions.RequestException as exc:
        return {"success": False, "error": f"接口调用失败: {exc}"}


# ==================== LLM 调用 ====================

def _safe_parse_json(raw):
    """安全解析 LLM 返回的 JSON。"""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def _llm_call(system_prompt, user_message, max_tokens=500, response_format=None):
    """同步调用 LLM，禁用 thinking 以获得直接 JSON/文本输出。"""
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "thinking": {"type": "disabled"},
    }
    if response_format:
        payload["response_format"] = response_format

    resp = requests.post(
        f"{LLM_BASE_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
        json=payload,
        timeout=LLM_TIMEOUT,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"LLM 调用失败（HTTP {resp.status_code}）")
    data = resp.json()
    message = data["choices"][0]["message"]
    content = (message.get("content") or "").strip()
    if not content:
        content = (message.get("reasoning_content") or "").strip()
    return content


def _build_catalog_text() -> str:
    """构建接口目录文本供 LLM 意图识别。"""
    lines = []
    for api in PERSONNEL_API_CATALOG:
        lines.append(f"- {api['api_id']}: {api['description']} ({api['method']})")
    return "\n".join(lines)


def llm_intent(query_text: str) -> dict:
    """LLM 识别查询意图，返回 {'api_id': ..., 'extra_params': {...}}。"""
    today = datetime.now().strftime("%Y-%m-%d")
    system_prompt = (
        "你是向阳村项目人员数据查询路由。根据用户问题选择最匹配的数据接口，只返回 JSON 对象。\n"
        'JSON格式：{"api_id":"接口ID","extra_params":{}}\n'
        "可选接口：\n"
        f"{_build_catalog_text()}\n"
        "规则：\n"
        "人数总览→personOverall；每小时人数分布→todayPersonHourStat；班组出勤→todayTeamsAtteStat；\n"
        "近七日参建方出勤→weekEnterpriseAtteStat；作业面人员列表→layerAreaPersonList；\n"
        "人员定位24H走势→snapshootProjectPersonCountV3；查某人位置→personCurLocationV2（extra_params 加 personName）；\n"
        "人员位置分布/区域分布/各区人数/在场人员分布→personCurLocationV2；\n"
        "人员库名单→personPage；日考勤→attendanceDay。\n"
        "涉及日期时在 extra_params 加 date（YYYY-MM-DD）。\n"
        f"今天是{today}。"
    )
    raw = _llm_call(
        system_prompt,
        query_text,
        max_tokens=300,
        response_format={"type": "json_object"},
    )
    parsed = _safe_parse_json(raw)
    return {
        "api_id": parsed.get("api_id"),
        "extra_params": parsed.get("extra_params") or {},
    }


def llm_summary(query_text: str, api_info: dict, raw_data, location_distribution=None) -> str:
    """LLM 对查询结果进行口语化总结。"""
    data_text = json.dumps(raw_data, ensure_ascii=False)
    if len(data_text) > 4000:
        data_text = data_text[:4000] + "...(截断)"

    if location_distribution:
        dist_lines = [
            f"{item['area_name']}: {item['total']}人（在线{item['online']}）"
            for item in location_distribution
        ]
        data_text = "人员位置分布：\n" + "\n".join(dist_lines) + "\n\n原始数据：\n" + data_text

    system_prompt = (
        "你是向阳村项目人员数据助手。根据查询结果，用中文给出简洁口语化总结。\n"
        "要求：\n"
        "1. 如果是人员位置分布查询，必须按区域逐一汇报各区人数（如「2#楼1F有19人、4F有18人」），不要只报总数、不要遗漏区域\n"
        "2. 先给结论，再列关键数字；控制在150字以内；纯文本，不使用 Markdown；不要套话。"
    )
    user_message = (
        f"用户问题：{query_text}\n"
        f"数据来源：{api_info['description']}（{api_info['api_id']}）\n"
        f"返回数据：{data_text}\n"
        "请直接输出总结文本。"
    )
    return _llm_call(system_prompt, user_message, max_tokens=500)


def _extract_location_distribution(raw_data) -> list:
    """从 personCurLocationV2 返回数据中提取按区域的人员分布。

    排除「全部」汇总行，并按总人数降序排列，确保总结时优先呈现各区域人数。
    """
    data = raw_data.get("data") if isinstance(raw_data, dict) else raw_data
    if not isinstance(data, dict):
        return []
    count_vos = data.get("stayPersonCountVos") or []
    result = []
    for vo in count_vos:
        if not isinstance(vo, dict):
            continue
        area_name = vo.get("areaName")
        if not area_name or area_name == "全部":
            continue
        result.append({
            "area_name": area_name,
            "online": int(vo.get("onlinePersonNum") or 0),
            "offline": int(vo.get("offlinePersonNum") or 0),
            "total": int(vo.get("totalPersonNum") or 0),
        })
    result.sort(key=lambda x: x["total"], reverse=True)
    return result


# ==================== 核心查询逻辑 ====================

def test_personnel_query(query_text: str, description: str = None) -> dict:
    """向阳村人员数据查询主流程：LLM 意图 → 调用接口 → LLM 总结。"""
    start_time = time.time()
    description = description or query_text

    # Step 1: LLM 意图识别
    intent_start = time.time()
    try:
        intent = llm_intent(query_text)
    except Exception as exc:
        intent = {"api_id": None, "extra_params": {}, "error": str(exc)}
    llm_intent_elapsed = round(time.time() - intent_start, 2)

    api_id = intent.get("api_id")
    api_info = _API_INDEX.get(api_id) if api_id else None

    if not api_info:
        return {
            "success": False,
            "description": description,
            "query": query_text,
            "status_code": 0,
            "elapsed_seconds": round(time.time() - start_time, 2),
            "error": f"未匹配到人员数据接口（LLM 返回 api_id={api_id}）",
            "available_apis": [a["api_id"] for a in PERSONNEL_API_CATALOG],
        }

    # Step 2: 调用数据接口
    api_result = _call_api(api_info, intent.get("extra_params"))
    if not api_result.get("success"):
        return {
            "success": False,
            "description": description,
            "query": query_text,
            "status_code": 0,
            "elapsed_seconds": round(time.time() - start_time, 2),
            "error": api_result.get("error", "接口调用失败"),
            "involved_data": {"api_id": api_id, "api_path": api_info["path"]},
        }

    # Step 3: 提取位置分布（personCurLocationV2 接口）
    location_distribution = None
    if api_id == "personCurLocationV2":
        location_distribution = _extract_location_distribution(api_result["data"])

    # Step 4: LLM 总结
    summary_start = time.time()
    summary_text = ""
    try:
        summary_text = llm_summary(query_text, api_info, api_result["data"], location_distribution)
    except Exception as exc:
        print(f"  [LLM] 总结失败: {exc}")
        summary_text = f"人员数据查询完成（接口：{api_info['description']}），但总结服务暂时不可用。"
    llm_summary_elapsed = round(time.time() - summary_start, 2)

    elapsed = round(time.time() - start_time, 2)
    return {
        "success": True,
        "description": description,
        "query": query_text,
        "status_code": api_result.get("http_status", 200),
        "elapsed_seconds": elapsed,
        "request_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_summary": summary_text,
        "返回数据总结": summary_text,
        "involved_data": {
            "api_id": api_id,
            "api_path": api_info["path"],
            "method": api_info["method"],
            "description": api_info["description"],
        },
        "raw_data": api_result.get("data"),
        "location_distribution": location_distribution,
        "llm_intent_elapsed_seconds": llm_intent_elapsed,
        "llm_summary_elapsed_seconds": llm_summary_elapsed,
    }


def get_personnel_catalog() -> list:
    """返回人员数据接口目录。"""
    return [
        {"api_id": a["api_id"], "method": a["method"], "description": a["description"]}
        for a in PERSONNEL_API_CATALOG
    ]


def llm_taji_summary(query_text: str, results: list) -> str:
    """LLM 对塔机查询结果进行口语化总结。"""
    data_text = json.dumps(results, ensure_ascii=False)
    if len(data_text) > 4000:
        data_text = data_text[:4000] + "...(截断)"

    system_prompt = (
        "你是向阳村项目塔机作业监控助手。根据查询结果，用中文给出简洁口语化总结。\n"
        "要求：先给结论，再列关键数字；控制在200字以内；纯文本，不使用 Markdown；不要套话。"
    )
    user_message = (
        f"用户问题：{query_text}\n"
        f"塔机作业数据：{data_text}\n"
        "请直接输出总结文本。"
    )
    return _llm_call(system_prompt, user_message, max_tokens=500)


def query_taji_by_nl(query_text: str, description: str = None) -> dict:
    """塔机自然语言查询：返回与人员查询一致的字段结构。"""
    start_ts = time.time()
    description = description or query_text

    # Step 1: LLM 解析意图
    intent_start = time.time()
    parsed = {"device_name": None, "start_time": None, "end_time": None}
    llm_error = None
    try:
        parsed = llm_parse_query(query_text)
    except Exception as exc:
        llm_error = str(exc)
        print(f"  [塔机] LLM 解析失败，降级为查询全部塔机当天数据: {exc}")
    llm_intent_elapsed = round(time.time() - intent_start, 2)

    device_name = parsed.get("device_name")
    start_time = parsed.get("start_time")
    end_time = parsed.get("end_time")

    if device_name:
        try:
            results = [query_tower_crane_work_status(device_name, start_time, end_time)]
        except Exception as exc:
            results = [{"device_name": device_name, "error": str(exc)}]
    else:
        results = [
            crane_status_summary(item)
            for item in query_all_cranes(start_time, end_time)
        ]

    # Step 2: LLM 总结
    summary_start = time.time()
    summary_text = ""
    try:
        summary_text = llm_taji_summary(query_text, results)
    except Exception as exc:
        print(f"  [LLM] 塔机总结失败: {exc}")
        summary_text = "塔机作业状态查询完成，但总结服务暂时不可用。"
    llm_summary_elapsed = round(time.time() - summary_start, 2)

    elapsed = round(time.time() - start_ts, 2)
    return {
        "success": True,
        "description": description,
        "query": query_text,
        "status_code": 200,
        "elapsed_seconds": elapsed,
        "request_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_summary": summary_text,
        "返回数据总结": summary_text,
        "involved_data": {
            "api_id": "towerCraneWorkStatus",
            "api_path": "towercranedataservice/getWorkCycleInfoHis",
            "method": "POST",
            "description": "塔机历史作业状态",
        },
        "raw_data": results,
        "parsed_intent": {
            "device_name": device_name,
            "start_time": start_time,
            "end_time": end_time,
        },
        "llm_error": llm_error,
        "llm_intent_elapsed_seconds": llm_intent_elapsed,
        "llm_summary_elapsed_seconds": llm_summary_elapsed,
    }


# ==================== HTTP 处理器 ====================

class XiangyangcunHandler(BaseHTTPRequestHandler):
    """向阳村人员数据查询测试服务 HTTP 处理器"""

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        print(f"[HTTP] {self.client_address[0]} - {format % args}")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _send_html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"请求体不是有效 JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_test_page()
        elif path == "/xiangyangcun/status":
            self._send_json({
                "status": "ok",
                "project": "向阳村",
                "project_key": XIANGYANGCUN_PROJECT_KEY,
                "tower_crane_devices": list(TOWER_CRANE_NAME_TO_SN),
                "available_apis": get_personnel_catalog(),
                "timestamp": datetime.now().isoformat(),
            })
        elif path == "/xiangyangcun/catalog":
            self._send_json({
                "success": True,
                "catalog": {
                    "tower_crane": {
                        "devices": list(TOWER_CRANE_NAME_TO_SN),
                        "endpoints": [
                            {"method": "POST", "path": "/xiangyangcun/taji/nl-query"},
                        ],
                    },
                    "personnel": {
                        "apis": get_personnel_catalog(),
                        "endpoints": [
                            {"method": "POST", "path": "/xiangyangcun/personnel/query"},
                        ],
                    },
                },
            })
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/xiangyangcun/personnel/query":
            self._handle_query()
        elif path == "/xiangyangcun/taji/nl-query":
            self._handle_taji_nl()
        else:
            self._send_json({"error": "Not Found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle_query(self):
        try:
            body = self._read_body()
            query_text = (body.get("query") or body.get("text") or "").strip()
            if not query_text:
                self._send_json({"error": "请提供 query 字段"}, 400)
                return
            description = body.get("description") or query_text
            print(f"\n  向阳村人员查询: {query_text}")
            result = test_personnel_query(query_text, description)
            self._send_json(result)
        except ValueError as exc:
            self._send_json({"success": False, "error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc)}, 500)

    def _handle_taji_nl(self):
        """塔机自然语言查询。"""
        try:
            body = self._read_body()
            query_text = (body.get("query") or body.get("text") or "").strip()
            if not query_text:
                self._send_json({"error": "请提供 query 字段（自然语言查询）"}, 400)
                return
            description = body.get("description") or query_text
            print(f"\n  塔机查询: {query_text}")
            self._send_json(query_taji_by_nl(query_text, description))
        except ValueError as exc:
            self._send_json({"success": False, "error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"success": False, "error": str(exc)}, 500)

    def _serve_test_page(self):
        html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>向阳村人员数据查询测试</title>
<style>
body { font-family: -apple-system, "PingFang SC", sans-serif; background:#f0f4f8; margin:0; padding:24px; }
h1 { font-size:20px; color:#0d47a1; }
.card { background:#fff; border-radius:12px; padding:20px; margin:16px 0; box-shadow:0 2px 12px rgba(0,0,0,0.06); }
input { padding:10px 14px; border:2px solid #e0e0e0; border-radius:8px; font-size:14px; margin:4px; width:70%; }
button { padding:10px 20px; background:#1a73e8; color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:14px; }
pre { background:#f6f8fa; padding:14px; border-radius:8px; white-space:pre-wrap; font-size:13px; max-height:500px; overflow:auto; }
</style>
</head>
<body>
<h1>🏗️ 向阳村项目统一数据查询测试服务</h1>
<div class="card">
    <h2>🏗️ 塔机作业查询（自然语言）</h2>
    <input id="taji" placeholder="例：查询所有塔机当前状态 / 4#塔机6月20日干了多少活" value="查询所有塔机当前状态">
    <button onclick="query('/xiangyangcun/taji/nl-query', 'taji')">查询</button>
</div>
<div class="card">
    <h2>👷 人员数据查询（自然语言）</h2>
    <input id="nl" placeholder="例：查询今天人员总览 / 今天班组出勤情况 / 查询在场人员的位置分布">
    <button onclick="query('/xiangyangcun/personnel/query', 'nl')">查询</button>
</div>
<div class="card">
    <pre id="result">等待查询...</pre>
</div>
<script>
async function query(url, inputId) {
    const result = document.getElementById('result');
    result.textContent = 'LLM 解析与查询中...';
    try {
        const resp = await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query: document.getElementById(inputId).value.trim()}),
        });
        result.textContent = JSON.stringify(await resp.json(), null, 2);
    } catch (e) {
        result.textContent = '请求失败: ' + e.message;
    }
}
</script>
</body>
</html>"""
        self._send_html(html)


# ==================== 启动入口 ====================

def main():
    print("=" * 60)
    print("  向阳村项目统一数据查询测试服务")
    print("=" * 60)
    print(f"  项目: 向阳村 (ProjectKey={XIANGYANGCUN_PROJECT_KEY})")
    print(f"  塔机设备: {', '.join(TOWER_CRANE_NAME_TO_SN)}")
    print(f"  人员接口: {len(PERSONNEL_API_CATALOG)} 个")
    print(f"  服务地址: http://127.0.0.1:{SERVER_PORT}")
    print(f"  人员查询: POST /xiangyangcun/personnel/query")
    print(f"  塔机查询: POST /xiangyangcun/taji/nl-query")
    print(f"  接口目录: GET  /xiangyangcun/catalog")
    print("  按 Ctrl+C 停止服务")

    server = HTTPServer(("0.0.0.0", SERVER_PORT), XiangyangcunHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
