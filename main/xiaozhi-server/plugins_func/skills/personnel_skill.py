"""人员数据分析技能提示注册"""

from .base import SkillHints
from .registry import skill_registry


FEW_SHOT_EXAMPLES = [
    "```\n用户: 三元里现在有多少工人\n"
    '返回: {"function_call": {"name": "analyze_personnel_data", "arguments": {"location": "三元里"}}}\n'
    "```",
    "```\n用户: 查看三元里现场人员状态\n"
    '返回: {"function_call": {"name": "analyze_personnel_data", "arguments": {"location": "三元里"}}}\n'
    "```",
    "```\n用户: 三元里安全帽佩戴率怎么样\n"
    '返回: {"function_call": {"name": "analyze_personnel_data", "arguments": {"location": "三元里"}}}\n'
    "```",
    "```\n用户: 将军祠现在有多少工人\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "将军祠现在有多少工人"}}}\n'
    "```",
    "```\n用户: 查询将军祠人员总览\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "查询将军祠人员总览"}}}\n'
    "```",
]

SUMMARY_PROMPT = """你是一个工地现场人员管理助手。请根据以下人员统计数据生成一段简洁、口语化的总结回复。

数据内容：
{data}

要求：
1. 用口语化的语言报告现场人员情况，像现场管理员汇报一样
2. 突出关键数字：在场人数、今日进出人次
3. 如果有工种分布，简要说明主要工种和人数
4. 如果有安全帽佩戴数据，提及佩戴率和是否达标
5. 回复长度控制在50-100字，简洁明了
6. 不要使用任何 Markdown 格式（如 **、- 列表等），纯文本回复
7. 不要添加「根据数据分析」等套话

请直接返回总结文本："""


def register_personnel_skill():
    """注册人员数据技能提示"""
    hints = SkillHints(
        function_name="analyze_personnel_data",
        keywords=[
            "三元里",
        ],
        few_shot_examples=FEW_SHOT_EXAMPLES,
        summary_prompt=SUMMARY_PROMPT,
        priority=8,  # 人员数据优先级
    )
    skill_registry.register(hints)


def unregister_personnel_skill():
    """注销人员数据技能提示"""
    skill_registry.unregister("analyze_personnel_data")