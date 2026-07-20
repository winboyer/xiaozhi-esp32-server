import re
import json
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# 注册地磅数据技能提示
from plugins_func.skills.weighbridge_skill import register_weighbridge_skill

register_weighbridge_skill()

TAG = __name__
logger = setup_logging()

ANALYZE_WEIGHBRIDGE_DATA_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "analyze_weighbridge_data",
        "description": (
            "分析指定项目的地磅数据，包括过磅次数、总重量、车辆类型统计、日趋势分析等。"
            "例如：分析三元里今天的地磅数据；三元里地磅数据怎么样；看看地磅最近一周统计。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "项目ID，例如 sanyuanli（三元里）",
                    "default": "sanyuanli",
                },
                "query_type": {
                    "type": "string",
                    "description": "查询类型：week（查询最近一周数据）。注意：单日查询也使用 week 模式，通过 start_time 限定当天范围。",
                    "enum": ["week"],
                    "default": "week",
                },
                "end_time": {
                    "type": "string",
                    "description": (
                        "查询截止时间，格式 YYYY-MM-DD HH:MM:SS，例如 2026-03-06 23:59:59。"
                        "query_type=day 时表示查询当天的数据截止时间；"
                        "query_type=week 时表示查询最近一周（含当天）到该截止时间的数据"
                    ),
                    "default": "当前时间",
                },
            },
            "required": ["project_id", "query_type", "end_time"],
        },
    },
}


def _default_end_time() -> str:
    """返回当前时间的 YYYY-MM-DD HH:MM:SS 格式字符串。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _validate_end_time(end_time: Optional[str]) -> str:
    """校验 end_time 格式为 YYYY-MM-DD HH:MM:SS，无效则返回当前时间。"""
    if not end_time or not isinstance(end_time, str):
        return _default_end_time()
    end_time = end_time.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", end_time):
        try:
            datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
            return end_time
        except ValueError:
            pass
    logger.bind(tag=TAG).warning(f"end_time 格式无效: {end_time}，使用当前时间")
    return _default_end_time()


def _to_float(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _extract_weighbridge_stats(payload: Any) -> Dict[str, Any]:
    """按 workerstatus 返回结构提取统计信息。"""
    result_data = payload.get("data", {}) if isinstance(payload, dict) else {}
    records = result_data.get("list") or []

    seen_orders = {}
    unique_records = []
    for item in records:
        if not isinstance(item, dict):
            continue
        order_code = str(item.get("scaleOrderCode") or "")
        if order_code and order_code in seen_orders:
            continue
        if order_code:
            seen_orders[order_code] = True
        unique_records.append(item)

    total_count = len(unique_records)
    total_weight = sum(_to_float(r.get("weight", 0)) for r in unique_records)

    daily_stats: Dict[str, Dict[str, float]] = {}
    plate_stats: Dict[str, Dict[str, float]] = {}

    for r in unique_records:
        weight = _to_float(r.get("weight", 0))
        plate = str(r.get("licensePlateCode") or "未识别")
        device_time = str(r.get("deviceTime") or r.get("time") or "")
        day = device_time[:10] if device_time else "未知"

        if day not in daily_stats:
            daily_stats[day] = {"count": 0, "weight": 0.0}
        daily_stats[day]["count"] += 1
        daily_stats[day]["weight"] += weight

        if plate not in plate_stats:
            plate_stats[plate] = {"count": 0, "weight": 0.0}
        plate_stats[plate]["count"] += 1
        plate_stats[plate]["weight"] += weight

    peak_day = (
        max(daily_stats.items(), key=lambda x: x[1]["count"])
        if daily_stats
        else None
    )
    top_plate = (
        max(plate_stats.items(), key=lambda x: x[1]["count"])
        if plate_stats
        else None
    )
    avg_weight = total_weight / total_count if total_count > 0 else 0.0
    avg_daily_count = total_count / len(daily_stats) if daily_stats else 0.0

    unit = ""
    for r in unique_records:
        if not unit:
            unit = str(r.get("unit") or "吨")
        break

    return {
        "api_code": payload.get("code") if isinstance(payload, dict) else None,
        "api_msg": payload.get("msg") if isinstance(payload, dict) else "",
        "project_id": result_data.get("project_id", ""),
        "query_type": result_data.get("query_type", ""),
        "start_time": result_data.get("start_time", ""),
        "end_time": result_data.get("end_time", ""),
        "unit": unit or "吨",
        "total_count": total_count,
        "total_weight": total_weight,
        "avg_weight": avg_weight,
        "avg_daily_count": avg_daily_count,
        "daily_stats": daily_stats,
        "plate_stats": plate_stats,
        "peak_day": peak_day,
        "top_plate": top_plate,
    }


def _format_raw_data_for_llm(stats: Dict[str, Any]) -> str:
    """将统计数据格式化为结构化 JSON 文本供 LLM 做智能总结。"""
    # 过滤掉内部字段，保留有价值的数据
    clean_stats = {
        k: v
        for k, v in stats.items()
        if not k.startswith("api_") and v is not None and v != ""
    }
    # 将 daily_stats 和 plate_stats 转为可读列表格式
    if "daily_stats" in clean_stats:
        daily_list = [
            {"date": day, "count": s["count"], "weight": s["weight"]}
            for day, s in clean_stats["daily_stats"].items()
        ]
        daily_list.sort(key=lambda x: x["date"])
        clean_stats["daily_stats"] = daily_list

    if "plate_stats" in clean_stats:
        plate_list = [
            {"plate": plate, "count": s["count"], "weight": s["weight"]}
            for plate, s in clean_stats["plate_stats"].items()
        ]
        plate_list.sort(key=lambda x: x["count"], reverse=True)
        clean_stats["plate_stats"] = plate_list

    # 简化 peak_day 和 top_plate 格式
    if "peak_day" in clean_stats and clean_stats["peak_day"]:
        clean_stats["peak_day"] = {
            "date": clean_stats["peak_day"][0],
            "count": clean_stats["peak_day"][1]["count"],
            "weight": clean_stats["peak_day"][1]["weight"],
        }
    if "top_plate" in clean_stats and clean_stats["top_plate"]:
        clean_stats["top_plate"] = {
            "plate": clean_stats["top_plate"][0],
            "count": clean_stats["top_plate"][1]["count"],
            "weight": clean_stats["top_plate"][1]["weight"],
        }

    return json.dumps(clean_stats, ensure_ascii=False, indent=2)


@register_function(
    "analyze_weighbridge_data",
    ANALYZE_WEIGHBRIDGE_DATA_FUNCTION_DESC,
    ToolType.SYSTEM_CTL,
)
def analyze_weighbridge_data(
    conn: "ConnectionHandler",
    project_id: str = "sanyuanli",
    query_type: str = "week",
    end_time: str = None,
):
    # 参数默认值处理
    project_id = (project_id or "sanyuanli").strip()
    query_type = (query_type or "week").strip().lower()
    # 外部 API 只支持 week 模式，day 模式会返回 400，内部统一使用 week
    original_query_type = query_type
    query_type = "week"
    if original_query_type != "week":
        logger.bind(tag=TAG).info(
            f"query_type 从 {original_query_type} 转换为 week（外部接口仅支持 week）"
        )
    end_time = _validate_end_time(end_time)

    plugins_cfg = conn.config.get("plugins", {})
    plugin_config = plugins_cfg.get("analyze_weighbridge_data", {})
    if not plugin_config:
        plugin_config = plugins_cfg.get("query_plate_records", {})
    api_url = plugin_config.get(
        "api_url",
        "https://dmap.cscec3bxjy.cn/api/dibang/report/workerstatus",
    )
    timeout = int(plugin_config.get("timeout", 30))

    # 将用户传入的地点名称映射为实际项目ID（如 三元里 -> sanyuanli）
    location_map = plugin_config.get("location_project_map", {})
    mapped_project_id = location_map.get(project_id, project_id)
    if mapped_project_id != project_id:
        logger.bind(tag=TAG).info(
            f"项目ID映射: {project_id} -> {mapped_project_id}"
        )

    payload = {
        "project_id": mapped_project_id,
        "query_type": query_type,
        "end_time": end_time,
    }

    logger.bind(tag=TAG).info(
        f"analyze_weighbridge_data 调用外部接口 | project_id={mapped_project_id} "
        f"query_type={query_type} end_time={end_time}"
    )

    try:
        resp = requests.post(api_url, json=payload, timeout=timeout)
        if not resp.ok:
            # 记录非200响应的详细内容，便于排查400等错误
            resp_body = resp.text[:500] if resp.text else ""
            logger.bind(tag=TAG).error(
                f"analyze_weighbridge_data API返回错误 | status={resp.status_code} "
                f"url={api_url} payload={payload} response={resp_body}"
            )
            return ActionResponse(
                Action.RESPONSE,
                response=f"地磅数据查询失败，接口返回 {resp.status_code} 错误。",
            )
        data = resp.json()

        stats = _extract_weighbridge_stats(data)

        # 返回原始数据给 LLM 做智能总结（REQLLM 模式）
        raw_data = _format_raw_data_for_llm(stats)
        return ActionResponse(Action.REQLLM, result=raw_data, response=None)
    except requests.exceptions.Timeout:
        return ActionResponse(
            Action.RESPONSE, response="地磅数据查询超时，请稍后再试。"
        )
    except requests.exceptions.RequestException as e:
        logger.bind(tag=TAG).error(
            f"analyze_weighbridge_data 请求失败: {e}"
        )
        return ActionResponse(
            Action.RESPONSE, response="地磅数据查询失败，外部服务暂不可用。"
        )
    except Exception as e:
        logger.bind(tag=TAG).error(
            f"analyze_weighbridge_data 处理异常: {e}"
        )
        return ActionResponse(
            Action.RESPONSE, response="地磅数据分析失败，结果解析异常。"
        )
