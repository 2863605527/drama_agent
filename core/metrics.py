"""Prometheus 指标埋点。

若未安装 prometheus-client，自动降级为 no-op，不影响主流程运行：
    pip install prometheus-client
"""
import time
import contextlib

try:
    from prometheus_client import Counter, Histogram, Gauge, CONTENT_TYPE_LATEST, generate_latest
    _AVAILABLE = True
except Exception:  # pragma: no cover - 未安装时降级
    _AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"

    def generate_latest():
        return b"# prometheus-client not installed\n"

    class _Noop:
        def labels(self, *a, **k):
            return self
        def inc(self, *a, **k):
            pass
        def observe(self, *a, **k):
            pass
        def set(self, *a, **k):
            pass

    Counter = Histogram = Gauge = _Noop


# 任务相关指标
TASK_SUBMITTED = Counter("drama_tasks_submitted_total", "提交任务总数", ["user"])
TASK_STATUS = Counter("drama_task_status_total", "任务状态变更次数", ["status"])
LLM_CALLS = Counter("drama_llm_calls_total", "LLM/MCP 调用次数", ["status"])
LLM_LATENCY = Histogram("drama_llm_latency_seconds", "LLM 调用耗时", buckets=(1, 5, 10, 20, 40, 60, 90, 120, 180))
ACTIVE_TASKS = Gauge("drama_active_tasks", "当前进行中的任务数")
MEDIA_CALLS = Counter("drama_media_calls_total", "图片/视频/TTS 生成调用次数", ["kind", "status"])
MEDIA_LATENCY = Histogram(
    "drama_media_latency_seconds", "媒体能力（image/video/tts/ffmpeg）调用耗时",
    ["kind"], buckets=(1, 5, 10, 30, 60, 120, 180, 300, 600, 900))

# HTTP 接口指标（路径做模板归一化，避免 task_id 造成高基数标签爆炸）
HTTP_REQUESTS = Counter("drama_http_requests_total", "HTTP 请求总数", ["method", "path", "status"])
HTTP_LATENCY = Histogram(
    "drama_http_latency_seconds", "HTTP 请求耗时",
    ["method", "path"], buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))


def normalize_path(request) -> str:
    """把真实路径归一化为路由模板：/api/task/<uuid>/compose -> /api/task/{id}/compose。"""
    try:
        route = request.scope.get("route")
        if route is not None and getattr(route, "path", None):
            return route.path
    except Exception:
        pass
    return request.url.path


@contextlib.contextmanager
def observe_latency(histogram, counter_ok="ok", counter_fail="fail"):
    """通用耗时观测上下文"""
    start = time.time()
    ok = True
    try:
        yield
    except Exception:
        ok = False
        raise
    finally:
        histogram.observe(time.time() - start)
        LLM_CALLS.labels(counter_ok if ok else counter_fail).inc()


def metrics_payload():
    return generate_latest(), CONTENT_TYPE_LATEST
