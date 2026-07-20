"""塔机静态数据查询技能提示注册"""

from .base import SkillHints
from .registry import skill_registry


def _build_examples() -> list:
    """动态构建 few-shot 示例"""
    return [
        "```\n用户: 查询塔机安装高度\n"
        '返回: {"function_call": {"name": "query_taji_height", "arguments": {}}}\n'
        "```",
        "```\n用户: 查询塔吊安装高度\n"
        '返回: {"function_call": {"name": "query_taji_height", "arguments": {}}}\n'
        "```",
        "```\n用户: 塔机高度是多少\n"
        '返回: {"function_call": {"name": "query_taji_height", "arguments": {}}}\n'
        "```",
        "```\n用户: 塔吊高度\n"
        '返回: {"function_call": {"name": "query_taji_height", "arguments": {}}}\n'
        "```",
        "```\n用户: 查询塔机1的高度\n"
        '返回: {"function_call": {"name": "query_taji_height", "arguments": {"device_name": "塔机1"}}}\n'
        "```",
        "```\n用户: 塔机8安装到多高了\n"
        '返回: {"function_call": {"name": "query_taji_height", "arguments": {"device_name": "塔机8"}}}\n'
        "```",
    ]


SUMMARY_PROMPT = """你是一个专业的塔机设备数据查询助手。请根据以下塔机安装高度数据生成一段简洁、口语化的总结回复。

数据内容：
{data}

要求：
1. 用口语化、自然的语言描述各塔机的安装高度情况，像向领导汇报一样
2. 列出每台塔机的名称和当前安装高度
3. 如果用户指定了特定塔机名称，只汇报该塔机的信息
4. 如果数据中有在线状态，标注哪些塔机在线、哪些离线
5. 回复长度控制在50-150字，简洁明了
6. 不要使用任何 Markdown 格式，纯文本回复
7. 不要添加「根据数据分析」等套话，直接说结果

请直接返回总结文本："""


def register_taji_static_skill():
    """注册塔机静态数据查询技能提示"""
    hints = SkillHints(
        function_name="query_taji_height",
        keywords=[
            "塔机", "塔吊", "安装高度", "塔机高度",
            "塔吊高度", "安装到多高", "吊塔",
        ],
        few_shot_examples=_build_examples(),
        summary_prompt=SUMMARY_PROMPT,
        priority=8,
    )
    skill_registry.register(hints)


def unregister_taji_static_skill():
    """注销塔机静态数据查询技能提示"""
    skill_registry.unregister("query_taji_height")