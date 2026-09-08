"""塔机历史作业状态查询技能提示注册"""

from .base import SkillHints
from .registry import skill_registry


def _build_examples() -> list:
    """动态构建 few-shot 示例"""
    return [
        "```\n用户: 查询向阳村4#塔机的作业状态\n"
        '返回: {"function_call": {"name": "query_taji_work_status", "arguments": {"device_name": "向阳村4#塔机"}}}\n'
        "```",
        "```\n用户: 塔机2今天干了多少活\n"
        '返回: {"function_call": {"name": "query_taji_work_status", "arguments": {"device_name": "向阳村2#塔机"}}}\n'
        "```",
        "```\n用户: 查询所有塔机的作业情况\n"
        '返回: {"function_call": {"name": "query_taji_work_status", "arguments": {}}}\n'
        "```",
        "```\n用户: 4#塔机有没有在作业\n"
        '返回: {"function_call": {"name": "query_taji_work_status", "arguments": {"device_name": "向阳村4#塔机"}}}\n'
        "```",
        "```\n用户: 向阳村3#塔机作业次数\n"
        '返回: {"function_call": {"name": "query_taji_work_status", "arguments": {"device_name": "向阳村3#塔机"}}}\n'
        "```",
    ]


SUMMARY_PROMPT = """你是一个工地塔机作业监控助手。请根据以下塔机历史作业状态数据生成一段简洁、口语化的总结回复。

数据内容：
{data}

要求：
1. 用口语化、自然的语言描述各塔机的作业情况，像向领导汇报一样
2. 汇报每台塔机的作业次数（work_cycle_count），以及是否有作业记录
3. 如果有最近作业记录，说明最近一次作业的时间范围，以及关键参数（如吊重 weight、最大力矩 max_torque、最大高度 max_height）
4. 如果用户指定了特定塔机名称，只汇报该塔机的信息
5. 如果某台塔机查询范围内无作业记录，如实说明，不要编造数据
6. 回复控制在200字以内，简洁明了
7. 不要使用任何 Markdown 格式，纯文本回复
8. 不要添加「根据数据分析」等套话，直接说结果

请直接返回总结文本："""


def register_taji_work_status_skill():
    """注册塔机历史作业状态查询技能提示"""
    hints = SkillHints(
        function_name="query_taji_work_status",
        keywords=[
            "作业状态", "作业情况", "作业次数", "作业记录",
            "干了多少活", "是否作业", "有没有作业", "塔机作业",
            "塔吊作业", "吊装作业", "工作循环",
        ],
        few_shot_examples=_build_examples(),
        summary_prompt=SUMMARY_PROMPT,
        priority=9,
    )
    skill_registry.register(hints)


def unregister_taji_work_status_skill():
    """注销塔机历史作业状态查询技能提示"""
    skill_registry.unregister("query_taji_work_status")
