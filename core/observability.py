"""可观测性统一入口：Sentry 错误监控（可选）。

设计原则与 prometheus-client 一致：依赖与 DSN 都缺失时静默降级，绝不阻断启动。
- 未配置 SENTRY_DSN：完全不启用；
- 配了 DSN 但没装 sentry-sdk：打印一次警告并跳过（pip install sentry-sdk 即启用）；
- 两者齐备：初始化，错误与异常自动上报，附带 environment/release 标签。
"""
from core.config import settings
from tools.logger_tool import get_logger

logger = get_logger("drama.observability")
_initialized = False


def init_sentry() -> bool:
    """初始化 Sentry，返回是否真正启用。幂等。"""
    global _initialized
    if _initialized:
        return True
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
    except Exception:
        logger.warning("SENTRY_DSN 已配置但未安装 sentry-sdk，跳过错误上报（pip install sentry-sdk）")
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        release=settings.app_version,
        traces_sample_rate=float(settings.sentry_traces_sample or 0),
        send_default_pii=False,            # 不上报用户隐私（密码/token 等）
        integrations=[FastApiIntegration(), AsyncioIntegration()],
        ignore_errors=[],
    )
    _initialized = True
    logger.info("sentry initialized | env=%s | release=%s", settings.environment, settings.app_version)
    return True


def capture_exception(err: Exception = None):
    """业务显式上报异常（Sentry 未启用时为空操作）。"""
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(err)
    except Exception:
        pass
