"""DramaMakeSkill 双模式 LLM 路由测试：注入宿主 provider 走客户端模型，否则回退 MCP。

不连真实 MCP / LLM / 火山 API：宿主侧用 FakeProvider，回退路径只断言配置状态。
"""
import pytest

from skill.drama_make_skill import DramaMakeSkill


class FakeHostProvider:
    def __init__(self):
        self.calls = []

    async def llm(self, messages, temperature=0.7):
        self.calls.append((messages, temperature))
        return f"host#{len(self.calls)}"


@pytest.mark.asyncio
async def test_default_falls_back_to_mcp():
    """默认不注入 provider：llm_provider 为 None，业务仍走 mcp_client（项目模式行为不变）。"""
    skill = DramaMakeSkill()
    assert skill.llm_provider is None


@pytest.mark.asyncio
async def test_injected_provider_handles_llm():
    host = FakeHostProvider()
    skill = DramaMakeSkill(llm_provider=host)
    out1 = await skill._llm([{"role": "user", "content": "写剧本"}])
    out2 = await skill._llm([{"role": "user", "content": "拆JSON"}], temperature=0.2)
    assert out1 == "host#1" and out2 == "host#2"
    assert len(host.calls) == 2
    # temperature 透传
    assert host.calls[1][1] == 0.2
    # 传给宿主的就是标准 messages
    assert host.calls[0][0] == [{"role": "user", "content": "写剧本"}]
