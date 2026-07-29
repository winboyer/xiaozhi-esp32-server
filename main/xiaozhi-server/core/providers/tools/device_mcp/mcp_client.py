"""设备端MCP客户端定义"""

import asyncio
from concurrent.futures import Future
from core.utils.util import sanitize_tool_name
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

# ---------------------------------------------------------------------------
# 默认设备 MCP 工具定义（服务启动时预注册，无需等待设备 tools/list 响应）
# 与 digital-human/js/config/default-mcp-tools.json 保持同步
# ---------------------------------------------------------------------------
DEFAULT_DEVICE_MCP_TOOLS = [
    {
        "name": "self.audio_speaker.set_volume",
        "description": (
            "Set the volume of the audio speaker (0-100). "
            "Call this tool directly when user wants to adjust volume. "
            "Example: user says '音量调到80' → call with volume=80."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"volume": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["volume"],
        },
    },
    {
        "name": "self.get_device_status",
        "description": (
            "查询设备的实时状态信息，包括扬声器音量、屏幕亮度、电池电量、网络连接等。"
            "仅在用户明确询问设备状态时调用（如：当前音量多少、电量还有多少、屏幕亮度是多少），"
            "不要作为设备控制的前置步骤。"
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "self.screen.set_brightness",
        "description": (
            "设置屏幕亮度（0-100）。"
            "用户说「屏幕亮度调到X」「亮度高一点」「亮度低一点」时直接调用此工具。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"brightness": {"type": "integer", "minimum": 0, "maximum": 100}},
            "required": ["brightness"],
        },
    },
]


class MCPClient:
    """设备端MCP客户端，用于管理MCP状态和工具"""

    def __init__(self):
        self.tools = {}  # sanitized_name -> tool_data
        self.name_mapping = {}
        self.ready = False
        self.call_results = {}  # To store Futures for tool call responses
        self.next_id = 1
        self.lock = asyncio.Lock()
        self._cached_available_tools = None  # Cache for get_available_tools

    def register_default_tools(self):
        """预注册默认设备 MCP 工具，确保 LLM 始终可见，不依赖设备 tools/list 响应时序"""
        for tool_data in DEFAULT_DEVICE_MCP_TOOLS:
            sanitized_name = sanitize_tool_name(tool_data["name"])
            if sanitized_name not in self.tools:
                self.tools[sanitized_name] = dict(tool_data)
                self.name_mapping[sanitized_name] = tool_data["name"]
        self._cached_available_tools = None
        logger.bind(tag=TAG).info(
            f"预注册 {len(DEFAULT_DEVICE_MCP_TOOLS)} 个默认设备 MCP 工具: "
            f"{[t['name'] for t in DEFAULT_DEVICE_MCP_TOOLS]}"
        )

    def has_tool(self, name: str) -> bool:
        return name in self.tools

    def get_available_tools(self) -> list:
        # Check if the cache is valid
        if self._cached_available_tools is not None:
            return self._cached_available_tools

        # If cache is not valid, regenerate the list
        result = []
        for tool_name, tool_data in self.tools.items():
            function_def = {
                "name": tool_name,
                "description": tool_data["description"],
                "parameters": {
                    "type": tool_data["inputSchema"].get("type", "object"),
                    "properties": tool_data["inputSchema"].get("properties", {}),
                    "required": tool_data["inputSchema"].get("required", []),
                },
            }
            result.append({"type": "function", "function": function_def})

        self._cached_available_tools = result  # Store the generated list in cache
        return result

    async def is_ready(self) -> bool:
        async with self.lock:
            return self.ready

    async def set_ready(self, status: bool):
        async with self.lock:
            self.ready = status

    async def add_tool(self, tool_data: dict):
        async with self.lock:
            sanitized_name = sanitize_tool_name(tool_data["name"])
            self.tools[sanitized_name] = tool_data
            self.name_mapping[sanitized_name] = tool_data["name"]
            self._cached_available_tools = (
                None  # Invalidate the cache when a tool is added
            )

    async def get_next_id(self) -> int:
        async with self.lock:
            current_id = self.next_id
            self.next_id += 1
            return current_id

    async def register_call_result_future(self, id: int, future: Future):
        async with self.lock:
            self.call_results[id] = future

    async def resolve_call_result(self, id: int, result: any):
        async with self.lock:
            if id in self.call_results:
                future = self.call_results.pop(id)
                if not future.done():
                    future.set_result(result)

    async def reject_call_result(self, id: int, exception: Exception):
        async with self.lock:
            if id in self.call_results:
                future = self.call_results.pop(id)
                if not future.done():
                    future.set_exception(exception)

    async def cleanup_call_result(self, id: int):
        async with self.lock:
            if id in self.call_results:
                self.call_results.pop(id)
