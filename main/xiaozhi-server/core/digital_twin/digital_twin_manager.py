"""
数字孪生连接管理器
管理所有数字孪生 WebSocket 连接 + 设备订阅关系
"""
import time
import asyncio
import logging
from typing import Dict, Set, Optional
from collections import defaultdict

TAG = __name__


class DigitalTwinManager:
    """管理数字孪生客户端的设备订阅与事件推送"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        # device_id → set[DigitalTwinHandler]
        self._subscriptions: Dict[str, Set] = defaultdict(set)
        # device_id → sequence 计数器
        self._sequences: Dict[str, int] = defaultdict(int)
        # 所有活跃的数字孪生 handler
        self._handlers: Set = set()
        # 线程安全锁
        self._lock = asyncio.Lock()

    async def subscribe(
        self, handler, device_ids: list, project: Optional[str] = None
    ) -> int:
        """
        订阅设备事件

        Args:
            handler: DigitalTwinHandler 实例
            device_ids: 要订阅的设备 MAC 地址列表
            project: 可选项目过滤

        Returns:
            实际订阅的设备数量
        """
        async with self._lock:
            self._handlers.add(handler)
            subscribed_count = 0
            for did in device_ids:
                did = did.strip()
                if not did:
                    continue
                self._subscriptions[did].add(handler)
                # 确保 sequence 从 1 开始
                if did not in self._sequences:
                    self._sequences[did] = 0
                subscribed_count += 1
            self.logger.bind(tag=TAG).info(
                f"数字孪生客户端订阅 {subscribed_count} 台设备, "
                f"当前活跃连接: {len(self._handlers)}, "
                f"当前订阅设备: {len(self._subscriptions)}"
            )
            return subscribed_count

    async def unsubscribe(
        self, handler, device_ids: Optional[list] = None
    ) -> int:
        """
        取消订阅设备事件

        Args:
            handler: DigitalTwinHandler 实例
            device_ids: 要取消的设备列表，None 表示全部

        Returns:
            取消的设备数量
        """
        async with self._lock:
            count = 0
            if device_ids is None:
                # 取消全部订阅
                for did in list(self._subscriptions.keys()):
                    if handler in self._subscriptions[did]:
                        self._subscriptions[did].discard(handler)
                        count += 1
                    # 清理空集合
                    if not self._subscriptions[did]:
                        del self._subscriptions[did]
            else:
                for did in device_ids:
                    did = did.strip()
                    if did in self._subscriptions:
                        self._subscriptions[did].discard(handler)
                        count += 1
                        if not self._subscriptions[did]:
                            del self._subscriptions[did]
            return count

    async def remove_handler(self, handler):
        """客户端断开连接时清理"""
        async with self._lock:
            self._handlers.discard(handler)
            # 清理所有订阅
            for did in list(self._subscriptions.keys()):
                self._subscriptions[did].discard(handler)
                if not self._subscriptions[did]:
                    del self._subscriptions[did]
            self.logger.bind(tag=TAG).info(
                f"数字孪生客户端断开, 剩余连接: {len(self._handlers)}"
            )

    async def push_event(self, device_id: str, event: dict):
        """
        推送事件到所有订阅了该设备的数字孪生客户端

        Args:
            device_id: OTA 设备 ID
            event: 事件字典（不含 sequence，由本方法注入）
        """
        async with self._lock:
            handlers = self._subscriptions.get(device_id, set())
            if not handlers:
                return

            # 分配递增序号
            self._sequences[device_id] += 1
            event["sequence"] = self._sequences[device_id]

        # 广播到所有订阅者（不持锁以提升并发）
        dead_handlers = []
        for handler in list(handlers):
            try:
                await handler.send_event(event)
            except Exception as e:
                self.logger.bind(tag=TAG).warning(
                    f"推送事件到数字孪生客户端失败: {e}"
                )
                dead_handlers.append(handler)

        # 清理失效的 handler
        if dead_handlers:
            async with self._lock:
                for dh in dead_handlers:
                    await self.remove_handler(dh)

    def has_subscribers(self, device_id: str) -> bool:
        """检查设备是否有数字孪生订阅者"""
        return device_id in self._subscriptions and len(self._subscriptions[device_id]) > 0
