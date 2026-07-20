"""天气查询技能提示注册"""

from .base import SkillHints
from .registry import skill_registry


def _build_examples() -> list:
    """构建天气查询 few-shot 示例"""
    return [
        "```\n用户: 今天天气怎么样\n"
        '返回: {"function_call": {"name": "get_weather", "arguments": {}}}\n'
        "```",
        "```\n用户: 广州今天天气\n"
        '返回: {"function_call": {"name": "get_weather", "arguments": {"location": "广州"}}}\n'
        "```",
        "```\n用户: 明天会下雨吗\n"
        '返回: {"function_call": {"name": "get_weather", "arguments": {}}}\n'
        "```",
        "```\n用户: 北京今天温度多少\n"
        '返回: {"function_call": {"name": "get_weather", "arguments": {"location": "北京"}}}\n'
        "```",
        "```\n用户: 查一下天气\n"
        '返回: {"function_call": {"name": "get_weather", "arguments": {}}}\n'
        "```",
    ]


def register_weather_skill():
    """注册天气查询技能提示"""
    hints = SkillHints(
        function_name="get_weather",
        keywords=[
            "天气", "下雨", "温度", "气温", "晴天", "阴天",
            "多云", "刮风", "台风", "暴雨", "下雪", "雾霾",
            "冷不冷", "热不热", "会不会下雨", "天气预报",
        ],
        few_shot_examples=_build_examples(),
        summary_prompt=None,  # get_weather 内部已有完整的天气报告文本，无需额外总结
        priority=5,
    )
    skill_registry.register(hints)


def unregister_weather_skill():
    """注销天气查询技能提示"""
    skill_registry.unregister("get_weather")