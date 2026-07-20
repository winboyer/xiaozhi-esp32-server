"""楼栋施工进度查询技能提示注册"""

from .base import SkillHints
from .registry import skill_registry

FEW_SHOT_EXAMPLES = [
    "```\n用户: 查询全部楼栋施工进度\n"
    '返回: {"function_call": {"name": "query_building_progress", "arguments": {}}}\n'
    "```",
    "```\n用户: 查询1号楼施工进度\n"
    '返回: {"function_call": {"name": "query_building_progress", "arguments": {"building_name": "1号楼"}}}\n'
    "```",
    "```\n用户: 楼栋施工进度\n"
    '返回: {"function_call": {"name": "query_building_progress", "arguments": {}}}\n'
    "```",
    "```\n用户: 查询2号楼当前施工到第几层\n"
    '返回: {"function_call": {"name": "query_building_progress", "arguments": {"building_name": "2号楼"}}}\n'
    "```",
]

SUMMARY_PROMPT = """你是一个工地数据查询助手。请根据以下楼栋施工进度数据生成一段简洁、口语化的总结回复。

数据内容：
{data}

要求：
1. 用口语化、自然的语言描述各楼栋的施工进度，像向领导汇报一样
2. 列出每栋楼的名称、当前施工楼层和总楼层
3. 区分已开始施工和尚未开工的楼栋
4. 如果用户指定了特定楼栋，只汇报该楼栋的信息
5. 回复长度控制在50-150字，简洁明了
6. 不要使用任何 Markdown 格式，纯文本回复
7. 不要添加「根据数据分析」等套话，直接说结果

请直接返回总结文本："""


def register_building_progress_skill():
    """注册楼栋施工进度查询技能提示"""
    hints = SkillHints(
        function_name="query_building_progress",
        keywords=[
            "楼栋施工进度", "施工进度", "施工到第几层",
            "建到几层", "盖到几层", "楼层施工",
        ],
        few_shot_examples=FEW_SHOT_EXAMPLES,
        summary_prompt=SUMMARY_PROMPT,
        priority=8,
    )
    skill_registry.register(hints)


def unregister_building_progress_skill():
    """注销楼栋施工进度查询技能提示"""
    skill_registry.unregister("query_building_progress")