"""电梯设备数据查询技能提示注册"""

from .base import SkillHints
from .registry import skill_registry

FEW_SHOT_EXAMPLES = [
    "```\n用户: 查询电梯在线状态\n"
    '返回: {"function_call": {"name": "query_elevator_data", "arguments": {"query": "查询电梯在线状态"}}}\n'
    "```",
    "```\n用户: 电梯运行数据\n"
    '返回: {"function_call": {"name": "query_elevator_data", "arguments": {"query": "电梯运行数据"}}}\n'
    "```",
    "```\n用户: 电梯按小时统计\n"
    '返回: {"function_call": {"name": "query_elevator_data", "arguments": {"query": "电梯按小时统计"}}}\n'
    "```",
    "```\n用户: 电梯笼内人流量\n"
    '返回: {"function_call": {"name": "query_elevator_data", "arguments": {"query": "电梯笼内人流量"}}}\n'
    "```",
    "```\n用户: 电梯当前有多少人\n"
    '返回: {"function_call": {"name": "query_elevator_data", "arguments": {"query": "电梯当前有多少人"}}}\n'
    "```",
    "```\n用户: 电梯现在有几个人\n"
    '返回: {"function_call": {"name": "query_elevator_data", "arguments": {"query": "电梯现在有几个人"}}}\n'
    "```",
]

SUMMARY_PROMPT = """你是一个工地电梯设备监控助手。请根据以下电梯设备数据生成一段简洁、口语化的总结回复。

数据内容：
{data}

要求：
1. 用口语化、自然的语言描述电梯设备情况，像向领导汇报一样
2. 如果是在线状态数据：列出在线和离线的设备名称
3. 如果是当前笼内人数：分别列出1号楼左笼/右笼、3号楼左笼/右笼的人数，最后给出合计
4. 如果数据为空或无有效数据，直接说明
5. 回复长度控制在50-150字，简洁明了
6. 不要使用任何 Markdown 格式，纯文本回复
7. 不要添加「根据数据分析」等套话，直接说结果

请直接返回总结文本："""


def register_elevator_skill():
    """注册电梯设备数据查询技能提示"""
    hints = SkillHints(
        function_name="query_elevator_data",
        keywords=[
            "电梯", "笼内", "人流量", "在线状态",
            "运行数据", "笼内人数", "几个人",
        ],
        few_shot_examples=FEW_SHOT_EXAMPLES,
        summary_prompt=SUMMARY_PROMPT,
        priority=7,
    )
    skill_registry.register(hints)


def unregister_elevator_skill():
    """注销电梯设备数据查询技能提示"""
    skill_registry.unregister("query_elevator_data")