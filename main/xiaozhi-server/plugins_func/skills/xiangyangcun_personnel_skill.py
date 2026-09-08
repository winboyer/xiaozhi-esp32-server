"""向阳村项目人员数据查询技能提示注册"""

from .base import SkillHints
from .registry import skill_registry


def _build_examples() -> list:
    """动态构建 few-shot 示例"""
    return [
        "```\n用户: 查询向阳村今天人员总览\n"
        '返回: {"function_call": {"name": "query_xiangyangcun_personnel", "arguments": {"query": "查询今天人员总览"}}}\n'
        "```",
        "```\n用户: 向阳村今天班组出勤情况\n"
        '返回: {"function_call": {"name": "query_xiangyangcun_personnel", "arguments": {"query": "今天班组出勤情况"}}}\n'
        "```",
        "```\n用户: 查询在场人员的位置分布\n"
        '返回: {"function_call": {"name": "query_xiangyangcun_personnel", "arguments": {"query": "查询在场人员的位置分布"}}}\n'
        "```",
        "```\n用户: 向阳村人员定位24小时走势\n"
        '返回: {"function_call": {"name": "query_xiangyangcun_personnel", "arguments": {"query": "人员定位24小时走势"}}}\n'
        "```",
        "```\n用户: 今天的考勤统计\n"
        '返回: {"function_call": {"name": "query_xiangyangcun_personnel", "arguments": {"query": "今天的考勤统计"}}}\n'
        "```",
    ]


SUMMARY_PROMPT = """你是一个向阳村项目人员数据助手。请根据以下向阳村项目人员数据生成一段简洁、口语化的总结回复。

数据内容：
{data}

要求：
1. 用口语化、自然的语言汇报人员数据情况，像向领导汇报一样
2. 先给结论，再列关键数字（人数、出勤率、区域分布等）
3. 如果数据中有位置分布（location_distribution），必须重点按区域逐一汇报各区人数（如「2#楼1F有19人、4F有18人」），不要只报总数、不要遗漏区域
4. 回复控制在150字以内，简洁明了
5. 不要使用任何 Markdown 格式，纯文本回复
6. 不要添加「根据数据分析」等套话，直接说结果

请直接返回总结文本："""


def register_xiangyangcun_personnel_skill():
    """注册向阳村项目人员数据查询技能提示"""
    hints = SkillHints(
        function_name="query_xiangyangcun_personnel",
        keywords=[
            "人员总览", "在场人数", "人数概览", "人员分布",
            "班组出勤", "考勤", "人员定位", "位置分布", "区域分布",
            "人员库", "作业面人员", "出勤率", "人员时间分布",
        ],
        few_shot_examples=_build_examples(),
        summary_prompt=SUMMARY_PROMPT,
        priority=9,
    )
    skill_registry.register(hints)


def unregister_xiangyangcun_personnel_skill():
    """注销向阳村项目人员数据查询技能提示"""
    skill_registry.unregister("query_xiangyangcun_personnel")
