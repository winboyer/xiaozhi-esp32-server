"""向阳村项目人员数据查询 - 通过工地安全数据平台查询向阳村项目的人员数据

流程：用户自然语言 → LLM 意图分析选择接口 → RSA 签名调用数据平台 → 返回结构化数据
（框架随后用技能 SUMMARY_PROMPT 做总结并 TTS 播报）
"""

import base64
import json
import hashlib
import re
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Dict, Any, Optional

import requests

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# 注册技能提示
from plugins_func.skills.xiangyangcun_personnel_skill import register_xiangyangcun_personnel_skill

register_xiangyangcun_personnel_skill()

TAG = __name__
logger = setup_logging()

# ==================== 向阳村项目数据平台配置（RSA 签名） ====================
XIANGYANGCUN_BASE_URL = "https://dw.yzw.cn/open"
XIANGYANGCUN_ACCESS_KEY = "be69162bdd4e46619ac95824a88b1ec2"
XIANGYANGCUN_PROJECT_KEY = "b35df2e91ed642c595ca96d0bc2d9ed9"
XIANGYANGCUN_PRIVATE_KEY_BASE64 = (
    "MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGBAMjBwnRaM3p+uDJQ0WsESmaOIbgNOtvkIMacRuJK+okoIqJFeWQhjPvimnTaQdvHFuYemaLllkH5tWNTlxM4cwSDw7OISc/2wGcfn8jX+QWu46MohsfNGudBG+/izia3I3QtwZmlSDBRjOYK2KbmO853zMxZnyj2b5lLCo/nixnjAgMBAAECgYAPbPf2MCu7DCHQiyFneDDUhYC1kp3eevGolFlL/QsYK+A3y/loxlbKnSq7sz0scbVJB4cYzn+HrUDEE46AGK4zQt5B4EAqtDsyC0Lwjpo2O4ObrLPeSN+CehUZ4fnXqnPq+/+vwjflzysYPh8ij7FYGOhme2QpPgBlVNX9zYlQgQJBAOMFE3jN2WazdXZfmfQIJPjC6F0fIEhXgSyhqpxeB5iMOyu5jmI2HhMVmqUogvj3WNjwxeuO87DpoMDehoBBQIECQQDiYmt9UMEEIw3ko6zklUM6KOJuf4CuniCplW9B7W14QgSYF/fjQ+5J6MHSPIR5n4JSc5ih72qgfobSHtj+uyhjAkB8iLlQyKNcyk9CW1lJ2/nkGI99HekIpi/vOtQrqQ1DqpF+//BSgdtnnq9RsHKAfrdXcmUwPiACSXbstmVUD/eBAkBHNPnmcu4jZPtLvYf2ZlS9CHsgko5hXm+bp9tU+1+BghJ73J4mKAndyY6dmFd7Agc19BJAbVQ2o1W45ecPSMNNAkEAmxqzT4nt0pujXBP5XsLuta0WT9XszMNC1yJef1kcTCMHQGntmNHhD/oOheGyFGc+hOB6AfZbAim9GyCgBxQDMQ=="
)

# ==================== 人员数据接口目录 ====================

XIANGYANGCUN_PERSONNEL_CATALOG = [
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

_API_INDEX = {api["api_id"]: api for api in XIANGYANGCUN_PERSONNEL_CATALOG}

# 内部意图缓存 (TTL=60s)
_intent_cache = {}


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
            logger.bind(tag=TAG).warning(f"{fmt_name} 格式加载失败: {exc}")
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
    encoded_sign = re.sub(r"[+]", "%2B", raw_sign)
    encoded_sign = re.sub(r"/", "%2F", encoded_sign)
    encoded_sign = re.sub(r"=", "%3D", encoded_sign)

    parts = []
    if extra_params and "projectKey" in extra_params:
        parts.append(f"projectKey={extra_params['projectKey']}")
    parts.append(f"accessKey={XIANGYANGCUN_ACCESS_KEY}")
    parts.append(f"timestamp={timestamp}")
    parts.append(f"nonce={nonce}")
    parts.append(f"sign={encoded_sign}")

    if extra_params:
        for key, val in extra_params.items():
            if key != "projectKey":
                from urllib.parse import quote as _quote
                parts.append(f"{key}={_quote(str(val), safe='')}")

    return f"{XIANGYANGCUN_BASE_URL}/{path.lstrip('/')}?{'&'.join(parts)}"


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
    logger.bind(tag=TAG).info(f"调用向阳村人员接口: [{method}] {path}")

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


# ==================== LLM 意图分析 ====================

def _build_catalog_text() -> str:
    """构建接口目录文本供 LLM 意图识别。"""
    lines = []
    for api in XIANGYANGCUN_PERSONNEL_CATALOG:
        lines.append(f"- {api['api_id']}: {api['description']} ({api['method']})")
    return "\n".join(lines)


def _build_intent_prompt(user_query: str) -> str:
    """构建意图分析系统提示词。"""
    return (
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
        f"今天是{datetime.now().strftime('%Y-%m-%d')}。"
    )


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


# ==================== 注册函数 ====================

XIANGYANGCUN_PERSONNEL_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "query_xiangyangcun_personnel",
        "description": (
            "查询向阳村项目的人员数据。"
            "当用户询问「人员总览」「在场人数」「班组出勤」「人员定位」「人员位置分布」"
            "「考勤统计」「人员库」「作业面人员」等向阳村项目人员相关问题时调用此函数。"
            "只需用自然语言描述查询内容，本工具自动分析意图并返回结构化结果。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户自然语言查询，如：查询今天人员总览、班组出勤情况、人员位置分布、考勤统计等",
                },
            },
            "required": ["query"],
        },
    },
}


@register_function("query_xiangyangcun_personnel", XIANGYANGCUN_PERSONNEL_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def query_xiangyangcun_personnel(
    conn: "ConnectionHandler",
    query: str = None,
):
    """查询向阳村项目人员数据

    流程：用户输入 → LLM 意图分析 → 调用对应数据接口 → 返回结构化数据（框架做总结播报）
    """
    if not query:
        return ActionResponse(
            Action.RESPONSE,
            response="请提供查询内容，例如：查询今天人员总览。",
        )

    # ---- Step 1: LLM 意图分析 ----
    intent_prompt = _build_intent_prompt(query)
    try:
        intent_llm = getattr(conn.intent, "llm", None)
        if intent_llm is None:
            return ActionResponse(
                Action.RESPONSE,
                response="LLM 服务未就绪，无法进行人员数据查询。",
            )

        cache_key = hashlib.md5(query.encode()).hexdigest()
        cached = _intent_cache.get(cache_key)
        if cached and cached.get("expires_at", 0) > time.time():
            intent_raw = cached["result"]
        else:
            intent_raw = intent_llm.response_no_stream(
                system_prompt=intent_prompt,
                user_prompt=query,
                max_tokens=200,
            )
            _intent_cache[cache_key] = {"result": intent_raw, "expires_at": time.time() + 60}

        intent_raw = (intent_raw or "").strip()
        match = re.search(r"\{.*\}", intent_raw, re.DOTALL)
        if match:
            intent_raw = match.group(0)
        intent_result = json.loads(intent_raw)
        logger.bind(tag=TAG).info(f"意图分析结果: {intent_result}")
    except Exception as exc:
        logger.bind(tag=TAG).error(f"意图分析失败: {exc}")
        return ActionResponse(
            Action.RESPONSE,
            response="意图分析失败，请重新描述查询内容。",
        )

    # ---- Step 2: 匹配接口 ----
    api_id = intent_result.get("api_id", "")
    api_info = _API_INDEX.get(api_id)
    if api_info is None:
        logger.bind(tag=TAG).warning(f"未匹配到人员数据接口, api_id={api_id}, query={query}")
        return ActionResponse(
            Action.RESPONSE,
            response="暂时无法查询相关的人员数据。",
        )

    extra_params = intent_result.get("extra_params", {}) or {}
    api_path = api_info["path"]

    # 日期参数规范化
    if "date" in extra_params:
        date_val = extra_params.pop("date")
        if "snapshoot" in api_path:
            extra_params["startDate"] = f"{date_val} 00:00:00"
            extra_params["endDate"] = f"{date_val} 23:59:59"
        elif "attendance" in api_path:
            extra_params["date"] = date_val
    if "snapshoot" in api_path and "startDate" not in extra_params:
        today = datetime.now().strftime("%Y-%m-%d")
        extra_params["startDate"] = f"{today} 00:00:00"
        extra_params["endDate"] = f"{today} 23:59:59"
    if "attendance" in api_path and "date" not in extra_params:
        extra_params["date"] = datetime.now().strftime("%Y-%m-%d")

    # ---- Step 3: 调用数据接口 ----
    api_result = _call_api(api_info, extra_params)
    if not api_result.get("success"):
        logger.bind(tag=TAG).error(f"接口调用失败: {api_result.get('error')}")
        return ActionResponse(
            Action.RESPONSE,
            response=f"人员数据查询失败：{api_result.get('error', '接口调用失败')}",
        )

    # ---- Step 4: 提取位置分布（personCurLocationV2 接口） ----
    raw_data = api_result.get("data")
    location_distribution = None
    if api_id == "personCurLocationV2":
        location_distribution = _extract_location_distribution(raw_data)

    # ---- Step 5: 组装结构化数据供框架总结 ----
    if location_distribution:
        # 位置分布查询：只保留区域分布，避免大段原始人员列表干扰总结
        result_payload = {
            "query_type": "向阳村人员数据",
            "api_id": api_id,
            "api_description": api_info["description"],
            "location_distribution": location_distribution,
        }
    else:
        result_payload = {
            "query_type": "向阳村人员数据",
            "api_id": api_id,
            "api_description": api_info["description"],
            "data": raw_data,
        }

    raw_json = json.dumps(result_payload, ensure_ascii=False, indent=2)
    return ActionResponse(Action.REQLLM, result=raw_json, response=None)
