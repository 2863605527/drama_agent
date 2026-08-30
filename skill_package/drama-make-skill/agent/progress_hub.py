"""任务进度中心：为每个任务维护一个 asyncio.Queue + 历史事件缓存，
供 SSE 流式输出实时推送流水线进度事件。"""
import asyncio
import time
from typing import Dict, List, Tuple


class ProgressHub:
    def __init__(self, max_history: int = 500):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._history: Dict[str, List[dict]] = {}
        self._seq: Dict[str, int] = {}
        self._max_history = max_history

    def create_stream(self, task_id: str):
        """为任务创建进度流（幂等）"""
        if task_id not in self._queues:
            self._queues[task_id] = asyncio.Queue()
            self._history[task_id] = []
            self._seq[task_id] = 0

    async def publish(self, task_id: str, event: dict):
        """发布一条进度事件，历史缓存 + 实时队列（带自增 seq 与 ts）"""
        if task_id not in self._queues:
            self.create_stream(task_id)
        event.setdefault("event", "log")
        self._seq[task_id] += 1
        event["seq"] = self._seq[task_id]
        event.setdefault("ts", time.time())
        self._history[task_id].append(event)
        # 限制历史缓存大小，避免 SSE 重连后重放过多旧事件
        if len(self._history[task_id]) > self._max_history:
            self._history[task_id] = self._history[task_id][-self._max_history:]
        await self._queues[task_id].put(event)

    async def subscribe(self, task_id: str) -> Tuple[List[dict], asyncio.Queue]:
        """订阅者接入：返回 (历史事件列表, 实时队列)"""
        self.create_stream(task_id)
        return list(self._history[task_id]), self._queues[task_id]

    def drop(self, task_id: str):
        """任务结束后清理（可选调用）"""
        self._queues.pop(task_id, None)
        self._history.pop(task_id, None)
        self._seq.pop(task_id, None)


# 全局单例
progress_hub = ProgressHub()
