"""楼栋施工进度查询 - 通过塔机静态数据 API 获取各楼栋当前施工进度"""

import json
from typing import TYPE_CHECKING

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action
from plugins_func.functions.taji_auth import (
    get_access_token,
    query_buildings,
    get_building_name,
    match_number,
)

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

# 注册技能提示
from plugins_func.skills.building_progress_skill import register_building_progress_skill

register_building_progress_skill()

TAG = __name__
logger = setup_logging()

BUILDING_PROGRESS_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "query_building_progress",
        "description": (
            "查询楼栋施工进度。"
            "当用户询问「楼栋施工进度」「X号楼施工进度」「全部楼栋施工进度」「查询施工进度」时调用此函数。"
            "支持查询全部楼栋或指定楼栋名称（如1号楼、2号楼）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "building_name": {
                    "type": "string",
                    "description": "可选，指定楼栋名称（如「1号楼」）。不指定则返回全部楼栋的施工进度。",
                },
            },
            "required": [],
        },
    },
}


@register_function("query_building_progress", BUILDING_PROGRESS_FUNCTION_DESC, ToolType.SYSTEM_CTL)
def query_building_progress(
    conn: "ConnectionHandler",
    building_name: str = None,
):
    """查询楼栋施工进度

    Args:
        conn: 连接处理器
        building_name: 可选，指定楼栋名称
    """
    # Step 1: 认证
    access_token = get_access_token()
    if not access_token:
        return ActionResponse(
            Action.RESPONSE,
            response="塔机数据服务认证失败，请稍后再试。",
        )

    # Step 2: 查询楼栋列表
    buildings = query_buildings(access_token)
    if not buildings:
        return ActionResponse(
            Action.RESPONSE,
            response="未查询到楼栋施工数据，请确认项目配置是否正确。",
        )

    # Step 3: 过滤/匹配
    if building_name and building_name.strip():
        name_clean = building_name.strip()
        matched = None
        for b in buildings:
            b_name = get_building_name(b)
            if name_clean in b_name or b_name in name_clean:
                matched = b
                break
        if not matched:
            for b in buildings:
                b_name = get_building_name(b)
                if match_number(b_name, name_clean):
                    matched = b
                    break
        if not matched:
            available = [get_building_name(b) for b in buildings[:20]]
            return ActionResponse(
                Action.RESPONSE,
                response=f"未找到与「{building_name}」匹配的楼栋信息，当前可查询的楼栋包括：{', '.join(available)}。",
            )
        buildings = [matched]

    # Step 4: 构建结构化数据供 LLM 总结
    progress_items = []
    for b in buildings:
        b_name = get_building_name(b)
        current_floor = b.get("current_construction_floor") or b.get("currentConstructionFloor") or 0
        total_floor = b.get("total_floor") or b.get("totalFloor") or 0
        progress_items.append({
            "building_name": b_name,
            "current_construction_floor": current_floor,
            "total_floor": total_floor,
        })

    raw_data = json.dumps({
        "query_type": "楼栋施工进度",
        "total_count": len(progress_items),
        "buildings": progress_items,
    }, ensure_ascii=False, indent=2)

    return ActionResponse(Action.REQLLM, result=raw_data, response=None)