"""设备运行状态查询 - 通过塔机静态数据 API 获取各设备在线/离线状态"""

import json
from typing import TYPE_CHECKING

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from plugins_func.functions.taji_auth import (
    get_access_token,
    query_deviceinfos,
    get_device_name,
    parse_online_status,
    match_number,
)

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# 注册技能提示
from plugins_func.skills.device_status_skill import register_device_status_skill

register_device_status_skill()

TAG = __name__
logger = setup_logging()

DEVICE_STATUS_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "query_device_status",
        "description": (
            "查询塔机/塔吊等设备的运行状态（在线/离线）。"
            "当用户询问「设备运行状态」「塔吊X在线状态」「全部设备运行状态」「塔机X是否在线」时调用此函数。"
            "支持查询全部设备或指定设备名称。注意：此函数仅查询塔机/塔吊设备，不包含电梯。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "可选，指定设备名称（如「塔吊1」）。不指定则返回全部设备的运行状态。",
                },
            },
            "required": [],
        },
    },
}


@register_function("query_device_status", DEVICE_STATUS_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def query_device_status(
    conn: "ConnectionHandler",
    device_name: str = None,
):
    """查询设备运行状态

    Args:
        conn: 连接处理器
        device_name: 可选，指定设备名称
    """
    # Step 1: 认证
    access_token = get_access_token()
    if not access_token:
        return ActionResponse(
            Action.RESPONSE,
            response="塔机数据服务认证失败，请稍后再试。",
        )

    # Step 2: 查询设备列表
    devices = query_deviceinfos(access_token)
    if not devices:
        return ActionResponse(
            Action.RESPONSE,
            response="未查询到设备数据，请确认项目配置是否正确。",
        )

    # 只保留塔机/塔吊设备
    taji_devices = []
    for d in devices:
        d_name = get_device_name(d)
        if "塔机" in d_name or "塔吊" in d_name:
            taji_devices.append(d)

    if not taji_devices:
        return ActionResponse(
            Action.RESPONSE,
            response="当前项目下未找到塔机/塔吊设备。",
        )

    # Step 3: 过滤/匹配
    if device_name and device_name.strip():
        name_clean = device_name.strip()
        matched = None
        for d in taji_devices:
            d_name = get_device_name(d)
            if name_clean in d_name or d_name in name_clean:
                matched = d
                break
        if not matched:
            for d in taji_devices:
                d_name = get_device_name(d)
                if match_number(d_name, name_clean):
                    matched = d
                    break
        if not matched:
            available = [get_device_name(d) for d in taji_devices[:20]]
            return ActionResponse(
                Action.RESPONSE,
                response=f"未找到与「{device_name}」匹配的设备，当前可查询的设备包括：{', '.join(available)}。",
            )
        taji_devices = [matched]

    # Step 4: 构建结构化数据供 LLM 总结
    status_items = []
    for d in taji_devices:
        d_name = get_device_name(d)
        online_status = d.get("online_status") or d.get("onlineStatus")
        status_text = parse_online_status(online_status)
        status_items.append({
            "device_name": d_name,
            "online_status": online_status,
            "status_text": status_text,
        })

    raw_data = json.dumps({
        "query_type": "设备运行状态",
        "total_count": len(status_items),
        "devices": status_items,
    }, ensure_ascii=False, indent=2)

    return ActionResponse(Action.REQLLM, result=raw_data, response=None)