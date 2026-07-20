"""塔机安装高度查询 - 通过塔机静态数据 API 获取各塔机当前安装高度"""

import json
from typing import TYPE_CHECKING

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from plugins_func.functions.taji_auth import (
    get_access_token,
    query_deviceinfos,
    get_device_name,
    parse_taji_height,
    match_number,
)

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# 注册技能提示
from plugins_func.skills.taji_static_skill import register_taji_static_skill

register_taji_static_skill()

TAG = __name__
logger = setup_logging()


QUERY_TAJI_HEIGHT_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "query_taji_height",
        "description": (
            "查询塔机/塔吊的当前安装高度。"
            "当用户询问「塔机安装高度」「塔吊高度」「塔机高度是多少」「查询塔机安装高度」时调用此函数。"
            "支持查询全部塔机或指定塔机名称（如塔机1、塔机8）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "device_name": {
                    "type": "string",
                    "description": "可选，指定塔机名称（如「塔机1」）。不指定则返回全部塔机的高度信息。",
                },
            },
            "required": [],
        },
    },
}


# ==================== 注册函数 ====================

@register_function("query_taji_height", QUERY_TAJI_HEIGHT_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def query_taji_height(
    conn: "ConnectionHandler",
    device_name: str = None,
):
    """查询塔机安装高度

    Args:
        conn: 连接处理器
        device_name: 可选，指定塔机名称
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
            response="未查询到塔机设备数据，请确认项目配置是否正确。",
        )

    # Step 3: 解析塔机高度（只保留名称含「塔机」或「塔吊」的设备）
    taji_list = []
    for device in devices:
        dev_name = get_device_name(device)
        # 「塔机」或「塔吊」都匹配
        if "塔机" not in dev_name and "塔吊" not in dev_name:
            continue
        # 过滤隐藏设备
        parsed = parse_taji_height(device)
        if parsed.get("hidden"):
            continue
        taji_list.append(parsed)

    if not taji_list:
        return ActionResponse(
            Action.RESPONSE,
            response="当前项目下未找到塔机设备。",
        )

    # Step 4: 如果指定了 device_name，过滤匹配
    if device_name:
        name_clean = device_name.strip()
        filtered = [
            t for t in taji_list
            if name_clean in t["device_name"] or t["device_name"] in name_clean
        ]
        if not filtered:
            # 数字模糊匹配
            filtered = [
                t for t in taji_list
                if match_number(t["device_name"], name_clean)
            ]
        if filtered:
            taji_list = filtered
        else:
            return ActionResponse(
                Action.RESPONSE,
                response=f"未找到名称为「{device_name}」的塔机，当前可查询的塔机包括：{', '.join(t['device_name'] for t in taji_list)}。",
            )

    # Step 5: 构建结构化数据供 LLM 总结
    summary_items = []
    for t in taji_list:
        item = {
            "device_name": t["device_name"],
            "height": f"{t['height']}m" if t["height"] is not None else "未知",
            "status": "在线" if t["online"] else "离线",
        }
        if t["update_time"]:
            item["update_time"] = t["update_time"]
        summary_items.append(item)

    raw_data = json.dumps(summary_items, ensure_ascii=False, indent=2)
    return ActionResponse(Action.REQLLM, result=raw_data, response=None)