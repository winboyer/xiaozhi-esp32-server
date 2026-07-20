"""
技能提示注册框架 (Skill Hints Framework)

允许每个插件函数模块注册自己的意图匹配提示（关键词、few-shot 示例、摘要提示词），
intent_llm 模块在构建系统提示词时动态收集所有已注册的技能提示。
"""

from .base import SkillHints, SkillRegistry
from .registry import skill_registry

__all__ = ["SkillHints", "SkillRegistry", "skill_registry"]