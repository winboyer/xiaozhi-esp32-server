"""设备运行状态查询技能提示注册"""

from .base import SkillHints
from .registry import skill_registry

FEW_SHOT_EXAMPLES = [
    "```\n用户: 查询全部设备运行状态\n"
    '返回: {"function_call": {"name": "query_device_status", "arguments": {}}}\n'
    "```",
    "```\n用户: 塔吊1在线状态\n"
    '返回: {"function_call": {"name": "query_device_status", "arguments": {"device_name": "塔吊1"}}}\n'
    "```",
    "```\n用户: 查询塔机8是否在线\n"
    '返回: {"function_call": {"name": "query_device_status", "arguments": {"device_name": "塔机8"}}}\n'
    "```",
    "```\n用户: 设备运行状态\n"
    '返回: {"function_call": {"name": "query_device_status", "arguments": {}}}\n'
    "```",
    "```\n用户: 所有塔吊的运行状态\n"
    '返回: {"function_call": {"name": "query_device_status", "arguments": {}}}\n'
    "```",
]

SUMMARY_PROMPT = """你是一个工地设备监控助手。请根据以下设备运行状态数据生成一段简洁、口语化的总结回复。

数据内容：
{data}

要求：
1. 用口语化、自然的语言描述各设备的在线/离线状态，像向领导汇报一样
2. 列出每台设备的名称和状态
3. 区分在线（运行中）和离线（已离线/停止）的设备
4. 如果用户指定了特定设备名称，只汇报该设备的信息
5. 回复长度控制在50-150字，简洁明了
6. 不要使用任何 Markdown 格式，纯文本回复
7. 不要添加「根据数据分析」等套话，直接说结果

请直接返回总结文本："""


def register_device_status_skill():
    """注册设备运行状态查询技能提示"""
    hints = SkillHints(
        function_name="query_device_status",
        keywords=[
            "设备运行状态", "运行状态", "在线状态",
            "是否在线", "是否运行", "在线",
        ],
        few_shot_examples=FEW_SHOT_EXAMPLES,
        summary_prompt=SUMMARY_PROMPT,
        priority=7,
    )
    skill_registry.register(hints)


def unregister_device_status_skill():
    """注销设备运行状态查询技能提示"""
    skill_registry.unregister("query_device_status")