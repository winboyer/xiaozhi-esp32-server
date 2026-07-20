import re
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# 注册人员数据技能提示
from plugins_func.skills.personnel_skill import register_personnel_skill

register_personnel_skill()

TAG = __name__
logger = setup_logging()

ANALYZE_PERSONNEL_DATA_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "analyze_personnel_data",
        "description": (
            "分析指定项目地点的现场人员状态数据，包括在场人数、工种分布、"
            "今日进出人次、安全装备佩戴状态等。"
            "例如：分析三元里的人员情况；查看三元里现场人员状态；三元里工人数量统计。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "项目地点，例如三元里、工地A等",
                },
            },
            "required": ["location"],
        },
    },
}


def _to_int(value: Any) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _extract_personnel_stats(payload: Any) -> Dict[str, Any]:
    """从接口返回数据中提取人员统计信息。
    
    支持两种接口返回格式：
    1. 地磅 /workerstatus 接口中可能包含的人员辅助字段
    2. 独立的人员状态接口返回（预留）
    """
    result_data = payload.get("data", {}) if isinstance(payload, dict) else {}
    
    # 如果 data 直接是列表（present_worker/list 接口返回格式）
    if isinstance(result_data, list) and result_data:
        return _extract_personnel_stats_from_records(result_data, payload)
    
    # 优先查找人员专属字段
    personnel = result_data.get("personnel") or result_data.get("personnel_status") or {}
    
    if isinstance(personnel, dict) and personnel:
        # 独立人员状态接口
        on_site_count = _to_int(personnel.get("on_site_count") or personnel.get("on_site"))
        today_entry = _to_int(personnel.get("today_entry") or personnel.get("entry_count"))
        today_exit = _to_int(personnel.get("today_exit") or personnel.get("exit_count"))
        worker_types = personnel.get("worker_types") or personnel.get("categories") or {}
        safety_status = personnel.get("safety_status") or {}
        
        return {
            "api_code": payload.get("code") if isinstance(payload, dict) else None,
            "api_msg": payload.get("msg") if isinstance(payload, dict) else "",
            "on_site_count": on_site_count,
            "today_entry": today_entry,
            "today_exit": today_exit,
            "worker_types": worker_types if isinstance(worker_types, dict) else {},
            "safety_status": safety_status if isinstance(safety_status, dict) else {},
            "source": "personnel_dedicated",
        }
    
    # 从记录列表中提取人员/工种统计（兼容地磅接口的辅助字段）
    records = result_data.get("list") or []
    if isinstance(records, list) and len(records) == 0:
        records = result_data.get("personnel_list") or result_data.get("workers") or []
    
    if isinstance(records, list) and records:
        return _extract_personnel_stats_from_records(records, payload)
    
    # 从顶层字段中尝试提取
    top_level_stats = _extract_top_level_personnel(result_data, payload)
    if top_level_stats:
        return top_level_stats
    
    return {
        "api_code": payload.get("code") if isinstance(payload, dict) else None,
        "api_msg": payload.get("msg") if isinstance(payload, dict) else "",
        "on_site_count": 0,
        "today_entry": 0,
        "today_exit": 0,
        "worker_types": {},
        "safety_status": {},
        "raw_records": 0,
        "source": "fallback_empty",
    }


def _extract_personnel_stats_from_records(records: List[Any], payload: Any) -> Dict[str, Any]:
    """从人员记录列表中提取统计信息"""
    on_site_count = len(records)
    
    worker_types: Dict[str, int] = {}
    safety_status: Dict[str, int] = {"佩戴安全帽": 0, "未佩戴安全帽": 0, "未知": 0}
    
    for record in records:
        if not isinstance(record, dict):
            continue
        
        # 工种统计
        worker_type = str(record.get("worker_type") or record.get("type") or record.get("category") or "其他")
        worker_types[worker_type] = worker_types.get(worker_type, 0) + 1
        
        # 安全帽状态
        helmet = str(record.get("helmet") or record.get("safety_helmet") or "").strip()
        if "未" in helmet or "否" in helmet or "no" in helmet.lower():
            safety_status["未佩戴安全帽"] = safety_status.get("未佩戴安全帽", 0) + 1
        elif helmet and helmet != "未知":
            safety_status["佩戴安全帽"] = safety_status.get("佩戴安全帽", 0) + 1
        else:
            safety_status["未知"] = safety_status.get("未知", 0) + 1
    
    helmet_wear_rate = 0.0
    total_with_helmet_data = safety_status.get("佩戴安全帽", 0) + safety_status.get("未佩戴安全帽", 0)
    if total_with_helmet_data > 0:
        helmet_wear_rate = safety_status["佩戴安全帽"] / total_with_helmet_data * 100
    
    return {
        "api_code": payload.get("code") if isinstance(payload, dict) else None,
        "api_msg": payload.get("msg") if isinstance(payload, dict) else "",
        "on_site_count": on_site_count,
        "today_entry": 0,
        "today_exit": 0,
        "worker_types": worker_types,
        "safety_status": safety_status,
        "helmet_wear_rate": helmet_wear_rate,
        "source": "record_list",
    }


def _extract_top_level_personnel(result_data: Dict[str, Any], payload: Any) -> Optional[Dict[str, Any]]:
    """尝试从顶层字段中提取人员统计数据"""
    # 常见的人员统计字段名
    personnel_keys = [
        ("on_site_count", ["on_site_count", "on_site", "personnel_count", "worker_count", "total_workers"]),
        ("today_entry", ["today_entry", "entry", "today_in"]),
        ("today_exit", ["today_exit", "exit", "today_out"]),
    ]
    
    found_any = False
    stats: Dict[str, Any] = {
        "api_code": payload.get("code") if isinstance(payload, dict) else None,
        "api_msg": payload.get("msg") if isinstance(payload, dict) else "",
        "on_site_count": 0,
        "today_entry": 0,
        "today_exit": 0,
        "worker_types": {},
        "safety_status": {},
        "source": "top_level",
    }
    
    for target_key, candidate_keys in personnel_keys:
        for key in candidate_keys:
            val = result_data.get(key)
            if val is not None:
                stats[target_key] = _to_int(val)
                found_any = True
                break
    
    worker_types = result_data.get("worker_types") or result_data.get("categories")
    if worker_types and isinstance(worker_types, dict):
        stats["worker_types"] = worker_types
        found_any = True
    
    return stats if found_any else None


def _format_raw_data_for_llm(location: str, stats: Dict[str, Any]) -> str:
    """将人员统计数据格式化为结构化 JSON 文本供 LLM 做智能总结。"""
    clean_stats = {
        k: v
        for k, v in stats.items()
        if not k.startswith("api_") and v is not None and v != "" and k != "source"
    }
    clean_stats["location"] = location
    # 将 worker_types 和 safety_status 字典转为可读列表
    if "worker_types" in clean_stats and isinstance(clean_stats["worker_types"], dict):
        type_list = [
            {"type": wtype, "count": count}
            for wtype, count in clean_stats["worker_types"].items()
        ]
        type_list.sort(key=lambda x: x["count"], reverse=True)
        clean_stats["worker_types"] = type_list
    if "safety_status" in clean_stats and isinstance(clean_stats["safety_status"], dict):
        safety_list = [
            {"status": status, "count": count}
            for status, count in clean_stats["safety_status"].items()
        ]
        safety_list.sort(key=lambda x: x["count"], reverse=True)
        clean_stats["safety_status"] = safety_list

    return json.dumps(clean_stats, ensure_ascii=False, indent=2)


@register_function("analyze_personnel_data", ANALYZE_PERSONNEL_DATA_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def analyze_personnel_data(
    conn: "ConnectionHandler",
    location: str = "三元里",
):
    # ---- 三元里项目 project_id ----
    SAN_YUAN_LI_PROJECT_ID = "61455993-9f17-47b2-87c1-2d08c9745359"
    
    plugins_cfg = conn.config.get("plugins", {})
    plugin_config = plugins_cfg.get("analyze_personnel_data", {})
    if not plugin_config:
        plugin_config = {}
    
    base_url = plugin_config.get(
        "api_url",
        "https://smarthat.lanjiansuzhou.com/dashboard/proj/safety/present_worker/list",
    )
    timeout = int(plugin_config.get("timeout", 30))
    token = plugin_config.get("token", "")
    
    # 项目路由: 当前仅三元里，后续可通过 plugin_config 扩展更多项目
    location_map = plugin_config.get("location_project_map", {})
    project_id = location_map.get(location, plugin_config.get("default_project_id", SAN_YUAN_LI_PROJECT_ID))
    
    params = {
        "project_id": project_id,
        "build_id": plugin_config.get("build_id", ""),
        "worker_name": "",
        "token": token,
        "areaLvl": plugin_config.get("area_lvl", "100000"),
        "orgLvl": "",
    }
    
    logger.bind(tag=TAG).info(
        f"analyze_personnel_data 调用外部接口 GET | location={location} project_id={project_id}"
    )
    
    try:
        resp = requests.get(base_url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        
        stats = _extract_personnel_stats(data)

        # 返回原始数据给 LLM 做智能总结（REQLLM 模式）
        raw_data = _format_raw_data_for_llm(location, stats)
        return ActionResponse(Action.REQLLM, result=raw_data, response=None)
    except requests.exceptions.Timeout:
        return ActionResponse(Action.RESPONSE, response="人员数据查询超时，请稍后再试。")
    except requests.exceptions.RequestException as e:
        logger.bind(tag=TAG).error(f"analyze_personnel_data 请求失败: {e}")
        return ActionResponse(Action.RESPONSE, response="人员数据查询失败，外部服务暂不可用。")
    except Exception as e:
        logger.bind(tag=TAG).error(f"analyze_personnel_data 处理异常: {e}")
        return ActionResponse(Action.RESPONSE, response="人员数据分析失败，结果解析异常。")