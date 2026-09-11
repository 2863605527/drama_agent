# -*- coding: utf-8 -*-
"""ProgressHub 订阅扇出测试：每个 SSE 连接独立队列，多连接 / 重连互不抢占。

回归背景：旧实现“每任务一个共享队列”，多个 EventSource 连接（含自动重连残留的
僵尸协程）竞争消费，事件被断开的旧连接取走后，当前页面就收不到实时日志。
"""
import pytest

from agent.progress_hub import ProgressHub


@pytest.fixture
def hub():
    return ProgressHub()


async def test_multiple_subscribers_each_get_all_events(hub):
    tid = "t1"
    _, q1 = await hub.subscribe(tid)
    _, q2 = await hub.subscribe(tid)
    for i in range(3):
        await hub.publish(tid, {"event": "log", "message": f"m{i}"})

    async def drain(q):
        out = []
        while not q.empty():
            out.append((await q.get())["message"])
        return out

    assert await drain(q1) == ["m0", "m1", "m2"]
    assert await drain(q2) == ["m0", "m1", "m2"]


async def test_unsubscribe_stops_delivery_but_keeps_others(hub):
    tid = "t2"
    _, q1 = await hub.subscribe(tid)
    _, q2 = await hub.subscribe(tid)
    hub.unsubscribe(tid, q1)
    await hub.publish(tid, {"event": "log", "message": "only-q2"})
    assert q1.empty()
    assert (await q2.get())["message"] == "only-q2"


async def test_late_subscriber_gets_history_snapshot(hub):
    tid = "t3"
    for i in range(2):
        await hub.publish(tid, {"event": "log", "message": f"h{i}"})
    history, q = await hub.subscribe(tid)
    assert [e["message"] for e in history] == ["h0", "h1"]
    await hub.publish(tid, {"event": "log", "message": "live"})
    assert (await q.get())["message"] == "live"


async def test_seq_monotonic_per_task(hub):
    tid = "t4"
    seqs = []
    for _ in range(3):
        ev = {}
        await hub.publish(tid, ev)
        seqs.append(ev["seq"])
    assert seqs == [1, 2, 3]


async def test_resubscribe_after_last_subscriber_left(hub):
    """最后一个连接断开会回收订阅者列表但保留历史，再次订阅必须能正常重建、不抛 KeyError。"""
    tid = "t5"
    await hub.publish(tid, {"event": "log", "message": "before"})
    _, q1 = await hub.subscribe(tid)
    hub.unsubscribe(tid, q1)          # 最后一个订阅者离开，订阅者列表被回收、历史保留
    history, q2 = await hub.subscribe(tid)   # 重连不得 KeyError
    assert [e["message"] for e in history] == ["before"]
    await hub.publish(tid, {"event": "log", "message": "after"})
    assert (await q2.get())["message"] == "after"
