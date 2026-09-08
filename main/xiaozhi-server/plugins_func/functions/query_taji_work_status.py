"""塔机历史作业状态查询 - 通过向阳村项目塔机数据服务查询作业记录"""

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING

import requests

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# 注册技能提示
from plugins_func.skills.taji_work_status_skill import register_taji_work_status_skill

register_taji_work_status_skill()

TAG = __name__
logger = setup_logging()

# ==================== 向阳村项目塔机作业接口配置 ====================
TOWER_CRANE_WORK_CYCLE_URL = (
    "https://tciccs.cscec3bxjy.cn:30400/api/towercranedataservice/getWorkCycleInfoHis"
)
TOWER_CRANE_REQUEST_TIMEOUT = 30

# 向阳村项目塔机名称 → 设备 SN 映射
TOWER_CRANE_NAME_TO_SN = {
    "向阳村4#塔机": "91320506MAE18ATB9XTC202606181EW4",
    "向阳村3#塔机": "91320506MAE18ATB9XTC202606181EW3",
    "向阳村2#塔机": "91320506MAE18ATB9XTC202606181EW2",
}


QUERY_TAJI_WORK_STATUS_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "query_taji_work_status",
        "description": (
            "查询向阳村项目塔机/塔吊的历史作业状态与作业记录。"
            "当用户询问「塔机作业状态」「塔机干了多少活」「塔机作业次数」「XX塔机今天是否作业」"
            "「向阳村4#塔机作业情况」时调用此函数。"
            "支持查询指定塔机（如向阳村4#塔机、4#塔机、塔机2）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "塔机名称，如「向阳村4#塔机」。未指定时返回全部塔机的作业状态。",
                },
                "start_time": {
                    "type": "string",
                    "description": "可选，开始时间，格式 YYYY-MM-DD HH:MM:SS。未指定时默认当天 00:00:00。",
                },
                "end_time": {
                    "type": "string",
                    "description": "可选，结束时间，格式 YYYY-MM-DD HH:MM:SS。未指定时默认当天 24:00:00。",
                },
            },
            "required": [],
        },
    },
}


def _resolve_device_sn(name):
    """按塔机名称解析设备 SN，支持简写匹配。"""
    text = re.sub(r"\s+", "", str(name or ""))
    if not text:
        return None, None
    if text in TOWER_CRANE_NAME_TO_SN:
        return text, TOWER_CRANE_NAME_TO_SN[text]
    for full_name, device_sn in TOWER_CRANE_NAME_TO_SN.items():
        if full_name in text or text in full_name:
            return full_name, device_sn
    nums = re.findall(r"\d+", text)
    for full_name, device_sn in TOWER_CRANE_NAME_TO_SN.items():
        full_nums = re.findall(r"\d+", full_name)
        if nums and full_nums and any(n in full_nums for n in nums):
            return full_name, device_sn
    return None, None


def _validate_time(value, field_name):
    """校验时间格式，允许日终 24:00:00。"""
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2} (?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
        r"|\d{4}-\d{2}-\d{2} 24:00:00",
        value,
    ):
        raise ValueError(f"{field_name} 必须使用 YYYY-MM-DD HH:MM:SS 格式")
    return value


def _query_single_crane(device_name, start_time, end_time):
    """查询单台塔机的历史作业记录。"""
    resolved_name, device_sn = _resolve_device_sn(device_name)
    if not device_sn:
        return {"device_name": device_name, "error": "未找到匹配的塔机名称"}

    today = datetime.now().strftime("%Y-%m-%d")
    start_time = _validate_time(start_time or f"{today} 00:00:00", "start_time")
    end_time = _validate_time(end_time or f"{today} 24:00:00", "end_time")

    try:
        resp = requests.post(
            TOWER_CRANE_WORK_CYCLE_URL,
            json={"deviceSN": device_sn, "startTime": start_time, "endTime": end_time},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=TOWER_CRANE_REQUEST_TIMEOUT,
            verify=False,
        )
    except requests.RequestException as exc:
        return {"device_name": resolved_name, "error": f"塔机数据接口请求失败: {exc}"}

    try:
        payload = resp.json()
    except ValueError:
        return {"device_name": resolved_name, "error": f"接口返回非 JSON（HTTP {resp.status_code}）"}

    if resp.status_code != 200 or not payload.get("success"):
        message = payload.get("msg") or f"HTTP {resp.status_code}"
        return {"device_name": resolved_name, "error": f"塔机数据接口查询失败: {message}"}

    cycles = payload.get("data") or []
    if not isinstance(cycles, list):
        return {"device_name": resolved_name, "error": "接口返回的 data 不是数组"}

    latest = max(
        cycles,
        key=lambda item: item.get("endTime") or item.get("startTime") or "",
    ) if cycles else None

    recent = []
    for cycle in cycles[-5:]:
        recent.append({
            "start_time": cycle.get("startTime"),
            "end_time": cycle.get("endTime"),
            "weight": cycle.get("weight"),
            "max_torque": cycle.get("maxTorque"),
            "max_height": cycle.get("maxHeight"),
            "type": cycle.get("type"),
        })

    return {
        "device_name": resolved_name,
        "device_sn": device_sn,
        "query_start": start_time,
        "query_end": end_time,
        "work_cycle_count": len(cycles),
        "status": "有作业记录" if cycles else "查询范围内无作业记录",
        "latest_cycle": latest,
        "recent_cycles": recent,
    }


@register_function("query_taji_work_status", QUERY_TAJI_WORK_STATUS_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def query_taji_work_status(
    conn: "ConnectionHandler",
    device_name: str = None,
    start_time: str = None,
    end_time: str = None,
):
    """查询塔机历史作业状态

    Args:
        conn: 连接处理器
        device_name: 可选，指定塔机名称
        start_time: 可选，开始时间
        end_time: 可选，结束时间
    """
    if device_name and device_name.strip():
        names = [device_name]
    else:
        names = list(TOWER_CRANE_NAME_TO_SN.keys())

    results = []
    for name in names:
        results.append(_query_single_crane(name, start_time, end_time))

    errors = [item for item in results if item.get("error")]
    if errors and len(errors) == len(results):
        return ActionResponse(
            Action.RESPONSE,
            response=f"塔机作业状态查询失败：{errors[0]['error']}",
        )

    raw_data = json.dumps({
        "query_type": "塔机历史作业状态",
        "total_count": len(results),
        "cranes": results,
    }, ensure_ascii=False, indent=2)

    return ActionResponse(Action.REQLLM, result=raw_data, response=None)
