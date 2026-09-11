"""异步任务分发器测试：USE_CELERY 开关在「本地 asyncio」与「Celery 队列」间正确切换。

不依赖真实 Redis/Celery：Celery 分支用 sys.modules 注入假任务对象，本地分支 mock job_runner。
"""
import sys
import types
import asyncio

import pytest

from core.config import settings
from tasks import dispatcher


@pytest.fixture
def fake_celery_module(monkeypatch):
    """注入假的 tasks.celery_jobs，避免测试环境未安装 celery 也能验证 .delay 分发。"""
    calls = {"segment": [], "compose": []}

    class _FakeTask:
        def __init__(self, bucket):
            self.bucket = bucket

        def delay(self, *args):
            self.bucket.append(args)

    mod = types.ModuleType("tasks.celery_jobs")
    mod.generate_segment_video_task = _FakeTask(calls["segment"])
    mod.compose_video_task = _FakeTask(calls["compose"])
    monkeypatch.setitem(sys.modules, "tasks.celery_jobs", mod)
    return calls


@pytest.mark.asyncio
async def test_local_mode_runs_in_background(monkeypatch):
    """USE_CELERY=false：本地 asyncio 后台执行 job_runner，并触发 on_finish。"""
    monkeypatch.setattr(settings, "use_celery", False)
    ran = {"compose": False}
    finished = asyncio.Event()

    async def fake_compose(task_id):
        ran["compose"] = task_id

    from tasks import job_runner
    monkeypatch.setattr(job_runner, "run_compose_job", fake_compose)

    mode = await dispatcher.schedule_compose("t-1", on_finish=finished.set)
    assert mode == "local"
    # 让出事件循环，使 create_task 的协程真正执行完
    await asyncio.sleep(0.05)
    assert ran["compose"] == "t-1"
    assert finished.is_set()


@pytest.mark.asyncio
async def test_celery_mode_enqueues_delay(fake_celery_module, monkeypatch):
    """USE_CELERY=true：只投递 .delay，不在本地执行 job_runner。"""
    monkeypatch.setattr(settings, "use_celery", True)
    from tasks import job_runner

    async def boom(task_id):
        raise AssertionError("celery 模式下不应在 Web 进程执行 job")
    monkeypatch.setattr(job_runner, "run_segment_video_job", boom)

    mode = await dispatcher.schedule_segment_video("t-2", "seg-2")
    assert mode == "celery"
    await asyncio.sleep(0.01)
    assert fake_celery_module["segment"] == [("t-2", "seg-2")]
    assert fake_celery_module["compose"] == []


@pytest.mark.asyncio
async def test_celery_mode_compose_delay(fake_celery_module, monkeypatch):
    monkeypatch.setattr(settings, "use_celery", True)
    mode = await dispatcher.schedule_compose("t-3")
    assert mode == "celery"
    assert fake_celery_module["compose"] == [("t-3",)]


@pytest.mark.asyncio
async def test_async_on_finish_is_awaited(monkeypatch):
    """on_finish 为协程函数时也能被正确 await。"""
    monkeypatch.setattr(settings, "use_celery", False)
    state = {"done": False}

    async def fake_seg(task_id, segment_id):
        return True

    async def async_finish():
        state["done"] = True

    from tasks import job_runner
    monkeypatch.setattr(job_runner, "run_segment_video_job", fake_seg)
    await dispatcher.schedule_segment_video("t-4", "seg-4", on_finish=async_finish)
    await asyncio.sleep(0.05)
    assert state["done"] is True
