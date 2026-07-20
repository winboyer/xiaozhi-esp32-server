import re
import json
from datetime import datetime
from typing import Any, Dict, List

import requests
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# 注册车牌记录技能提示
from plugins_func.skills.plate_records_skill import register_plate_records_skill

register_plate_records_skill()

TAG = __name__
logger = setup_logging()

QUERY_PLATE_RECORDS_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "query_plate_records",
        "description": (
            "查询指定项目在指定日期的车牌号记录数量。"
            "例如：查询三元里2026年5月28日记录有多少量车牌号信息。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "项目地点，例如三元里",
                },
                "date": {
                    "type": "string",
                    "description": "查询日期，格式 YYYY-MM-DD 或 YYYY年M月D日",
                },
            },
            "required": ["location", "date"],
        },
    },
}


def _normalize_date(date_str: str) -> str:
    date_str = (date_str or "").strip()
    if not date_str:
        raise ValueError("date 不能为空")

    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", date_str):
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")

    date_str = date_str.replace("年", "-").replace("月", "-").replace("日", "")
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", date_str):
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")

    raise ValueError("date 格式必须是 YYYY-MM-DD 或 YYYY年M月D日")


def _extract_plate_count(payload: Any) -> int:
    # 优先提取明显的车牌计数字段
    plate_count_keys = {
        "plate_count",
        "license_plate_count",
        "car_plate_count",
        "plateNum",
        "plate_num",
    }

    direct_values: List[int] = []
    plate_candidates: List[str] = []

    def walk(node: Any):
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k)
                lowered = key.lower()
                if k in plate_count_keys and isinstance(v, (int, float)):
                    direct_values.append(int(v))
                if ("plate" in lowered or "车牌" in key) and isinstance(v, str):
                    plate_candidates.append(v)
                if ("plate" in lowered or "车牌" in key) and isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            plate_candidates.append(item)
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)

    if direct_values:
        return max(direct_values)

    normalized_plates: List[str] = []
    plate_pattern = re.compile(r"[A-Z]{1}[A-Z0-9]{5,7}")
    for plate in plate_candidates:
        cleaned = re.sub(r"\s+", "", plate.upper())
        matched = plate_pattern.findall(cleaned)
        if matched:
            normalized_plates.extend(matched)
        elif cleaned:
            normalized_plates.append(cleaned)

    if normalized_plates:
        return len(normalized_plates)

    # 兜底：若 data 是列表，按记录条数统计
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return len(data)

    return 0


@register_function("query_plate_records", QUERY_PLATE_RECORDS_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def query_plate_records(conn: "ConnectionHandler", location: str = None, date: str = None):
    if not location or not date:
        return ActionResponse(
            Action.RESPONSE,
            response="缺少参数，请提供地点和日期，例如：查询三元里2026年5月28日车牌记录。",
        )

    plugin_config = conn.config.get("plugins", {}).get("query_plate_records", {})
    api_url = plugin_config.get(
        "api_url", "https://dmap.cscec3bxjy.cn/api/dibang/report/workerstatus"
    )
    timeout = int(plugin_config.get("timeout", 30))

    location_map = plugin_config.get("location_project_map", {})
    project_id = location_map.get(location, plugin_config.get("default_project_id", location))

    try:
        normalized_date = _normalize_date(date)
    except ValueError as e:
        return ActionResponse(Action.RESPONSE, response=f"日期格式错误：{e}")

    # 外部 API 只支持 week 模式，day 模式会返回 400
    payload = {
        "project_id": project_id,
        "query_type": "week",
        "end_time": f"{normalized_date} 23:59:59",
    }

    logger.bind(tag=TAG).info(
        f"query_plate_records 调用外部接口 | location={location} project_id={project_id} date={normalized_date}"
    )

    try:
        resp = requests.post(api_url, json=payload, timeout=timeout)
        if not resp.ok:
            # 记录非200响应的详细内容，便于排查400等错误
            resp_body = resp.text[:500] if resp.text else ""
            logger.bind(tag=TAG).error(
                f"query_plate_records API返回错误 | status={resp.status_code} "
                f"url={api_url} payload={payload} response={resp_body}"
            )
            return ActionResponse(
                Action.RESPONSE,
                response=f"查询失败，接口返回 {resp.status_code} 错误。",
            )
        data = resp.json()

        plate_count = _extract_plate_count(data)

        # 返回原始数据给 LLM 做智能总结（REQLLM 模式）
        raw_data = json.dumps(
            {
                "location": location,
                "date": normalized_date,
                "plate_count": plate_count,
            },
            ensure_ascii=False,
            indent=2,
        )
        return ActionResponse(Action.REQLLM, result=raw_data, response=None)
    except requests.exceptions.Timeout:
        return ActionResponse(Action.RESPONSE, response="查询超时，请稍后再试。")
    except requests.exceptions.RequestException as e:
        logger.bind(tag=TAG).error(f"query_plate_records 请求失败: {e}")
        return ActionResponse(Action.RESPONSE, response="查询失败，外部服务暂不可用。")
    except Exception as e:
        logger.bind(tag=TAG).error(f"query_plate_records 处理异常: {e}")
        return ActionResponse(Action.RESPONSE, response="查询失败，结果解析异常。")
