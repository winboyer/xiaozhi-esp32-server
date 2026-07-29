"""
数字孪生 WebSocket 连接处理器
处理单个数字孪生客户端的消息收发
"""
import json
import uuid
import asyncio
import logging
from typing import Optional

import websockets

TAG = __name__

# 心跳超时时间（秒）
HEARTBEAT_TIMEOUT = 90
# 心跳间隔建议（秒）
HEARTBEAT_INTERVAL = 30


class DigitalTwinHandler:
    """处理单个数字孪生客户端的 WebSocket 连接"""

    def __init__(
        self,
        websocket: websockets.ServerConnection,
        manager,  # DigitalTwinManager
        logger: logging.Logger,
    ):
        self.websocket = websocket
        self.manager = manager
        self.logger = logger
        self.session_id = str(uuid.uuid4())
        self._last_activity = asyncio.get_event_loop().time()
        self._alive = True

    async def handle(self):
        """主消息循环"""
        # 发送欢迎消息
        await self._send_welcome()

        try:
            async for raw_message in self.websocket:
                self._last_activity = asyncio.get_event_loop().time()
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    await self._send_error("invalid_json", "消息不是有效的 JSON")
                    continue

                msg_type = message.get("type", "")
                if msg_type == "subscribe":
                    await self._handle_subscribe(message)
                elif msg_type == "unsubscribe":
                    await self._handle_unsubscribe(message)
                elif msg_type == "ping":
                    await self._handle_ping()
                else:
                    await self._send_error(
                        "unknown_type", f"未知消息类型: {msg_type}"
                    )
        except websockets.exceptions.ConnectionClosed:
            self.logger.bind(tag=TAG).info("数字孪生客户端断开连接")
        finally:
            await self._cleanup()

    async def send_event(self, event: dict):
        """发送语音交互事件到数字孪生客户端"""
        if not self._alive:
            return
        try:
            await self.websocket.send(json.dumps(event, ensure_ascii=False))
        except websockets.exceptions.ConnectionClosed:
            self._alive = False
            raise

    # ---------- 内部方法 ----------

    async def _send_welcome(self):
        """发送连接确认消息"""
        await self.websocket.send(
            json.dumps(
                {
                    "type": "welcome",
                    "session_id": self.session_id,
                    "timestamp": int(asyncio.get_event_loop().time() * 1000),
                    "version": "xiaozhi-digital-twin-ws.v1",
                },
                ensure_ascii=False,
            )
        )

    async def _handle_subscribe(self, message: dict):
        """处理订阅请求"""
        device_ids = message.get("device_ids", [])
        if not device_ids or not isinstance(device_ids, list):
            await self._send_error("invalid_params", "device_ids 必须是字符串数组")
            return

        project = message.get("project")
        count = await self.manager.subscribe(self, device_ids, project)

        await self.websocket.send(
            json.dumps(
                {
                    "type": "subscribed",
                    "session_id": self.session_id,
                    "timestamp": int(asyncio.get_event_loop().time() * 1000),
                    "device_ids": device_ids,
                    "message": f"已订阅 {count} 台设备",
                },
                ensure_ascii=False,
            )
        )

    async def _handle_unsubscribe(self, message: dict):
        """处理取消订阅请求"""
        device_ids = message.get("device_ids")
        count = await self.manager.unsubscribe(self, device_ids)

        await self.websocket.send(
            json.dumps(
                {
                    "type": "unsubscribed",
                    "session_id": self.session_id,
                    "timestamp": int(asyncio.get_event_loop().time() * 1000),
                    "message": f"已取消 {count} 台设备订阅",
                },
                ensure_ascii=False,
            )
        )

    async def _handle_ping(self):
        """处理心跳"""
        await self.websocket.send(
            json.dumps(
                {
                    "type": "pong",
                    "session_id": self.session_id,
                    "timestamp": int(asyncio.get_event_loop().time() * 1000),
                }
            )
        )

    async def _send_error(self, code: str, message: str):
        """发送错误消息"""
        try:
            await self.websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "session_id": self.session_id,
                        "timestamp": int(asyncio.get_event_loop().time() * 1000),
                        "code": code,
                        "message": message,
                    },
                    ensure_ascii=False,
                )
            )
        except websockets.exceptions.ConnectionClosed:
            self._alive = False

    async def _cleanup(self):
        """清理资源"""
        self._alive = False
        await self.manager.remove_handler(self)
        try:
            await self.websocket.close()
        except Exception:
            pass
