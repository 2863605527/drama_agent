"""登录限流测试：连续失败超过阈值返回 429"""
import pytest
from core.ratelimit import rate_limiter


@pytest.mark.asyncio
class TestLoginRateLimit:
    async def test_login_rate_limited(self, client):
        # 该测试用固定 IP + 固定路径，连续打超过 5 次错误登录
        rate_limiter.reset()
        statuses = []
        for i in range(7):
            resp = await client.post("/api/auth/login",
                                     json={"username": "nobody", "password": f"wrong{i}"})
            statuses.append(resp.status_code)
        rate_limiter.reset()
        # 前 5 次为 401，之后应出现 429
        assert 429 in statuses
        assert statuses[:5].count(401) == 5
