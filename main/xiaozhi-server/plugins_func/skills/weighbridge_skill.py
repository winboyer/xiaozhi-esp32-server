"""地磅数据分析技能提示注册"""

from datetime import datetime, timedelta
from .base import SkillHints
from .registry import skill_registry


def _build_examples() -> list:
    """动态构建 few-shot 示例（含时间信息）"""
    now = datetime.now()
    today_end = now.strftime("%Y-%m-%d") + " 23:59:59"
    yesterday_end = (now - timedelta(days=1)).strftime("%Y-%m-%d") + " 23:59:59"
    last_week_end = (now - timedelta(days=now.weekday() + 1)).strftime("%Y-%m-%d") + " 23:59:59"

    return [
        "```\n用户: 分析地磅数据\n"
        '返回: {"function_call": {"name": "analyze_weighbridge_data", "arguments": {"project_id": "sanyuanli"}}}\n'
        "```",
        "```\n用户: 分析三元里地磅数据\n"
        '返回: {"function_call": {"name": "analyze_weighbridge_data", "arguments": {"project_id": "sanyuanli"}}}\n'
        "```",
        "```\n用户: 看看地磅最近一周数据\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"query_type": "week", "end_time": "{today_end}"}}}}}}\n'
        "```",
        "```\n用户: 看看地磅本周数据\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"query_type": "week", "end_time": "{today_end}"}}}}}}\n'
        "```",
        "```\n用户: 看看地磅本周数据统计\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"query_type": "week", "end_time": "{today_end}"}}}}}}\n'
        "```",
        "```\n用户: 看看地磅上周数据统计\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"query_type": "week", "end_time": "{last_week_end}"}}}}}}\n'
        "```",
        "```\n用户: 查询三元里今天地磅数据\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"project_id": "sanyuanli", "query_type": "day", "end_time": "{today_end}"}}}}}}\n'
        "```",
        "```\n用户: 查询三元里昨天地磅数据\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"project_id": "sanyuanli", "query_type": "day", "end_time": "{yesterday_end}"}}}}}}\n'
        "```",
        "```\n用户: 三元里今天运了多少车\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"project_id": "sanyuanli", "query_type": "day", "end_time": "{today_end}"}}}}}}\n'
        "```",
        "```\n用户: 看看最近一周的运输情况\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"query_type": "week", "end_time": "{today_end}"}}}}}}\n'
        "```",
        "```\n用户: 查下三元里最近的车辆进出\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"project_id": "sanyuanli", "query_type": "week", "end_time": "{today_end}"}}}}}}\n'
        "```",
        "```\n用户: 今天工地上了多少土方\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"query_type": "day", "end_time": "{today_end}"}}}}}}\n'
        "```",
        "```\n用户: 地磅本周总共多少吨\n"
        f'返回: {{"function_call": {{"name": "analyze_weighbridge_data", "arguments": {{"query_type": "week", "end_time": "{today_end}"}}}}}}\n'
        "```",
    ]


SUMMARY_PROMPT = """你是一个专业的地磅数据分析助手。请根据以下地磅数据生成一段简洁、口语化的总结回复。

数据内容：
{data}

要求：
1. 用口语化、自然的语言描述数据情况，像人类员工汇报工作一样
2. 突出关键数字：总车次、总重量、平均重量、最活跃车辆、高峰日
3. 如果数据中有每日统计，简要说明趋势（哪几天比较多）
4. 如果用户问的是特定项目（如三元里），在回复中提及项目名称
5. 回复长度控制在50-150字，简洁明了
6. 不要使用任何 Markdown 格式（如 **、- 列表等），纯文本回复
7. 不要添加「根据数据分析」「查询结果显示」等套话，直接说结果

请直接返回总结文本："""


def register_weighbridge_skill():
    """注册地磅数据技能提示"""
    hints = SkillHints(
        function_name="analyze_weighbridge_data",
        keywords=[
            "地磅", "车辆统计", "运输统计", "过磅", "车次",
            "土方", "运输情况", "车辆进出", "运了",
        ],
        few_shot_examples=_build_examples(),
        summary_prompt=SUMMARY_PROMPT,
        priority=10,  # 地磅数据是核心数据源，高优先级
    )
    skill_registry.register(hints)


def unregister_weighbridge_skill():
    """注销地磅数据技能提示"""
    skill_registry.unregister("analyze_weighbridge_data")