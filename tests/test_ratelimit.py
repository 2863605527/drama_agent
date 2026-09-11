"""固定窗口限流器单元测试"""
import time
from core.ratelimit import FixedWindowRateLimiter


class TestRateLimiter:
    def test_allow_within_limit(self):
        rl = FixedWindowRateLimiter()
        ok1, remain1 = rl.is_allowed("k", "3/minute")
        ok2, remain2 = rl.is_allowed("k", "3/minute")
        assert ok1 and ok2
        assert remain1 == 2
        assert remain2 == 1

    def test_block_over_limit(self):
        rl = FixedWindowRateLimiter()
        results = [rl.is_allowed("k", "2/minute")[0] for _ in range(3)]
        assert results == [True, True, False]

    def test_different_keys_independent(self):
        rl = FixedWindowRateLimiter()
        rl.is_allowed("a", "1/minute")
        ok_b, _ = rl.is_allowed("b", "1/minute")
        assert ok_b  # 不同 key 互不影响

    def test_window_expires(self):
        rl = FixedWindowRateLimiter()
        rl.is_allowed("k", "1/second")
        ok, _ = rl.is_allowed("k", "1/second")
        assert not ok
        time.sleep(1.1)
        ok_after, _ = rl.is_allowed("k", "1/second")
        assert ok_after

    def test_reset(self):
        rl = FixedWindowRateLimiter()
        rl.is_allowed("k", "1/minute")
        rl.reset("k")
        ok, _ = rl.is_allowed("k", "1/minute")
        assert ok
