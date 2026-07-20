"""工地安全数据查询技能提示注册"""

from .base import SkillHints
from .registry import skill_registry


FEW_SHOT_EXAMPLES = [
    "```\n用户: 查询今天人员总览\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "查询今天人员总览"}}}\n'
    "```",
    "```\n用户: 查询最近预警记录\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "查询最近预警记录"}}}\n'
    "```",
    "```\n用户: 看看最近告警记录\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "看看最近告警记录"}}}\n'
    "```",
    "```\n用户: 分析今天的班组出勤情况\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "分析今天的班组出勤情况"}}}\n'
    "```",
    "```\n用户: 查下参建单位最近七天的出勤\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "查下参建单位最近七天的出勤"}}}\n'
    "```",
    "```\n用户: 基站物资信息\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "基站物资信息"}}}\n'
    "```",
    "```\n用户: 组织架构\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "组织架构"}}}\n'
    "```",
    "```\n用户: 今天考勤统计\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "今天考勤统计"}}}\n'
    "```",
    "```\n用户: 设备信息统计\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "设备信息统计"}}}\n'
    "```",
    "```\n用户: 查询作业面人员列表\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "查询作业面人员列表"}}}\n'
    "```",
    "```\n用户: 查询人员库\n"
    '返回: {"function_call": {"name": "staff_safe_query", "arguments": {"query": "查询人员库"}}}\n'
    "```",
]


SUMMARY_PROMPT = """你是一个工地安全数据智能分析助手。以下是查询结果的结构化 JSON，你需要将其转为一段口语化、简洁的总结回复。

数据内容：
{data}

注意：
- 输出的 JSON 包含"请求内容"、"请求时间"、"涉及数据"和"返回数据总结"四个字段
- 请直接提取"返回数据总结"字段的内容，用自然、口语化的方式向用户汇报
- 不要照搬 JSON 格式，要像人类汇报工作一样
- 适当简化数据，突出关键信息
- 回复长度控制在 50-150 字
- 不要使用任何 Markdown 格式（如 **、- 列表等），纯文本回复
- 不要添加「根据数据分析」「查询结果显示」等套话，直接说结果

请直接返回总结文本："""


def register_staff_safe_skill():
    """注册工地安全数据查询技能提示"""
    hints = SkillHints(
        function_name="staff_safe_query",
        keywords=[
            "工地安全", "安全数据", "人员总览", "人员分布",
            "班组出勤", "告警记录", "预警", "报警",
            "人员定位", "人员轨迹",
            "基站", "物资信息", "设备统计",
            "人员库", "考勤统计", "组织架构",
            "作业面人员", "参建公司", "参建方",
            "在哪里", "位置查询", "当前所在位置", "多少人", "人员",
        ],
        few_shot_examples=FEW_SHOT_EXAMPLES,
        summary_prompt=SUMMARY_PROMPT,
        priority=9,  # 工地安全数据，高优先级
    )
    skill_registry.register(hints)


def unregister_staff_safe_skill():
    """注销工地安全数据查询技能提示"""
    skill_registry.unregister("staff_safe_query")