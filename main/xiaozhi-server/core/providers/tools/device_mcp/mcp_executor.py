"""设备端MCP工具执行器"""

from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from ..base import ToolType, ToolDefinition, ToolExecutor
from plugins_func.register import Action, ActionResponse
from .mcp_handler import call_mcp_tool
from config.logger import setup_logging

logger = setup_logging()


def _resolve_mcp_tool_name(mcp_client, tool_name: str) -> str:
    """将任意格式的工具名解析为 MCP 客户端中实际注册的名称。
    
    处理 LLM 可能丢失分隔符（. _ -）的情况：
    self.audio_speaker.set_volume / self_audio_speaker_set_volume / selfaudiospeakersetvolume
    → self_audio_speaker_set_volume
    """
    # 精确匹配
    if mcp_client.has_tool(tool_name):
        return tool_name

    # 标准化：移除所有分隔符后对比
    def _strip(name: str) -> str:
        return name.replace("_", "").replace("-", "").replace(".", "").lower()

    stripped_input = _strip(tool_name)

    # 遍历 MCP 客户端中所有已注册工具
    for registered_name in mcp_client.tools.keys():
        if _strip(registered_name) == stripped_input:
            return registered_name

    # 尝试 reverse lookup：name_mapping 中 original_name 可能匹配
    for sanitized_name, original_name in mcp_client.name_mapping.items():
        if _strip(original_name) == stripped_input:
            return sanitized_name

    # 都找不到，返回原始名称（后续 call_mcp_tool 会报清晰的错误）
    return tool_name


class DeviceMCPExecutor(ToolExecutor):
    """设备端MCP工具执行器"""

    def __init__(self, conn):
        self.conn = conn

    async def execute(
        self, conn: "ConnectionHandler", tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行设备端MCP工具"""
        if not hasattr(conn, "mcp_client") or not conn.mcp_client:
            return ActionResponse(
                action=Action.ERROR,
                response="设备端MCP客户端未初始化",
            )

        if not await conn.mcp_client.is_ready():
            return ActionResponse(
                action=Action.ERROR,
                response="设备端MCP客户端未准备就绪",
            )

        try:
            import json

            args_str = json.dumps(arguments) if arguments else "{}"

            # 将 LLM 返回的工具名解析为 MCP 客户端实际注册的名称
            resolved_name = _resolve_mcp_tool_name(conn.mcp_client, tool_name)
            if resolved_name != tool_name:
                logger.info(
                    f"设备MCP工具名解析: '{tool_name}' -> '{resolved_name}'"
                )

            # 调用设备端MCP工具
            result = await call_mcp_tool(conn, conn.mcp_client, resolved_name, args_str)

            resultJson = None
            if isinstance(result, str):
                try:
                    resultJson = json.loads(result)
                except Exception as e:
                    pass

            # 视觉大模型不经过二次LLM处理
            if (
                resultJson is not None
                and isinstance(resultJson, dict)
                and "action" in resultJson
            ):
                return ActionResponse(
                    action=Action[resultJson["action"]],
                    response=resultJson.get("response", ""),
                )

            return ActionResponse(action=Action.REQLLM, result=str(result))

        except ValueError as e:
            return ActionResponse(action=Action.NOTFOUND, response=str(e))
        except Exception as e:
            return ActionResponse(action=Action.ERROR, response=str(e))

    def get_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有设备端MCP工具（mcp_client 为空时自动预注册默认工具）"""
        if not hasattr(self.conn, "mcp_client") or not self.conn.mcp_client:
            return {}

        # 兜底：如果 mcp_client.tools 为空（时序问题导致 register_default_tools 未生效），
        # 在此处直接注册默认设备 MCP 工具，确保 LLM 始终可见
        if not self.conn.mcp_client.tools:
            try:
                self.conn.mcp_client.register_default_tools()
            except Exception:
                pass

        tools = {}
        mcp_tools = self.conn.mcp_client.get_available_tools()

        for tool in mcp_tools:
            func_def = tool.get("function", {})
            tool_name = func_def.get("name", "")

            if tool_name:
                tools[tool_name] = ToolDefinition(
                    name=tool_name, description=tool, tool_type=ToolType.DEVICE_MCP
                )

        return tools

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有指定的设备端MCP工具（支持模糊匹配分隔符）"""
        if not hasattr(self.conn, "mcp_client") or not self.conn.mcp_client:
            return False

        resolved = _resolve_mcp_tool_name(self.conn.mcp_client, tool_name)
        # 解析后名称不同说明通过模糊匹配找到了；相同则需要检查精确匹配
        return resolved != tool_name or self.conn.mcp_client.has_tool(tool_name)
