import os
import time
import requests
from dotenv import load_dotenv
from tools.logger_tool import get_logger

logger = get_logger("drama.llm")

load_dotenv()

# ===== 大模型配置（全部支持环境变量覆盖，可随时切换 DeepSeek / Kimi / Qwen / 本地 vLLM 等 OpenAI 兼容模型）=====
# API 基地址（OpenAI 兼容接口）
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.deepseek.com").rstrip("/")
# API Key（LLM_API_KEY 优先，兼容旧变量 DEEPSEEK_API_KEY）
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
# 模型名称：DeepSeek 官方为 deepseek-chat(V3)/deepseek-reasoner(R1)；
# 第三方 OpenAI 兼容中转(Kimi/Qwen/vLLM 等)请在 .env 用 LLM_MODEL 配合对应 LLM_API_URL 覆盖
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
# 默认温度
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
# 空响应 / 网络异常重试次数（DeepSeek 等偶发 HTTP 200 + body=0）
LLM_MAX_RETRIES = max(1, int(os.getenv("LLM_MAX_RETRIES", "3")))
# 重试基础等待（秒），按 1x/2x/4x 指数退避
LLM_RETRY_BASE = float(os.getenv("LLM_RETRY_BASE", "2"))

logger.info("llm config | url=%s | model=%s | key=%s | retries=%d",
            LLM_API_URL, LLM_MODEL, "***" if LLM_API_KEY else "MISSING", LLM_MAX_RETRIES)


def llm_chat(messages: list, temperature: float = None) -> str:
    """调用大模型（OpenAI 兼容接口），模型/地址/Key 均由环境变量决定。
    遇网络异常 / HTTP 5xx / 空响应会按指数退避自动重试 LLM_MAX_RETRIES 次。"""
    url = LLM_API_URL
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": LLM_TEMPERATURE if temperature is None else temperature
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"}
    logger.info("llm_chat | model=%s | msgs=%d | chars=%d", LLM_MODEL, len(messages), len(str(messages)))
    last_err = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            if resp.status_code in (401, 403):
                raise RuntimeError(
                    f"HTTP {resp.status_code} 鉴权失败：当前 LLM_API_KEY 在 {LLM_API_URL} 不被认可"
                    f"（官方 Key 请核对是否复制正确/是否被禁用；第三方中转 Key 必须把 LLM_API_URL 改成中转地址）。上游返回：{resp.text[:150]}")
            if resp.status_code >= 500:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:120]}")
            resp.raise_for_status()
            j = resp.json()
            content = (j.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if not content or not content.strip():
                # HTTP 200 但 content 为空（DeepSeek 偶发），当作出错重试
                raise RuntimeError("LLM 返回空响应（HTTP 200 + body=0，可能是上游服务限流或临时故障）")
            logger.info("llm_chat ok | resp_chars=%d", len(content))
            return content
        except Exception as e:
            last_err = e
            err_short = str(e)[:120]
            if attempt < LLM_MAX_RETRIES:
                wait = LLM_RETRY_BASE * (2 ** (attempt - 1))
                logger.warning("llm_chat failed (attempt %d/%d, retry in %.1fs) | %s",
                               attempt, LLM_MAX_RETRIES, wait, err_short)
                time.sleep(wait)
                continue
            logger.error("llm_chat failed (final %d/%d) | %s", attempt, LLM_MAX_RETRIES, err_short)
            break
    raise RuntimeError(f"LLM 调用失败（已重试 {LLM_MAX_RETRIES} 次）：{last_err}")


def parse_script_from_prompt(user_input: str) -> str:
    prompt = f"""你是短剧编剧，根据用户创意输出短剧剧本。
用户创意：{user_input}

要求：
1. 严格遵循用户创意中点明的角色数量、场景数量、分镜数量（如用户写"3个分镜"就只写 3 个分镜，不要扩写成十几镜）。
2. 若用户未明确数量，则按剧情需要合理确定，短剧本通常 3~6 个分镜即可，避免冗长。
3. 剧本格式：先写标题、角色列表（每个角色一段外貌性格描述），再写场景，最后按顺序列出每个分镜（标注镜号、场景、画面与动作、台词）。
4. 台词、动作、场景都要具体，便于后续拆解成分镜脚本。
"""
    return llm_chat([{"role": "user", "content": prompt}])
