"""跨路由共享的运行时单例。

main.py 的 lifespan 启动时调用 init_agent() 重建实例（清空内存任务存储 / sink 等状态）；
路由一律通过 api.deps.get_agent() 依赖取用，实时读取模块属性，始终拿到当前实例，
不缓存导入期引用。保留 import 期占位实例：测试与脚本不触发 lifespan 也能工作。
"""
from agent.drama_agent import DramaAgent

agent = DramaAgent()  # 占位：import 期可用


def init_agent() -> DramaAgent:
    """（lifespan 中调用）重建 DramaAgent 并从 MySQL 加载全部任务"""
    global agent
    agent = DramaAgent()
    return agent
