"""电梯设备数据查询 - 通过电梯设备 API 获取在线状态/运行数据/人流量/当前笼内人数"""

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import requests
from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# 注册技能提示
from plugins_func.skills.elevator_skill import register_elevator_skill

register_elevator_skill()

TAG = __name__
logger = setup_logging()

# ==================== 电梯 API 配置 ====================
ELEVATOR_QUERY_URL = "http://115.159.67.12:8090/api/device/query-exec"
ELEVATOR_DEVICE_ID = "tw_lifter_0616"

# 4个电梯设备列表
ELEVATOR_DEVICES = [
    {"building": "1号楼", "cage": "左笼", "device_number": "0114004712251229001"},
    {"building": "1号楼", "cage": "右笼", "device_number": "0114004612251229001"},
    {"building": "3号楼", "cage": "左笼", "device_number": "0114004612259160001"},
    {"building": "3号楼", "cage": "右笼", "device_number": "0114004712259160001"},
]

ELEVATOR_QUERY_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "query_elevator_data",
        "description": (
            "【统一电梯设备数据查询入口】当用户询问电梯相关数据时，必须调用此工具。"
            "覆盖类别：电梯在线状态、电梯运行数据、电梯按小时统计、电梯笼内人流量（按分钟）、电梯当前笼内人数。"
            "支持查询1号楼左笼/右笼、3号楼左笼/右笼共4个电梯设备。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户自然语言查询，如：电梯在线状态、电梯运行数据、电梯按小时统计、电梯笼内人流量、电梯当前有多少人等",
                },
            },
            "required": ["query"],
        },
    },
}


# ==================== API 调用工具 ====================

def _elevator_query_device(key: str, query_params: dict = None) -> Optional[dict]:
    """发起电梯设备查询请求

    POST /api/device/query-exec?id=tw_lifter_0616
    Body: {"key": "tw_xxx", "params": {...}}
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
        logger.bind(tag=TAG).error(f"电梯API POST 失败: {resp.status_code}")
        return None
    except requests.RequestException as e:
        logger.bind(tag=TAG).error(f"电梯API 请求异常: {e}")
        return None


def _find_result(obj, depth=0) -> dict:
    """递归查找 result 字段 (适配任意嵌套层级)"""
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


def _safe_get(d, *keys):
    """安全获取字典值，支持多个备选 key"""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


# ==================== 查询逻辑 ====================

def _query_elevator_online() -> dict:
    """查询电梯在线状态"""
    data = _elevator_query_device("tw_online", {})
    if data is None:
        return {"success": False, "error": "电梯在线状态查询失败"}

    result_map = _find_result(data) if isinstance(data, dict) else {}
    dn_to_info = {d["device_number"]: f"{d['building']}{d['cage']}" for d in ELEVATOR_DEVICES}

    online_list = []
    offline_list = []
    for dn, status in result_map.items():
        info = dn_to_info.get(dn, dn)
        if status in ("online", "1", 1):
            online_list.append(info)
        else:
            offline_list.append(f"{info}({status})")

    return {
        "success": True,
        "query_type": "电梯在线状态",
        "total": len(result_map),
        "online_count": len(online_list),
        "offline_count": len(offline_list),
        "online_devices": online_list,
        "offline_devices": offline_list,
    }


def _query_elevator_current_people() -> dict:
    """查询当前时刻 4 个电梯笼内各有多少人"""
    from datetime import datetime

    data = _elevator_query_device("tw_minute_traffic", {})
    if data is None:
        return {"success": False, "error": "电梯当前笼内人数查询失败"}

    all_records = None
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict):
            std = inner.get("std")
            if isinstance(std, dict):
                all_records = std.get("records")
            if all_records is None:
                all_records = inner.get("records")
        elif isinstance(inner, list):
            all_records = inner
        if all_records is None:
            all_records = data.get("records")

    if not isinstance(all_records, list) or len(all_records) == 0:
        return {"success": False, "error": "未获取到电梯 records 数据"}

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
    now = datetime.now()
    query_time_str = now.strftime("%Y-%m-%d %H:%M:%S")

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
                    "building": building, "cage": cage, "label": label,
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
                    "AvgPersonNum": None, "status": "no_data",
                })
        else:
            device_results.append({
                "building": building, "cage": cage, "label": label,
                "DeviceNumber": dn,
                "AvgPersonNum": None, "status": "no_data",
            })

    return {
        "success": True,
        "query_type": "电梯当前笼内人数",
        "query_time": query_time_str,
        "total_devices": len(ELEVATOR_DEVICES),
        "devices_with_data": len([d for d in device_results if d["status"] == "ok"]),
        "total_avg_people": round(total_people, 1),
        "devices": device_results,
    }


# ==================== 意图解析（本地规则 + LLM 回退） ====================

def _parse_elevator_intent(query_text: str) -> dict:
    """解析电梯查询意图，返回 {"type": ..., "param": ...}"""
    import re
    text = query_text.strip()

    # 电梯当前时刻笼内人数（必须在 traffic 之前匹配，避免"人数"被误匹配）
    if re.search(r'(?:查询|当前|现在).*(?:电梯|笼内).*(?:有多少人|几人|人数)|(?:电梯).*(?:当前|现在).*(?:笼内|人数|几人)|(?:笼内).*(?:当前|现在).*(?:有多少人|人数)', text):
        return {"type": "elevator_current_people"}
    # 电梯在线状态
    if re.search(r'电梯.*(?:在线|运行状态|状态)|(?:在线|运行)状态.*电梯', text):
        return {"type": "elevator_online"}
    # 电梯运行数据按小时
    if re.search(r'电梯.*(?:运行数据|小时|时序|按小时)|(?:按小时|小时).*电梯', text):
        return {"type": "elevator_hourly"}
    # 电梯笼内人流量
    if re.search(r'(?:电梯|笼内).*(?:人流量|人流)|(?:人流量|人流).*(?:电梯|笼内)', text):
        return {"type": "elevator_traffic"}
    # 通用电梯运行数据
    if re.search(r'电梯.*(?:运行|数据|统计)|(?:查询|获取).*电梯', text):
        return {"type": "elevator_runtime"}
    # 任何包含电梯关键词的回退到 online
    if "电梯" in text:
        return {"type": "elevator_online"}

    return {"type": None}


@register_function("query_elevator_data", ELEVATOR_QUERY_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def query_elevator_data(
    conn: "ConnectionHandler",
    query: str = None,
):
    """智能电梯设备数据查询

    流程：
    1. 解析查询意图（电梯在线/运行数据/人流量/当前人数）
    2. 调用对应电梯 API
    3. 构建结构化数据
    4. 交给 LLM 总结

    Args:
        conn: 连接处理器
        query: 用户查询文本
    """
    if not query:
        return ActionResponse(
            Action.RESPONSE,
            response="请提供查询内容，例如：查询电梯在线状态、电梯当前有多少人。",
        )

    intent = _parse_elevator_intent(query)
    intent_type = intent.get("type")

    if not intent_type:
        return ActionResponse(
            Action.RESPONSE,
            response="未识别到电梯相关的查询意图，请尝试描述更明确的查询内容。",
        )

    try:
        if intent_type == "elevator_current_people":
            result = _query_elevator_current_people()
        elif intent_type == "elevator_online":
            result = _query_elevator_online()
        else:
            # elevator_runtime / elevator_hourly / elevator_traffic: 返回原始数据
            key_map = {
                "elevator_runtime": "tw_runtime",
                "elevator_hourly": "tw_hourly_stats",
                "elevator_traffic": "tw_minute_traffic",
            }
            key = key_map.get(intent_type, "tw_online")
            data = _elevator_query_device(key, {})
            if data is None:
                return ActionResponse(
                    Action.RESPONSE,
                    response="电梯设备数据查询失败，请稍后再试。",
                )
            result = {
                "success": True,
                "query_type": intent_type,
                "raw_data": data,
            }

        if not result.get("success"):
            return ActionResponse(
                Action.RESPONSE,
                response=result.get("error", "电梯数据查询失败。"),
            )

        raw_data = json.dumps(result, ensure_ascii=False, indent=2)
        return ActionResponse(Action.REQLLM, result=raw_data, response=None)

    except Exception as e:
        logger.bind(tag=TAG).error(f"电梯数据查询异常: {e}")
        return ActionResponse(
            Action.RESPONSE,
            response=f"电梯数据查询异常: {str(e)}",
        )