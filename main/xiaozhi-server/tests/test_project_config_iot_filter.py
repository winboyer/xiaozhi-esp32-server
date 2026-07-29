import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.project_config import ProjectName, apply_project_filter
from core.providers.tools.base import ToolDefinition, ToolType


class DummyToolManager:
    def __init__(self):
        self._cached_tools = {
            "get_weather": ToolDefinition(
                name="get_weather",
                description={"function": {"name": "get_weather"}},
                tool_type=ToolType.SERVER_PLUGIN,
            ),
            "get_battery_level": ToolDefinition(
                name="get_battery_level",
                description={"function": {"name": "get_battery_level"}},
                tool_type=ToolType.DEVICE_IOT,
            ),
        }
        self._cached_function_descriptions = [
            {"function": {"name": "get_weather"}},
            {"function": {"name": "get_battery_level"}},
        ]
        self._project_allowed_tools = None
        self._refresh_tools_patched = False

    def get_all_tools(self):
        return self._cached_tools

    def refresh_tools(self):
        return None


def test_apply_project_filter_removes_device_iot_tools_in_chaobaihe_mode():
    tool_manager = DummyToolManager()
    conn = SimpleNamespace(
        config={"project": ProjectName.CHAOBAIHE},
        func_handler=SimpleNamespace(tool_manager=tool_manager),
    )

    with patch("core.project_config._setup_chaobaihe_mode"):
        apply_project_filter(conn)

    available_tools = set(tool_manager._cached_tools.keys())
    assert "get_weather" in available_tools
    assert "get_battery_level" not in available_tools
