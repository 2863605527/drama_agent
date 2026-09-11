"""任务进度中心：为每个任务维护一个 asyncio.Queue + 历史事件缓存，
供 SSE 流式输出实时推送流水线进度事件。

多实例扩展（预留）：单实例下事件只在本进程内存；水平扩容多实例时，
创建任务的实例与建立 SSE 连接的实例可能不是同一个。此时调用
``await progress_hub.attach_redis(redis_client)`` 接入 Redis Pub/Sub，
publish 会额外广播到 Redis 频道，其他实例的桥接协程收到后投递到本地队列。
未安装 redis 依赖 / 未调用 attach_redis 时，行为与纯内存完全一致。
"""
import asyncio
import time
from typing import Dict, List, Tuple, Optional, Callable, Awaitable

_CHANNEL = "drama:progress"


class ProgressHub:
    def __init__(self, max_history: int = 500):
        # 每个任务可有多个并发订阅者（多个浏览器标签 / EventSource 自动重连），
        # 必须“每个连接一条独立队列”，发布时扇出广播；绝不能多连接共享单队列，
        # 否则已断开但尚未退出的旧协程会把事件取走，导致当前页面收不到实时进度。
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._history: Dict[str, List[dict]] = {}
        self._seq: Dict[str, int] = {}
        self._max_history = max_history
        # 每任务事件回调（用于把日志持久化到任务，刷新/重启后可回显）
        self._sinks: Dict[str, Callable[[dict], Awaitable[None]]] = {}
        # 可选 Redis 桥接（多实例时启用）
        self._redis = None
        self._bridge_task: Optional[asyncio.Task] = None
        self._instance_id = f"{id(self):x}"

    def bind_sink(self, task_id: str, cb: Callable[[dict], Awaitable[None]]):
        """注册任务事件 sink（幂等覆盖）。publish 每条事件后会异步回调，异常不影响主流程。"""
        self._sinks[task_id] = cb

    def unbind_sink(self, task_id: str):
        self._sinks.pop(task_id, None)

    def create_stream(self, task_id: str):
        """为任务初始化历史 / 序号 / 订阅者容器（幂等，各字典独立补齐，
        避免“订阅者列表已随最后连接回收、历史仍在”时再次订阅 KeyError）"""
        self._subscribers.setdefault(task_id, [])
        self._history.setdefault(task_id, [])
        self._seq.setdefault(task_id, 0)

    def set_seq_floor(self, task_id: str, seq: int):
        """设置 seq 下限（进程重启后从持久化日志恢复水位，保证 seq 跨重启单调递增，
        前端按 seq 去重才不会把新事件误判为重复）"""
        self.create_stream(task_id)
        if seq > self._seq[task_id]:
            self._seq[task_id] = seq

    async def publish(self, task_id: str, event: dict):
        """发布一条进度事件：写入历史缓存，并扇出给该任务的每一条订阅队列（各自独立、互不抢占）"""
        self.create_stream(task_id)
        event.setdefault("event", "log")
        self._seq[task_id] += 1
        event["seq"] = self._seq[task_id]
        event.setdefault("ts", time.time())
        self._history[task_id].append(event)
        # 限制历史缓存大小，避免 SSE 重连后重放过多旧事件
        if len(self._history[task_id]) > self._max_history:
            self._history[task_id] = self._history[task_id][-self._max_history:]
        # 扇出广播：每个活跃订阅者各收一份；put_nowait 无界队列不会阻塞，慢/僵尸连接不影响其他人
        for q in list(self._subscribers.get(task_id, ())):
            try:
                q.put_nowait(event)
            except Exception:
                pass
        # 持久化 sink（失败不阻断主流程）
        sink = self._sinks.get(task_id)
        if sink is not None:
            try:
                await sink(event)
            except Exception:
                pass
        # 多实例：广播给其他实例（失败不影响主流程）
        if self._redis is not None:
            await self._redis_publish(task_id, event)

    async def subscribe(self, task_id: str) -> Tuple[List[dict], asyncio.Queue]:
        """订阅者接入：为“本次连接”新建独立队列，返回 (历史事件快照, 该连接专属队列)。
        多次连接 / 重连各自独立，事件互不抢占。"""
        self.create_stream(task_id)
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[task_id].append(q)
        return list(self._history[task_id]), q

    def unsubscribe(self, task_id: str, q: asyncio.Queue):
        """连接结束时注销其专属队列（SSE 协程退出必须调用，防止僵尸队列堆积）"""
        subs = self._subscribers.get(task_id)
        if not subs:
            return
        try:
            subs.remove(q)
        except ValueError:
            pass
        if not subs:
            self._subscribers.pop(task_id, None)

    def drop(self, task_id: str):
        """任务结束后清理（可选调用）"""
        self._subscribers.pop(task_id, None)
        self._history.pop(task_id, None)
        self._seq.pop(task_id, None)
        self._sinks.pop(task_id, None)

    # ---------- 可选：Redis Pub/Sub 多实例桥接 ----------
    async def attach_redis(self, redis_client) -> None:
        """接入 redis.asyncio 客户端，开启跨实例事件桥接。

        用法（lifespan 中）：
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.redis_url)
            await progress_hub.attach_redis(r)
        """
        self._redis = redis_client
        if self._bridge_task is None:
            self._bridge_task = asyncio.create_task(self._redis_bridge())

    async def detach_redis(self) -> None:
        if self._bridge_task:
            self._bridge_task.cancel()
            self._bridge_task = None
        self._redis = None

    async def _redis_publish(self, task_id: str, event: dict) -> None:
        import json
        try:
            payload = json.dumps({"task_id": task_id, "event": event,
                                  "from": self._instance_id}, ensure_ascii=False)
            await self._redis.publish(_CHANNEL, payload)
        except Exception:
            pass  # 广播失败不阻断本地流水线

    async def _redis_bridge(self) -> None:
        """订阅 Redis 频道，把其他实例的事件投递到本地队列（不回环自己发的）"""
        import json
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(_CHANNEL)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    if data.get("from") == self._instance_id:
                        continue  # 自己广播的，本地已投递
                    tid, evt = data["task_id"], data["event"]
                    self.create_stream(tid)
                    self._history[tid].append(evt)
                    for q in list(self._subscribers.get(tid, ())):
                        try:
                            q.put_nowait(evt)
                        except Exception:
                            pass
                except Exception:
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.unsubscribe(_CHANNEL)
                await pubsub.close()
            except Exception:
                pass


# 全局单例
progress_hub = ProgressHub()
