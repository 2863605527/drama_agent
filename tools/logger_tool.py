"""统一日志模块：控制台 + 文件双输出，按天滚动。

用法：
    from tools.logger_tool import get_logger
    logger = get_logger("drama.skill")
    logger.info("...")

日志文件位置：./logs/drama_YYYY-MM-DD.log
"""
import os
import sys
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

_LOG_DIR = os.path.join(os.getcwd(), "logs")
_LOG_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_configured = False


def _ansi_formatter():
    """控制台带颜色的 Formatter（Windows Terminal / VSCode / 大多数现代终端支持 ANSI）"""
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
    """初始化 root logger：控制台（INFO）+ 按天滚动的文件（DEBUG）"""
    global _configured
    if _configured:
        return
    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 控制台：INFO 及以上，带颜色
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(_ansi_formatter())
    root.addHandler(console)

    # 文件：DEBUG 及以上，按天滚动，保留 14 天
    logfile = os.path.join(_LOG_DIR, "drama.log")
    file_handler = TimedRotatingFileHandler(
        logfile, when="midnight", backupCount=14, encoding="utf-8")
    file_handler.suffix = "%Y-%m-%d.log"
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_LOG_FMT, _DATE_FMT))
    root.addHandler(file_handler)

    # 降噪：uvicorn access 日志太啰嗦，调到 WARNING
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _configured = True
    root.info("logger initialized, log file: %s", logfile)


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger（首次调用自动初始化 root 配置）"""
    _setup_root()
    return logging.getLogger(name)
