"""工地安全数据智能查询 - 基于 LLM 意图分析 + 数据接口调用 + 智能总结

接受用户自然语言查询请求，通过 LLM 分析意图、调用对应的工地安全数据接口，
再利用 LLM 对返回结果进行总结，最终输出结构化 JSON。
"""

import base64
import json
import hashlib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

# 内部意图缓存 (TTL=60s，避免相同query重复调用LLM)
_intent_cache = {}
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from core.project_config import get_staff_safe_api_ids
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# 注册技能提示
from plugins_func.skills.staff_safe_skill import register_staff_safe_skill

register_staff_safe_skill()

TAG = __name__
logger = setup_logging()

# ==================== API 配置 ====================
STAFF_SAFE_BASE_URL = "https://dw.yzw.cn/open"
STAFF_SAFE_ACCESS_KEY = "be69162bdd4e46619ac95824a88b1ec2"
STAFF_SAFE_PROJECT_KEY = "e3ae0e4a0ab6478da33bce089237a9ed"
STAFF_SAFE_PRIVATE_KEY_BASE64 = (
    "MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGBAMjBwnRaM3p+uDJQ0WsESmaOIbgNOtvkIMacRuJK+okoIqJFeWQhjPvimnTaQdvHFuYemaLllkH5tWNTlxM4cwSDw7OISc/2wGcfn8jX+QWu46MohsfNGudBG+/izia3I3QtwZmlSDBRjOYK2KbmO853zMxZnyj2b5lLCo/nixnjAgMBAAECgYAPbPf2MCu7DCHQiyFneDDUhYC1kp3eevGolFlL/QsYK+A3y/loxlbKnSq7sz0scbVJB4cYzn+HrUDEE46AGK4zQt5B4EAqtDsyC0Lwjpo2O4ObrLPeSN+CehUZ4fnXqnPq+/+vwjflzysYPh8ij7FYGOhme2QpPgBlVNX9zYlQgQJBAOMFE3jN2WazdXZfmfQIJPjC6F0fIEhXgSyhqpxeB5iMOyu5jmI2HhMVmqUogvj3WNjwxeuO87DpoMDehoBBQIECQQDiYmt9UMEEIw3ko6zklUM6KOJuf4CuniCplW9B7W14QgSYF/fjQ+5J6MHSPIR5n4JSc5ih72qgfobSHtj+uyhjAkB8iLlQyKNcyk9CW1lJ2/nkGI99HekIpi/vOtQrqQ1DqpF+//BSgdtnnq9RsHKAfrdXcmUwPiACSXbstmVUD/eBAkBHNPnmcu4jZPtLvYf2ZlS9CHsgko5hXm+bp9tU+1+BghJ73J4mKAndyY6dmFd7Agc19BJAbVQ2o1W45ecPSMNNAkEAmxqzT4nt0pujXBP5XsLuta0WT9XszMNC1yJef1kcTCMHQGntmNHhD/oOheGyFGc+hOB6AfZbAim9GyCgBxQDMQ=="
)

# 私钥缓存
_private_key = None


def _get_private_key():
    """加载 RSA 私钥"""
    global _private_key
    if _private_key is not None:
        return _private_key

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend

    # PKCS#8 优先：当前私钥为 PKCS#8 格式，先试 PKCS#8 可避免 PKCS#1 的无意义 WARNING
    # 同时保留 PKCS#1 作为兜底，兼容其他格式的私钥
    formats = [
        ("PKCS#8", "-----BEGIN PRIVATE KEY-----\n" + STAFF_SAFE_PRIVATE_KEY_BASE64 + "\n-----END PRIVATE KEY-----"),
        ("PKCS#1", "-----BEGIN RSA PRIVATE KEY-----\n" + STAFF_SAFE_PRIVATE_KEY_BASE64 + "\n-----END RSA PRIVATE KEY-----"),
    ]

    for fmt_name, pem_str in formats:
        try:
            key = serialization.load_pem_private_key(
                pem_str.encode(), password=None, backend=default_backend()
            )
            logger.bind(tag=TAG).info(f"RSA 私钥加载成功 (格式: {fmt_name})")
            _private_key = key
            return key
        except Exception as e:
            logger.bind(tag=TAG).warning(f"{fmt_name} 格式加载失败: {e}")

    raise ValueError("无法加载 RSA 私钥，请检查密钥格式")


def _generate_sign(access_key: str, timestamp: str, nonce: str) -> str:
    """生成 RSA-SHA256 签名"""
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
    """构建带 RSA 签名的请求 URL"""
    timestamp = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    raw_sign = _generate_sign(STAFF_SAFE_ACCESS_KEY, timestamp, nonce)
    encoded_sign = quote(raw_sign, safe="")

    parts = []
    # projectKey 放最前面
    if extra_params and "projectKey" in extra_params:
        parts.append(f"projectKey={quote(str(extra_params['projectKey']), safe='')}")

    parts.append(f"accessKey={quote(STAFF_SAFE_ACCESS_KEY, safe='')}")
    parts.append(f"timestamp={quote(timestamp, safe='')}")
    parts.append(f"nonce={quote(nonce, safe='')}")
    parts.append(f"sign={encoded_sign}")

    if extra_params:
        for key, val in extra_params.items():
            if key != "projectKey":
                parts.append(f"{key}={quote(str(val), safe='')}")

    full_url = f"{STAFF_SAFE_BASE_URL}/{path.lstrip('/')}?{'&'.join(parts)}"
    return full_url


# ==================== 接口目录定义 ====================
# 每个接口包含：path, method, description, params(可选固定参数), is_post_body(是否POST body传参)
API_CATALOG = [
    # ---- 大屏相关 ----
    {
        "api_id": "personOverall",
        "path": "bigScreen/BigsHome/personOverall",
        "method": "GET",
        "category": "大屏-首页",
        "description": "首页人数总览",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["人数总览", "首页人数", "人员概览", "人数概览"],
    },
    {
        "api_id": "todayPersonHourStat",
        "path": "bigScreen/BigsHome/todayPersonHourStat",
        "method": "GET",
        "category": "大屏-首页",
        "description": "当天人员时间分布（每小时统计）",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["人员时间分布", "每小时人数", "人员时段", "分时统计"],
    },
    {
        "api_id": "todayTeamsAtteStat",
        "path": "bigScreen/BigsHome/todayTeamsAtteStat",
        "method": "GET",
        "category": "大屏-首页",
        "description": "今日班组出勤情况",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["班组出勤", "班组出勤情况", "班组考勤", "今日班组出勤"],
    },
    {
        "api_id": "weekEnterpriseAtteStat",
        "path": "bigScreen/BigsHome/weekEnterpriseAtteStat",
        "method": "GET",
        "category": "大屏-首页",
        "description": "近七日参建方人员出勤情况",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["参建方出勤", "近七日", "企业出勤", "施工单位出勤"],
    },
    {
        "api_id": "getAlarmRecord",
        "path": "bigScreen/bigAlarm/getAlarmRecord",
        "method": "GET",
        "category": "大屏-告警",
        "description": "分页获取告警记录",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY, "pageNum": 1, "pageSize": 50},
        "keywords": ["告警记录", "告警列表", "报警记录", "预警记录"],
    },
    {
        "api_id": "getMonthRecordSubType",
        "path": "bigScreen/bigAlarm/getMonthRecordSubType",
        "method": "GET",
        "category": "大屏-告警",
        "description": "近三十天预警类型分析",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["预警类型", "告警类型", "报警分类", "告警分析"],
    },
    {
        "api_id": "getMonthRecordStatus",
        "path": "bigScreen/bigAlarm/getMonthRecordStatus",
        "method": "GET",
        "category": "大屏-告警",
        "description": "近三十日报警处理情况",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["报警处理", "告警处理", "处理情况"],
    },
    {
        "api_id": "getMonthEnterpriseRecordNum",
        "path": "bigScreen/bigAlarm/getMonthEnterpriseRecordNum",
        "method": "GET",
        "category": "大屏-告警",
        "description": "近三十天参建公司下班组告警数量",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["公司告警", "企业告警数量", "参建公司告警"],
    },
    {
        "api_id": "getMonthOrganRecordNum",
        "path": "bigScreen/bigAlarm/getMonthOrganRecordNum",
        "method": "GET",
        "category": "大屏-告警",
        "description": "近三十天班组各告警数量",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["班组告警", "班组预警数量"],
    },
    {
        "api_id": "layerAreaPersonList",
        "path": "bigScreen/BigsLayer/layerAreaPersonList",
        "method": "GET",
        "category": "大屏-作业面",
        "description": "作业面人员列表",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["作业面人员", "分层人员", "区域人员"],
    },
    # ---- 定位相关 ----
    {
        "api_id": "snapshootProjectPersonCountV3",
        "path": "location/snapshootProjectPersonCountV3",
        "method": "POST",
        "category": "定位",
        "description": "今日人员定位-24H走势图（每分钟人数）",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["定位走势", "24小时走势", "人员定位趋势", "人数走势"],
    },
    {
        "api_id": "personCurLocationV2",
        "path": "location/personCurLocation/v2",
        "method": "POST",
        "category": "定位",
        "description": "今日人员定位-人员列表（支持按姓名查询人员所在位置）",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["人员定位", "当前位置", "实时定位", "人员列表", "在哪里", "位置查询", "查位置", "定位查询", "找人员"],
    },
    {
        "api_id": "track",
        "path": "location/track",
        "method": "POST",
        "category": "定位",
        "description": "人员轨迹查询",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["人员轨迹", "轨迹查询", "行动轨迹"],
    },
    # ---- 设备/物资 ----
    {
        "api_id": "gatewayPageByProjectId",
        "path": "device/gateway/pageByProjectId",
        "method": "GET",
        "category": "设备",
        "description": "基站物资信息",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["基站", "物资信息", "基站物资"],
    },
    {
        "api_id": "assetQuantityStatistics",
        "path": "asset/quantityStatistics",
        "method": "GET",
        "category": "设备",
        "description": "设备信息统计",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["设备统计", "资产统计", "设备数量"],
    },
    {
        "api_id": "gatewayPage",
        "path": "device/gateway/page",
        "method": "GET",
        "category": "设备",
        "description": "主基站信息（分页）",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY, "pageNum": 1, "pageSize": 10},
        "keywords": ["主基站", "基站信息", "网关信息"],
    },
    {
        "api_id": "labelPage",
        "path": "device/label/page",
        "method": "POST",
        "category": "设备",
        "description": "标签信息（分页）",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY, "pageNum": 1, "pageSize": 10},
        "keywords": ["标签信息", "设备标签"],
    },
    # ---- 人员/项目 ----
    {
        "api_id": "personPage",
        "path": "person/page",
        "method": "POST",
        "category": "人员",
        "description": "分页获取人员库",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY, "pageNum": 1, "pageSize": 10},
        "keywords": ["人员库", "人员名单", "人员信息"],
    },
    # ---- 组织架构 ----
    {
        "api_id": "organTree",
        "path": "organ/tree",
        "method": "GET",
        "category": "组织",
        "description": "获取参建公司及其班组架构",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["组织架构", "参建公司", "班组架构", "公司班组"],
    },
    # ---- 统计相关 ----
    {
        "api_id": "attendanceDay",
        "path": "report/attendance/attendanceDay",
        "method": "POST",
        "category": "统计",
        "description": "作业面日考勤统计",
        "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
        "keywords": ["考勤统计", "日考勤", "考勤数据", "出勤统计"],
    },
]


# ==================== 非工地数据关键词预过滤 ====================
# 当用户查询命中的这些关键词时，直接判定为不在工地安全数据范畴内，不再调用接口
_NON_STAFF_KEYWORDS = [
    "天气", "下雨", "温度", "气温", "晴天", "阴天", "多云", "刮风", "台风",
    "暴雨", "下雪", "雾霾", "冷不冷", "热不热", "会不会下雨", "天气预报",
    "新闻", "头条", "热搜", "时事", "快讯", "要闻",
    "音乐", "唱歌", "歌曲", "播放", "来一首", "听歌",
    "电影", "电视剧", "综艺", "娱乐",
    "股票", "财经", "汇率", "基金",
    "笑话", "故事", "谜语", "游戏",
    "菜谱", "做饭", "烹饪", "美食",
]


def _is_non_staff_query(query: str) -> bool:
    """检查查询是否为非工地安全数据相关的内容"""
    if not query:
        return False
    text_lower = query.lower()
    return any(kw in text_lower for kw in _NON_STAFF_KEYWORDS)


# ==================== LLM 意图分析提示词 ====================

def _get_filtered_api_catalog(conn: "ConnectionHandler") -> list:
    """根据当前连接的项目配置，过滤 API_CATALOG
    
    三元里项目：仅暴露人员状态、定位、班组、考勤等接口
    将军祠项目：仅暴露告警、设备、物资等接口
    无项目：返回空列表（不进行数据接口调用）
    """
    project = conn.config.get("project")
    allowed_ids = get_staff_safe_api_ids(project)
    
    if not allowed_ids:
        # 无项目或无匹配：不暴露任何 API
        return []
    
    filtered = [api for api in API_CATALOG if api["api_id"] in allowed_ids]
    logger.bind(tag=TAG).info(
        f"项目 API 过滤: project={project.value if project else 'None'}, "
        f"可用接口 {len(filtered)}/{len(API_CATALOG)}"
    )
    return filtered


def _build_intent_prompt(user_query: str, api_catalog: list = None) -> str:
    """构建意图分析系统提示词，让 LLM 选择最匹配的接口
    
    Args:
        user_query: 用户查询文本
        api_catalog: 过滤后的 API 目录，None 时使用完整 API_CATALOG
    """
    if api_catalog is None:
        api_catalog = API_CATALOG
    
    # 如果没有可用接口，返回提示 LLM 拒绝的 prompt
    if not api_catalog:
        return (
            "你是工地安全数据查询助手。当前项目未配置任何数据接口，"
            "对于任何数据查询请求，请返回 {\"api_id\": \"none\", \"reason\": \"无可用数据接口\"}。"
            f"\n\n用户查询：{user_query}\n请返回 JSON："
        )
    
    catalog_lines = []
    for i, api in enumerate(api_catalog):
        catalog_lines.append(
            f"{i}. [{api['api_id']}] ({api['method']} {api['category']}) {api['description']}"
        )

    catalog_text = "\n".join(catalog_lines)

    prompt = f"""你是一个工地安全数据查询的意图分析助手。根据用户查询，从以下接口目录中选择最匹配的接口。

【可用接口目录】
{catalog_text}

【任务】选最匹配接口，返回JSON含api_id/reason/extra_params。今天是{datetime.now().strftime('%Y-%m-%d %H:%M')}。

【规则】问"xxx在哪里"→api_id=personCurLocationV2,extra_params加personName。考勤统计→attendanceDay，班组出勤→todayTeamsAtteStat。涉及日期加date(YYYY-MM-DD)。

【重要】如果用户查询的是天气、新闻、音乐、娱乐等与工地安全数据完全无关的内容，请返回：
{{"api_id": "none", "reason": "查询内容不在工地安全数据范畴内"}}

【输出格式】
必须只返回纯 JSON，不要任何其他文字：
{{
    "api_id": "接口ID（无匹配时为 none）",
    "reason": "选择原因",
    "extra_params": {{}}
}}

用户查询：{user_query}
请返回 JSON："""
    return prompt


def _build_summary_prompt(api_description: str, api_data: str, user_query: str, api_category: str) -> str:
    """构建数据总结提示词"""
    # attendanceDay 考勤统计接口：强调关键字段
    extra_requirements = ""
    if "attendanceDay" in api_description or "考勤" in api_description:
        extra_requirements = """
7. 【考勤统计特别要求】每条记录仅包含以下字段，请直接使用：
   - personName: 人员姓名
   - orgName: 公司/参建方名称
   - totalStayTime.hours: 总停留时长（小时，保留1位小数）
   - totalStayTime.seconds: 总停留时长（秒，原始值）
   请在总结中按公司（使用 orgName）统计出勤人数、总停留时长，并列出当天出勤人员的姓名和停留时间。
   注意：数据中不存在 personId、orgId、platformPersonId 等 ID 字段，请勿编造或引用这些字段。
"""

    prompt = f"""你是一个工地安全数据智能分析助手。请根据以下接口返回的数据，对用户查询进行总结。

【查询接口】{api_description}（{api_category}）
【用户查询】{user_query}
【返回数据】
{api_data}

【要求】用口语总结关键数字，50-150字，纯文本，不套话{extra_requirements}

请直接返回总结文本："""
    return prompt


# ==================== 核心查询逻辑 ====================

def _call_api(api_info: dict, extra_params: dict = None) -> Dict[str, Any]:
    """调用工地安全数据接口
    
    对于 POST 请求，auth 参数（projectKey）放在 URL 中，
    业务参数（startDate/endDate 等）放在 JSON body 中，避免重复发送导致 500 错误。
    """
    path = api_info["path"]
    method = api_info["method"]
    base_params = dict(api_info.get("params", {}))
    body_params = {}
    
    if extra_params:
        # projectKey 留在 URL 参数中，其余的业务参数放到 body
        body_params = dict(extra_params)
        # projectKey 不应该出现在 body 中（已在 URL 签名中）
        body_params.pop("projectKey", None)

    url = _build_request(path, base_params)

    logger.bind(tag=TAG).info(
        f"调用接口: [{method}] {path} | URL参数: {base_params} | Body参数: {body_params}"
    )

    try:
        if method == "GET":
            resp = requests.get(url, timeout=30)
        else:
            resp = requests.post(url, json=body_params, timeout=30)

        resp.raise_for_status()
        data = resp.json()
        return {
            "success": True,
            "http_status": resp.status_code,
            "elapsed": round(resp.elapsed.total_seconds(), 2),
            "data": data,
        }
    except requests.exceptions.Timeout:
        logger.bind(tag=TAG).error(f"接口超时: {path}")
        return {"success": False, "error": "接口调用超时"}
    except requests.exceptions.RequestException as e:
        logger.bind(tag=TAG).error(f"接口请求失败: {path} | {e}")
        return {"success": False, "error": f"接口调用失败: {str(e)}"}
    except Exception as e:
        logger.bind(tag=TAG).error(f"接口异常: {path} | {e}")
        return {"success": False, "error": f"未知错误: {str(e)}"}


def _select_api_by_intent(intent_result: dict) -> Optional[dict]:
    """根据意图分析结果选择对应的 API
    
    支持两种匹配方式：
    1. 精确匹配 api_id（如 "todayTeamsAtteStat"）
    2. 数字索引回退（如 LLM 返回 "2" 时按列表索引查找）
    
    返回 None 表示无法匹配（包括 LLM 明确返回 api_id="none"）
    """
    api_id = intent_result.get("api_id", "")
    # LLM 明确标记为无匹配
    if api_id == "none":
        logger.bind(tag=TAG).info(f"LLM 判定查询不在工地安全数据范畴内, reason={intent_result.get('reason', '')}")
        return None
    # 方式 1: 精确匹配
    for api in API_CATALOG:
        if api["api_id"] == api_id:
            return api
    # 方式 2: 数字索引回退（LLM 可能返回列表编号而不是标识符）
    try:
        idx = int(api_id)
        if 0 <= idx < len(API_CATALOG):
            logger.bind(tag=TAG).warning(
                f"LLM 返回了数字索引 {idx} 而非 API 标识符，已自动回退匹配: {API_CATALOG[idx]['api_id']}"
            )
            return API_CATALOG[idx]
    except (ValueError, TypeError):
        pass
    return None


def _truncate_data(data: Any, max_chars: int = 5000) -> str:
    """截断过长数据"""
    data_str = json.dumps(data, ensure_ascii=False, indent=2)
    if len(data_str) > max_chars:
        return data_str[:max_chars] + "\n\n... (数据过长，已截断)"
    return data_str


def _find_person_location(api_data: dict, person_name: str) -> Optional[str]:
    """从 personCurLocationV2 返回数据中查找指定人员所在位置
    
    解析 data.stayPersonPageVos 列表，按 personName 匹配，
    返回 cadName 字段（人员所在位置/作业面名称）。
    
    Args:
        api_data: _call_api 返回的完整接口数据
        person_name: 要查找的人员姓名
        
    Returns:
        人员所在位置名称，如未找到则返回 None
    """
    if not api_data or not person_name:
        return None
    
    # 提取 data 层
    data = api_data.get("data", {}) if isinstance(api_data, dict) else {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
    
    # 从 stayPersonPageVos 中查找
    page_vos = data.get("stayPersonPageVos", [])
    if not isinstance(page_vos, list):
        return None
    
    # 精确匹配 + 模糊匹配
    for record in page_vos:
        if not isinstance(record, dict):
            continue
        record_name = record.get("personName", "")
        if record_name == person_name:
            location = record.get("gatewayPositionName", "") or record.get("cadName", "")
            logger.bind(tag=TAG).info(f"人员位置查询成功: {person_name} → {location}")
            return location
    
    # 模糊匹配（包含关系）
    for record in page_vos:
        if not isinstance(record, dict):
            continue
        record_name = record.get("personName", "")
        if person_name in record_name or record_name in person_name:
            location = record.get("gatewayPositionName", "") or record.get("cadName", "")
            logger.bind(tag=TAG).info(f"人员位置查询(模糊)成功: {record_name}({person_name}) → {location}")
            return location
    
    logger.bind(tag=TAG).warning(f"人员位置查询未找到: {person_name}")
    return None


# ==================== 注册函数 ====================

STAFF_SAFE_QUERY_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "staff_safe_query",
        "description": (
            "【统一工地安全数据查询入口】当用户询问工地相关数据时，必须调用此工具。"
            "覆盖类别：人员(总览/分布/库/列表/定位/轨迹)、班组(出勤/架构/告警)、"
            "组织(架构/参建公司/参建方)、考勤(日考勤/出勤统计)、设备物资(设备/基站/标签/物资)、"
            "告警(记录/列表/预警/处理/分析)、作业面(人员列表)。"
            "只需用自然语言描述查询内容，本工具自动分析意图并返回结构化结果。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户自然语言查询，如：今天人员总览、最近告警、人员定位走势、班组出勤、设备统计、考勤数据、组织架构等",
                },
            },
            "required": ["query"],
        },
    },
}


@register_function("staff_safe_query", STAFF_SAFE_QUERY_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def staff_safe_query(
    conn: "ConnectionHandler",
    query: str = None,
):
    """智能工地安全数据查询

    流程：用户输入 → LLM 意图分析 → 调用对应数据接口 → LLM 总结 → 返回结果
    """
    if not query:
        return ActionResponse(
            Action.RESPONSE,
            response="请提供查询内容，例如：查询今天人员总览。",
        )

    # ---- Step 0: 关键词预过滤（非工地数据直接拒绝，避免 LLM 误匹配） ----
    if _is_non_staff_query(query):
        logger.bind(tag=TAG).info(f"关键词预过滤判定为非工地数据查询: {query}")
        return ActionResponse(
            Action.RESPONSE,
            response="暂时无法查询相关信息",
        )

    request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- Step 1: LLM 意图分析 ----
    # 根据项目配置过滤 API 目录，确保 LLM 只看到当前项目允许的接口
    filtered_catalog = _get_filtered_api_catalog(conn)
    if not filtered_catalog:
        logger.bind(tag=TAG).warning(
            f"当前项目未配置任何数据接口，拒绝查询: {query}"
        )
        return ActionResponse(
            Action.RESPONSE,
            response="当前项目暂无可用数据接口",
        )
    intent_prompt = _build_intent_prompt(query, filtered_catalog)

    try:
        # 使用 conn 上的 LLM 做意图分析
        intent_llm = getattr(conn.intent, "llm", None)
        if intent_llm is None:
            return ActionResponse(
                Action.RESPONSE,
                response="LLM 服务未就绪，无法进行意图分析。",
            )

        # 尝试缓存命中
        cache_key = hashlib.md5(query.encode()).hexdigest()
        cached = _intent_cache.get(cache_key)
        if cached and cached.get("expires_at", 0) > time.time():
            intent_raw = cached["result"]
            logger.bind(tag=TAG).info(f"命中内部意图缓存: {query[:20]}...")
        else:
            intent_raw = intent_llm.response_no_stream(
                system_prompt=intent_prompt,
                user_prompt=query,
                max_tokens=200,
            )
            _intent_cache[cache_key] = {"result": intent_raw, "expires_at": time.time() + 60}
        # 清理并解析意图结果
        intent_raw = intent_raw.strip()
        import re as _re
        match = _re.search(r"\{.*\}", intent_raw, _re.DOTALL)
        if match:
            intent_raw = match.group(0)
        intent_result = json.loads(intent_raw)

        logger.bind(tag=TAG).info(f"意图分析结果: {intent_result}")

    except Exception as e:
        logger.bind(tag=TAG).error(f"意图分析失败: {e}")
        return ActionResponse(
            Action.RESPONSE,
            response="意图分析失败，请重新描述查询内容。",
        )

    # ---- Step 2: 调用数据接口 ----
    api_info = _select_api_by_intent(intent_result)
    if api_info is None:
        logger.bind(tag=TAG).warning(
            f"意图分析未匹配到接口, api_id={intent_result.get('api_id', '未知')}, query={query}"
        )
        return ActionResponse(
            Action.RESPONSE,
            response="暂时无法查询相关信息",
        )

    extra_params = intent_result.get("extra_params", {})
    api_path = api_info["path"]
    # 如果有 date 参数且接口需要 startDate/endDate 或 day
    if "date" in extra_params:
        date_val = extra_params.pop("date")
        if "snapshoot" in api_path:
            extra_params["startDate"] = f"{date_val} 00:00:00"
            extra_params["endDate"] = f"{date_val} 23:59:59"
        elif "track" in api_path:
            extra_params["day"] = date_val
        elif "attendance" in api_path:
            extra_params["date"] = date_val
    # snapshoot 接口强制需要 startDate/endDate，没有则默认今天
    if "snapshoot" in api_path and "startDate" not in extra_params:
        today = datetime.now().strftime("%Y-%m-%d")
        extra_params["startDate"] = f"{today} 00:00:00"
        extra_params["endDate"] = f"{today} 23:59:59"
    # attendance 接口需要 date 参数，没有则默认今天
    if "attendance" in api_path and "date" not in extra_params:
        extra_params["date"] = datetime.now().strftime("%Y-%m-%d")

    api_result = _call_api(api_info, extra_params)

    # ---- attendanceDay 后处理：通过 personPage 做 ID→名称映射 ----
    if api_result["success"] and api_info["api_id"] == "attendanceDay":
        try:
            logger.bind(tag=TAG).info("attendanceDay 查询成功，开始 ID→名称映射...")

            # Step 2a: 从 attendanceDay 提取唯一 orgId 列表
            attendance_data = api_result["data"]
            if isinstance(attendance_data, dict) and "data" in attendance_data:
                attendance_data = attendance_data["data"]
            unique_org_ids = set()
            if isinstance(attendance_data, list):
                for record in attendance_data:
                    oid = record.get("orgId", "") or record.get("organId", "")
                    if oid:
                        unique_org_ids.add(oid)

            # Step 2b: 调用 personPage，传入 organIds 精确获取这些班组的人员映射
            person_page_info = _select_api_by_intent({"api_id": "personPage"})
            person_page_params = {"pageNum": 1, "pageSize": 5000}
            if unique_org_ids:
                person_page_params["organIds"] = list(unique_org_ids)
            person_page_result = _call_api(person_page_info, person_page_params)

            person_name_map = {}  # personId → personName
            org_name_map = {}     # orgId → orgName

            if person_page_result.get("success"):
                page_data = person_page_result["data"]
                if isinstance(page_data, dict) and "data" in page_data:
                    page_data = page_data["data"]
                rows = page_data.get("rows", []) if isinstance(page_data, dict) else []
                for item in rows:
                    pid = item.get("id", "")
                    name = item.get("name", "")
                    if pid and name:
                        person_name_map[pid] = name
                    oid = item.get("organization", "")
                    oname = item.get("orgName", "")
                    if oid and oname and oid not in org_name_map:
                        org_name_map[oid] = oname
                logger.bind(tag=TAG).info(
                    f"personPage 映射完成: {len(person_name_map)} 个人员, {len(org_name_map)} 个组织"
                    f" (过滤 organIds: {len(unique_org_ids)} 个)"
                )
            else:
                logger.bind(tag=TAG).warning(
                    f"personPage 调用失败: {person_page_result.get('error')}"
                )

            # Step 2c: 用映射丰富 attendance 数据，并只保留总结所需字段
            if isinstance(attendance_data, list):
                mapped_person = 0
                mapped_org = 0
                total_person = 0
                total_org = 0
                # 构建清洗后的记录列表，只保留 personName / orgName / 停留时长
                clean_records = []
                for record in attendance_data:
                    person_id = record.get("personId", "")
                    org_id = record.get("orgId", "") or record.get("organId", "")
                    # totalStayTime 单位是秒，转为小时（保留 1 位小数）
                    stay_seconds = record.get("totalStayTime", 0) or 0
                    stay_hours = round(stay_seconds / 3600.0, 1)

                    # 注入 personName
                    person_name = "未知人员"
                    if person_id:
                        total_person += 1
                        if person_id in person_name_map:
                            person_name = person_name_map[person_id]
                            mapped_person += 1

                    # 注入 orgName
                    org_name = ""
                    if org_id:
                        total_org += 1
                        if org_id in org_name_map:
                            org_name = org_name_map[org_id]
                            mapped_org += 1
                        else:
                            org_name = f"班组-{org_id}"

                    clean_records.append({
                        "personName": person_name,
                        "orgName": org_name,
                        "totalStayTime": {
                            "hours": stay_hours,
                            "seconds": stay_seconds,
                        },
                    })

                logger.bind(tag=TAG).info(
                    f"attendanceDay 数据丰富完成: {len(clean_records)} 条记录, "
                    f"人员映射 {mapped_person}/{total_person}, "
                    f"组织映射 {mapped_org}/{total_org}"
                )

                # 用清洗后的数据替换原始 response，避免 LLM 被 ID 字段干扰
                data_wrapper = api_result["data"]
                if isinstance(data_wrapper, dict) and "data" in data_wrapper:
                    data_wrapper["data"] = clean_records
                else:
                    api_result["data"] = {"data": clean_records}
        except Exception as e:
            logger.bind(tag=TAG).error(f"attendanceDay ID→名称映射失败: {e}", exc_info=True)

    # ---- 人员位置/定位查询后处理：双接口聚合 ----
    # 如果是 personCurLocationV2（人员列表）或 snapshootProjectPersonCountV3（24H走势），
    # 同时获取另一个接口的数据，确保 LLM 总结来源全面
    is_person_cur_location = api_result["success"] and api_info["api_id"] == "personCurLocationV2"
    is_snapshoot = api_result["success"] and api_info["api_id"] == "snapshootProjectPersonCountV3"

    # 人员位置查找快捷路径（指定 personName 的精确查找）
    person_name = extra_params.get("personName", "")
    if is_person_cur_location and person_name:
        location_name = _find_person_location(api_result["data"], person_name)
        if location_name:
            return ActionResponse(
                Action.RESPONSE,
                response=f"{person_name}目前位于{location_name}。",
                result=json.dumps({
                    "请求内容": query,
                    "请求时间": request_time,
                    "人员姓名": person_name,
                    "所在位置": location_name,
                }, ensure_ascii=False, indent=2),
            )
        else:
            return ActionResponse(
                Action.RESPONSE,
                response=f"未在今日人员定位列表中找到{person_name}，请确认姓名是否正确或该人员是否在场。",
                result=json.dumps({
                    "请求内容": query,
                    "请求时间": request_time,
                    "人员姓名": person_name,
                    "所在位置": "未找到",
                }, ensure_ascii=False, indent=2),
            )

    # 人员定位双接口聚合：并行获取 personCurLocationV2 + snapshootProjectPersonCountV3
    if is_person_cur_location or is_snapshoot:
        logger.bind(tag=TAG).info("人员定位查询：启动双接口并行聚合...")
        snapshoot_result = None
        try:
            if is_person_cur_location:
                # 已有 personCurLocationV2（api_result），并行补调 snapshoot
                today = datetime.now().strftime("%Y-%m-%d")
                snapshoot_info = {
                    "api_id": "snapshootProjectPersonCountV3",
                    "path": "location/snapshootProjectPersonCountV3",
                    "method": "POST",
                    "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
                    "description": "今日人员定位-24H走势图",
                    "category": "定位",
                }
                snapshoot_extra = {"startDate": f"{today} 00:00:00", "endDate": f"{today} 23:59:59"}
                with ThreadPoolExecutor(max_workers=1) as executor:
                    snapshoot_future = executor.submit(_call_api, snapshoot_info, snapshoot_extra)
                    snapshoot_result = snapshoot_future.result(timeout=30)
            else:
                # 已有 snapshoot（api_result），并行补调 personCurLocationV2
                person_info = {
                    "api_id": "personCurLocationV2",
                    "path": "location/personCurLocation/v2",
                    "method": "POST",
                    "params": {"projectKey": STAFF_SAFE_PROJECT_KEY},
                    "description": "今日人员定位-人员列表",
                    "category": "定位",
                }
                with ThreadPoolExecutor(max_workers=1) as executor:
                    person_future = executor.submit(_call_api, person_info, {})
                    person_result = person_future.result(timeout=30)
                    snapshoot_result = api_result  # snapshoot 是主结果
                    api_result = person_result  # 交换

            # 处理 personCurLocationV2 数据，提取基站分布
            gateway_dist = {}
            if api_result["success"]:
                person_data = api_result["data"]
                if isinstance(person_data, dict):
                    inner_data = person_data.get("data") or person_data
                    if isinstance(inner_data, list):
                        inner_data = {"stayPersonPageVos": inner_data, "stayPersonCountVos": []}
                    if isinstance(inner_data, dict):
                        page_vos = inner_data.get("stayPersonPageVos") or []
                        for vo in page_vos:
                            if isinstance(vo, dict):
                                gateway = vo.get("gatewayPositionName", "")
                                if gateway:
                                    gateway_dist[gateway] = gateway_dist.get(gateway, 0) + 1

            # 处理 snapshootProjectPersonCountV3 数据，做趋势摘要
            trend_summary = {}
            if snapshoot_result and snapshoot_result.get("success"):
                snap_data = snapshoot_result["data"]
                if isinstance(snap_data, dict):
                    data_list = snap_data.get("data") or []
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
                                "trend": (
                                    "上升" if len(online_counts) >= 2 and online_counts[-1] > online_counts[0]
                                    else ("下降" if len(online_counts) >= 2 and online_counts[-1] < online_counts[0] else "平稳")
                                ),
                            }

            # 构建聚合数据
            combined_data = {
                "查询类型": "人员定位综合查询",
                "24H趋势摘要": trend_summary,
                "人员基站位置分布": gateway_dist,
                "personCurLocationV2_原始数据": api_result["data"] if api_result["success"] else None,
            }
            data_truncated = _truncate_data(combined_data)
            involved_data = {
                "api_ids": ["personCurLocationV2", "snapshootProjectPersonCountV3"],
                "api_description": "人员定位综合查询（双接口聚合）",
                "api_category": "定位",
            }
        except Exception as e:
            logger.bind(tag=TAG).error(f"人员定位双接口聚合失败: {e}", exc_info=True)
            data_truncated = _truncate_data(api_result["data"])
            involved_data = {
                "api_id": api_info["api_id"],
                "api_description": api_info["description"],
                "api_category": api_info["category"],
                "api_path": api_info["path"],
                "http_status": api_result["http_status"],
                "elapsed_seconds": api_result["elapsed"],
            }

    # 构建涉及数据摘要（如果双接口聚合已设置则跳过）
    is_personnel_query = is_person_cur_location or is_snapshoot
    if not is_personnel_query:
        if not api_result["success"]:
            return ActionResponse(
                Action.RESPONSE,
                response=f"数据接口调用失败：{api_result.get('error', '未知错误')}",
            )
        data_truncated = _truncate_data(api_result["data"])
        involved_data = {
            "api_id": api_info["api_id"],
            "api_description": api_info["description"],
            "api_category": api_info["category"],
            "api_path": api_info["path"],
            "http_status": api_result["http_status"],
            "elapsed_seconds": api_result["elapsed"],
        }

    # ---- Step 3: LLM 数据总结 ----
    summary_prompt = _build_summary_prompt(
        api_info["description"],
        data_truncated,
        query,
        api_info["category"],
    )

    try:
        summary_text = intent_llm.response_no_stream(
            system_prompt=summary_prompt,
            user_prompt="请生成数据总结",
            max_tokens=200,
        )
    except Exception as e:
        logger.bind(tag=TAG).error(f"数据总结失败: {e}")
        summary_text = "数据总结生成失败，请查看原始数据。"

    # ---- Step 4: 构建最终返回 JSON ----
    final_result = {
        "请求内容": query,
        "请求时间": request_time,
        "涉及数据": involved_data,
        "返回数据总结": summary_text.strip(),
    }

    result_json = json.dumps(final_result, ensure_ascii=False, indent=2)

    # 直接返回口语化总结文本，避免双重 LLM 总结（内部已完成总结，不需要 intentHandler 再调 skill summary）
    response_text = summary_text.strip()
    return ActionResponse(Action.RESPONSE, result=result_json, response=response_text)
