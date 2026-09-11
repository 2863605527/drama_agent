"""轻量级固定窗口限流器（纯内存实现，无额外依赖）。

单实例足够；多实例部署时应替换为 Redis 版本（接口保持一致）。
"""
import time
import threading
from collections import defaultdict


class FixedWindowRateLimiter:
    def __init__(self):
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    @staticmethod
    def _parse(limit: str) -> tuple[int, int]:
        """'5/minute' -> (5, 60)；支持 second/minute/hour/day"""
        num, unit = limit.strip().split("/")
        num = int(num)
        window_map = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        return num, window_map.get(unit, 60)

    def is_allowed(self, key: str, limit: str) -> tuple[bool, int]:
        """返回 (是否放行, 剩余次数)"""
        max_hits, window = self._parse(limit)
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits[key] if now - t < window]
            if len(hits) >= max_hits:
                self._hits[key] = hits
                return False, 0
            hits.append(now)
            self._hits[key] = hits
            return True, max_hits - len(hits)

    def reset(self, key: str = None):
        with self._lock:
            if key:
                self._hits.pop(key, None)
            else:
                self._hits.clear()


rate_limiter = FixedWindowRateLimiter()
