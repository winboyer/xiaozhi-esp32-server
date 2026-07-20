"""技能提示数据模型定义"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SkillHints:
    """
    单个技能（函数）向 LLM 意图识别提供的核心提示信息。

    Attributes:
        function_name: 对应的函数名，例如 analyze_weighbridge_data
        keywords: 触发该函数的关键词/词组列表，例如 ["地磅", "车辆统计", "运输统计"]
        few_shot_examples: few-shot 示例列表，每个元素是 "(用户输入, LLM返回JSON)" 元组
        summary_prompt: 当数据返回后需要 LLM 做智能总结时的提示词模板，可包含 {data} 占位符
        priority: 匹配优先级，数值越大越优先（用于同类数据源存在子类型时的排序）
    """
    function_name: str
    keywords: List[str] = field(default_factory=list)
    few_shot_examples: List[str] = field(default_factory=list)
    summary_prompt: Optional[str] = None
    priority: int = 0


@dataclass
class SkillRegistry:
    """技能提示注册中心"""

    _skills: dict = field(default_factory=dict)  # function_name -> SkillHints

    def register(self, hints: SkillHints) -> None:
        """注册一个技能提示"""
        self._skills[hints.function_name] = hints

    def unregister(self, function_name: str) -> None:
        """注销一个技能提示"""
        self._skills.pop(function_name, None)

    def get(self, function_name: str) -> Optional[SkillHints]:
        """获取指定函数的技能提示"""
        return self._skills.get(function_name)

    def get_all(self) -> dict:
        """获取所有已注册的技能提示"""
        return self._skills.copy()

    def build_keyword_table(self) -> str:
        """
        构建关键词模糊匹配规则表，用于注入 LLM 系统提示词。

        格式：每行 "- 关键词1、关键词2 → 函数描述 → 函数名"
        """
        if not self._skills:
            return ""

        lines = []
        for _, hints in sorted(
            self._skills.items(), key=lambda x: x[1].priority, reverse=True
        ):
            if not hints.keywords:
                continue
            kw_str = "、".join(hints.keywords)
            # 取描述的前半句作为简短说明，避免过长
            lines.append(f"- {kw_str} → {hints.function_name}")

        if not lines:
            return ""

        return "\n".join(lines)

    def build_few_shot_examples(self) -> str:
        """构建所有技能的 few-shot 示例组合"""
        examples = []
        for _, hints in sorted(
            self._skills.items(), key=lambda x: x[1].priority, reverse=True
        ):
            if hints.few_shot_examples:
                examples.extend(hints.few_shot_examples)
        return "\n".join(examples)

    def get_summary_prompt(self, function_name: str) -> Optional[str]:
        """获取指定函数的摘要提示词（用于 REQLLM 模式）"""
        hints = self._skills.get(function_name)
        return hints.summary_prompt if hints else None