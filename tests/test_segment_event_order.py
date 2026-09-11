"""片段视频 job 的事件时序测试：成功时必须「先 persist 落库，再广播 segment ok」。

回归保护：曾经 segment ok 在落库前就发出，前端收到后立即回拉详情会读到旧数据，
把事件里刚回填的 video_url 又覆盖为空，表现为「视频生成成功但前端不展示」。
"""
import pytest

from schema.drama_schema import DramaTask, DramaScript, Segment, TaskStatus
from tasks import job_runner


class _FakeCounter:
    def inc(self):
        pass

    def dec(self):
        pass


@pytest.mark.asyncio
async def test_segment_ok_event_emitted_after_persist(monkeypatch):
    order = []
    seg = Segment(segment_id="seg-1", shot_ids=["s1", "s2"], duration=8)
    task = DramaTask(task_id="t1", thread_id="t1", user_prompt="x",
                     status=TaskStatus.GENERATE_VIDEO)
    task.script = DramaScript(script_id="sc1", title="t", raw_content="x",
                              characters=[], scenes=[], shots=[], segments=[seg])

    async def fake_infra():
        order.append("infra")

    async def fake_load(_tid):
        order.append("load")
        return task

    async def fake_persist(_t):
        order.append("persist")

    class _FakeSkill:
        async def _generate_segment_video(self, t, g):
            order.append("gen")
            g.video_url = "/assets/videos/t1_seg-1.mp4"
            return True

    events = []

    async def fake_pub(_tid, ev):
        order.append("pub")
        events.append(ev)

    monkeypatch.setattr(job_runner, "_ensure_infra", fake_infra)
    monkeypatch.setattr(job_runner, "load_task", fake_load)
    monkeypatch.setattr(job_runner, "persist_task", fake_persist)
    monkeypatch.setattr(job_runner, "_get_skill", lambda: _FakeSkill())
    monkeypatch.setattr(job_runner.progress_hub, "publish", fake_pub)
    monkeypatch.setattr(job_runner.metrics, "ACTIVE_TASKS", _FakeCounter(), raising=False)

    ok = await job_runner.run_segment_video_job("t1", "seg-1")
    assert ok is True

    ok_events = [e for e in events if e.get("event") == "segment" and e.get("status") == "ok"]
    assert len(ok_events) == 1, "成功后应广播恰好一次 segment ok"
    assert ok_events[0]["video_url"] == "/assets/videos/t1_seg-1.mp4"
    # 关键时序：生成 -> 落库 -> 广播 ok（最后一个动作是广播，且落库早于广播）
    assert order[-1] == "pub"
    assert order.index("gen") < order.index("persist")
    assert order.index("persist") < len(order) - 1
