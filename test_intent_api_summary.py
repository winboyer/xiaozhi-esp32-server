import pytest

from intent_api_server import _strip_reasoning


def test_strip_reasoning_keeps_only_final_answer():
    text = "我先粗略分析一下：渗压=0.34kPa(0.11~0.46)，正常。"
    assert _strip_reasoning(text) == "渗压=0.34kPa(0.11~0.46)，正常。"
