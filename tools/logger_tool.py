"""统一日志模块：控制台 + 文件双输出，按天滚动；支持文本/JSON 两种格式。

用法：
    from tools.logger_tool import get_logger
    logger = get_logger("drama.skill")
    logger.info("...")

- 开发默认：控制台彩色文本，文件纯文本。
- 生产可设环境变量 LOG_FORMAT=json：控制台与文件均输出单行 JSON（便于 Loki/ELK 采集）。
- 可用 log_context(task_id=..., request_id=...) 给一段执行绑定上下文字段，
  该上下文内所有日志自动携带（基于 contextvars，asyncio 安全）。

日志文件位置：./logs/drama_YYYY-MM-DD.log
"""
import os
import sys
import json
import logging
import contextvars
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler

_LOG_DIR = os.path.join(os.getcwd(), "logs")
_LOG_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_LOG_FORMAT = os.getenv("LOG_FORMAT", "text").strip().lower()
_configured = False

# 异步安全的日志上下文（每个任务/请求可绑定，自动随 task 传播）
_CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("LOG_CTX", default={})


def bind_log_context(**fields) -> contextvars.Token:
    """合并绑定日志上下文字段，返回 token 用于 reset；也可用 contextlib 自行管理。"""
    merged = {**_CTX.get(), **{k: v for k, v in fields.items() if v is not None}}
    return _CTX.set(merged)


def reset_log_context(token: contextvars.Token) -> None:
    _CTX.reset(token)


class log_context:
    """上下文管理器：with log_context(task_id=...): logger.info(...) 自动带字段。"""
    def __init__(self, **fields):
        self.fields = fields
        self.token = None

    def __enter__(self):
        self.token = bind_log_context(**self.fields)
        return self

    def __exit__(self, *exc):
        reset_log_context(self.token)
        return False


class _JsonFormatter(logging.Formatter):
    """单行 JSON 结构化格式：固定字段 + contextvars 上下文 + 异常栈。"""
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_CTX.get())
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # 业务代码通过 logger.info(..., extra={"fields": {...}}) 附加结构化字段
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _ansi_formatter():
    """控制台带颜色的 Formatter（现代终端支持 ANSI）"""
    class ColorFormatter(logging.Formatter):
        COLORS = {
            logging.DEBUG: "\033[90m",
            logging.INFO: "\033[36m",
            logging.WARNING: "\033[33m",
            logging.ERROR: "\033[31m",
            logging.CRITICAL: "\033[1;31m",
        }
        RESET = "\033[0m"

        def format(self, record):
            color = self.COLORS.get(record.levelno, "")
            record.levelname = f"{color}{record.levelname}{self.RESET}"
            return super().format(record)

    return ColorFormatter(_LOG_FMT, _DATE_FMT)


def _setup_root():
    """初始化 root logger：控制台（INFO）+ 按天滚动文件（DEBUG）"""
    global _configured
    if _configured:
        return
    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    use_json = _LOG_FORMAT == "json"
    console_fmt = _JsonFormatter() if use_json else _ansi_formatter()
    file_fmt = _JsonFormatter() if use_json else logging.Formatter(_LOG_FMT, _DATE_FMT)

    # 控制台日志统一走 stderr：
    # 1) MCP stdio 子进程的 stdout 只能传输 JSON-RPC，写日志会污染协议流；
    # 2) 符合 12-factor（应用日志走 stderr），主进程 API 响应不依赖 stdout。
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(console_fmt)
    root.addHandler(console)

    logfile = os.path.join(_LOG_DIR, "drama.log")
    file_handler = TimedRotatingFileHandler(
        logfile, when="midnight", backupCount=14, encoding="utf-8")
    file_handler.suffix = "%Y-%m-%d.log"
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_fmt)
    root.addHandler(file_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _configured = True
    root.info("logger initialized | format=%s | file=%s", _LOG_FORMAT, logfile)


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger（首次调用自动初始化 root 配置）"""
    _setup_root()
    return logging.getLogger(name)
