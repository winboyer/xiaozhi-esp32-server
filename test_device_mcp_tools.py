"""
测试 OTA 设备 MCP 工具调用链路：
1. self.audio_speaker.set_volume  → 音量调节（0-100）
2. self.get_device_status         → 查询设备状态（音量/电池/网络/屏幕）
3. self.screen.set_brightness     → 屏幕亮度调节（0-100）

验证：
- 工具名模糊匹配（. _ - 分隔符丢失/变化）
- MCPClient 工具注册 → name_mapping 映射
- DeviceMCPExecutor._resolve_mcp_tool_name 解析
- ToolManager 模糊查找

用法：
    cd main/xiaozhi-server
    python ../test_device_mcp_tools.py
"""

import sys
import os
import re
import json

# 确保 xiaozhi-server 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "main", "xiaozhi-server"))


def sanitize_tool_name(name: str) -> str:
    """与 core.utils.util.sanitize_tool_name 一致"""
    return re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "_", name)

# ---------------------------------------------------------------------------
# 模拟 MCPClient（不依赖真实连接）
# ---------------------------------------------------------------------------
class MockMCPClient:
    """模拟设备端 MCP 客户端"""

    def __init__(self):
        self.tools = {}  # sanitized_name → tool_data
        self.name_mapping = {}  # sanitized_name → original_name
        self.ready = True

    def has_tool(self, name: str) -> bool:
        return name in self.tools

    def add_tool(self, name: str, description: str, input_schema: dict = None):
        """添加工具，模拟设备 MCP 注册流程"""
        sanitized = sanitize_tool_name(name)
        tool_data = {
            "name": name,
            "description": description,
            "inputSchema": input_schema or {"type": "object", "properties": {}, "required": []},
        }
        self.tools[sanitized] = tool_data
        self.name_mapping[sanitized] = name

    def get_available_tools(self) -> list:
        result = []
        for tool_name, tool_data in self.tools.items():
            result.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_data["description"],
                    "parameters": tool_data["inputSchema"],
                },
            })
        return result


# ---------------------------------------------------------------------------
# 注册三个 MCP 工具（模拟设备端注册）
# ---------------------------------------------------------------------------
def register_device_mcp_tools():
    """模拟 ESP32 设备注册 MCP 工具"""
    client = MockMCPClient()

    # 1. 音量调节
    client.add_tool(
        "self.audio_speaker.set_volume",
        "Set the volume of the audio speaker. If the current volume is unknown, "
        "you must call `self.get_device_status` tool first and then call this tool.",
        {
            "type": "object",
            "properties": {
                "volume": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "required": ["volume"],
        },
    )

    # 2. 设备状态查询
    client.add_tool(
        "self.get_device_status",
        "Provides the real-time information of the device, including the current "
        "status of the audio speaker, screen, battery, network, etc.",
        {"type": "object", "properties": {}},
    )

    # 3. 屏幕亮度调节
    client.add_tool(
        "self.screen.set_brightness",
        "Set the brightness of the screen.",
        {
            "type": "object",
            "properties": {
                "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "required": ["brightness"],
        },
    )

    return client


# ---------------------------------------------------------------------------
# 测试 _resolve_mcp_tool_name（从 mcp_executor.py 复制逻辑）
# ---------------------------------------------------------------------------
def _strip(name: str) -> str:
    return name.replace("_", "").replace("-", "").replace(".", "").lower()


def resolve_mcp_tool_name(mcp_client, tool_name: str) -> str:
    """将任意格式的工具名解析为 MCP 客户端中实际注册的名称"""
    # 精确匹配
    if mcp_client.has_tool(tool_name):
        return tool_name

    stripped_input = _strip(tool_name)

    # 遍历 MCP 客户端中所有已注册工具
    for registered_name in mcp_client.tools.keys():
        if _strip(registered_name) == stripped_input:
            return registered_name

    # 尝试 reverse lookup：name_mapping 中 original_name 可能匹配
    for sanitized_name, original_name in mcp_client.name_mapping.items():
        if _strip(original_name) == stripped_input:
            return sanitized_name

    return tool_name


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------
def test_tool_resolution():
    """测试工具名解析"""
    client = register_device_mcp_tools()

    print("=" * 70)
    print("设备 MCP 工具注册表:")
    for sanitized, original in client.name_mapping.items():
        print(f"  {sanitized}  →  {original}")
    print()

    # 定义测试用例: (输入名, 期望解析后的 sanitized 名, 场景描述)
    test_cases = [
        # ---- self.audio_speaker.set_volume ----
        ("self_audio_speaker_set_volume", "self_audio_speaker_set_volume", "LLM 返回 sanitized 名"),
        ("self.audio_speaker.set_volume", "self_audio_speaker_set_volume", "LLM 返回原始名(带点号)"),
        ("selfaudiospeakersetvolume", "self_audio_speaker_set_volume", "LLM 丢失所有分隔符"),
        ("selfAudioSpeakerSetVolume", "self_audio_speaker_set_volume", "LLM 驼峰无分隔符"),
        # ---- self.get_device_status ----
        ("self_get_device_status", "self_get_device_status", "LLM 返回 sanitized 名"),
        ("self.get_device_status", "self_get_device_status", "LLM 返回原始名(带点号)"),
        ("selfgetdevicestatus", "self_get_device_status", "LLM 丢失所有分隔符"),
        # ---- self.screen.set_brightness ----
        ("self_screen_set_brightness", "self_screen_set_brightness", "LLM 返回 sanitized 名"),
        ("self.screen.set_brightness", "self_screen_set_brightness", "LLM 返回原始名(带点号)"),
        ("selfscreensetbrightness", "self_screen_set_brightness", "LLM 丢失所有分隔符"),
    ]

    all_passed = True
    for input_name, expected, desc in test_cases:
        result = resolve_mcp_tool_name(client, input_name)
        passed = result == expected
        status = "✅" if passed else "❌"
        if not passed:
            all_passed = False
        print(f"  {status} {desc}")
        print(f"     输入: {input_name}")
        print(f"     期望: {expected}")
        print(f"     结果: {result}")
        print()

    return all_passed


def test_tool_availability_and_routing():
    """测试工具在 ToolManager 级别的可用性和路由"""
    client = register_device_mcp_tools()

    # 模拟 DeviceMCPExecutor.get_tools()
    tools = {}
    for tool in client.get_available_tools():
        func_def = tool.get("function", {})
        name = func_def.get("name", "")
        if name:
            tools[name] = {"name": name, "description": tool}

    print("=" * 70)
    print("ToolManager 级别工具注册表:")
    for name in sorted(tools.keys()):
        print(f"  {name}")
    print()

    # 模拟 ToolManager.get_tool_type 精确查找
    test_names = [
        "self_audio_speaker_set_volume",
        "self_get_device_status",
        "self_screen_set_brightness",
    ]

    all_found = True
    for name in test_names:
        found = name in tools
        status = "✅" if found else "❌"
        if not found:
            all_found = False
        print(f"  {status} 精确匹配: {name} → {'找到' if found else '未找到'}")

    # 模拟 ToolManager._fuzzy_find_tool 模糊查找
    fuzzy_cases = {
        "selfaudiospeakersetvolume": "self_audio_speaker_set_volume",
        "selfgetdevicestatus": "self_get_device_status",
        "selfscreensetbrightness": "self_screen_set_brightness",
    }

    print()
    print("模糊匹配测试 (ToolManager._fuzzy_find_tool):")
    for fuzzy_name, expected in fuzzy_cases.items():
        normalized_input = _strip(fuzzy_name)
        matched = None
        for name in tools:
            if _strip(name) == normalized_input:
                matched = name
                break
        passed = matched == expected
        status = "✅" if passed else "❌"
        if not passed:
            all_found = False
        print(f"  {status} '{fuzzy_name}' → '{matched}' (期望: '{expected}')")

    return all_found


def test_name_mapping_for_mcp_call():
    """测试发送到设备时的名称映射（name_mapping 还原原始名）"""
    client = register_device_mcp_tools()

    print("=" * 70)
    print("MCP 调用时的名称还原 (name_mapping):")

    test_cases = [
        ("self_audio_speaker_set_volume", "self.audio_speaker.set_volume", {"volume": 80}),
        ("self_get_device_status", "self.get_device_status", {}),
        ("self_screen_set_brightness", "self.screen.set_brightness", {"brightness": 80}),
    ]

    all_passed = True
    for sanitized, expected_original, args in test_cases:
        actual_original = client.name_mapping.get(sanitized, sanitized)
        passed = actual_original == expected_original
        status = "✅" if passed else "❌"
        if not passed:
            all_passed = False

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": actual_original, "arguments": args},
        }
        import json
        print(f"  {status} {sanitized}")
        print(f"     → 设备名: {actual_original}")
        print(f"     → 发送: {json.dumps(payload, ensure_ascii=False)}")
        print()

    return all_passed


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║       OTA 设备 MCP 工具调用链路测试                              ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    results = {}

    print("【测试 1】_resolve_mcp_tool_name 工具名解析")
    results["resolve"] = test_tool_resolution()

    print("【测试 2】ToolManager 工具注册与模糊匹配")
    results["routing"] = test_tool_availability_and_routing()

    print("【测试 3】name_mapping 原始名还原 (call_mcp_tool)")
    results["mapping"] = test_name_mapping_for_mcp_call()

    print("=" * 70)
    print("测试汇总:")
    for name, passed in results.items():
        print(f"  {'✅' if passed else '❌'} {name}")
    print()

    all_passed = all(results.values())
    if all_passed:
        print("🎉 所有测试通过！三个 MCP 工具调用链路正常。")
    else:
        print("❌ 存在失败用例，请检查。")

    sys.exit(0 if all_passed else 1)
