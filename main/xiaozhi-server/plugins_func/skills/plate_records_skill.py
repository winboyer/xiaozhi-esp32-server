"""车牌记录查询技能提示注册"""

from .base import SkillHints
from .registry import skill_registry


FEW_SHOT_EXAMPLES = [
    "```\n用户: 查询三元里2026年5月28日车牌记录\n"
    '返回: {"function_call": {"name": "query_plate_records", "arguments": {"location": "三元里", "date": "2026-05-28"}}}\n'
    "```",
    "```\n用户: 今天有多少车牌记录\n"
    '返回: {"function_call": {"name": "query_plate_records", "arguments": {"location": "三元里"}}}\n'
    "```",
    "```\n用户: 查下车牌号信息\n"
    '返回: {"function_call": {"name": "query_plate_records", "arguments": {"location": "三元里"}}}\n'
    "```",
    "```\n用户: 三元里昨天记录了多少辆车\n"
    '返回: {"function_call": {"name": "query_plate_records", "arguments": {"location": "三元里"}}}\n'
    "```",
    "```\n用户: 最近的车牌记录统计\n"
    '返回: {"function_call": {"name": "query_plate_records", "arguments": {}}}\n'
    "```",
]


SUMMARY_PROMPT = """你是一个车牌记录数据助手。请根据以下车牌记录数据生成一段简洁、口语化的总结回复。

数据内容：
{data}

要求：
1. 用口语化的语言描述车牌记录情况
2. 突出关键数字：记录条数、地点、日期
3. 回复长度控制在30-80字，简洁明了
4. 不要使用任何 Markdown 格式（如 **、- 列表等），纯文本回复

请直接返回总结文本："""


def register_plate_records_skill():
    """注册车牌记录技能提示"""
    hints = SkillHints(
        function_name="query_plate_records",
        keywords=[
            "车牌", "车牌号", "车牌记录", "车辆牌照",
            "记录了多少辆车", "车牌信息",
        ],
        few_shot_examples=FEW_SHOT_EXAMPLES,
        summary_prompt=SUMMARY_PROMPT,
        priority=5,
    )
    skill_registry.register(hints)


def unregister_plate_records_skill():
    """注销车牌记录技能提示"""
    skill_registry.unregister("query_plate_records")