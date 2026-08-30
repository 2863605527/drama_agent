"""TTS 配音工具：为分镜视频生成台词/旁白语音。

背景：火山即梦文生视频 API（jimeng_t2v_v30）本身不生成音频，
分镜视频天然无声 —— 这是模型能力边界，不是代码 bug。
本工具用 edge-tts（微软 Edge 在线语音合成，免费、无需 API Key）
把大模型为每个分镜写的台词/旁白合成为语音，再由 video_tool 混入视频。

环境变量（.env）：
  ENABLE_TTS=1            # 是否启用配音（1/true 开启，0/false 关闭，默认开启）
  TTS_VOICE=zh-CN-XiaoxiaoNeural   # 音色，常用可选：
                           #   zh-CN-XiaoxiaoNeural   女声·温柔（默认）
                           #   zh-CN-YunxiNeural      男声·阳光
                           #   zh-CN-YunyangNeural    男声·播音
                           #   zh-CN-XiaoyiNeural     女声·活泼
  TTS_RATE=+8%             # 语速（-50% ~ +100%）
"""
import os
import re
import asyncio
from dotenv import load_dotenv
from tools.logger_tool import get_logger

logger = get_logger("drama.tts")

load_dotenv()

ENABLE_TTS = os.getenv("ENABLE_TTS", "1").strip().lower() in ("1", "true", "yes", "on")
TTS_VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
TTS_RATE = os.getenv("TTS_RATE", "+8%")

# edge-tts 是可选依赖：未安装/不可联网时自动降级为静音视频，不阻断主流程
try:
    import edge_tts
    _EDGE_OK = True
except ImportError:
    _EDGE_OK = False
    logger.warning("edge-tts 未安装，分镜视频将无配音（pip install edge-tts 可启用）")


def _clean_lines(lines: str) -> str:
    """清洗台词文本：去掉角色名前缀中的@、多余空白；空镜返回空串。"""
    if not lines:
        return ""
    text = str(lines).strip()
    if not text:
        return ""
    # 去掉 "角色名：" 前缀（TTS 不应读出角色名），保留台词本体
    text = re.sub(r"^@?[^\s：:]{1,12}[：:]\s*", "", text, flags=re.MULTILINE)
    # 去掉残留的 @角色名 标注
    text = re.sub(r"@\S+", "", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def synthesize_speech(lines: str, out_path: str, voice: str = None, rate: str = None) -> str:
    """把台词/旁白合成为 mp3 音频文件，返回音频路径；无台词或失败返回空串。"""
    if not ENABLE_TTS or not _EDGE_OK:
        return ""
    text = _clean_lines(lines)
    if not text:
        return ""
    voice = voice or TTS_VOICE
    rate = rate or TTS_RATE
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        tts = edge_tts.Communicate(text, voice, rate=rate)
        asyncio.run(_save(tts, out_path))
        if os.path.exists(out_path) and os.path.getsize(out_path) > 512:
            logger.info("tts ok | %s | voice=%s | %d chars | %d bytes",
                        out_path, voice, len(text), os.path.getsize(out_path))
            return out_path
        logger.warning("tts output too small, ignore | %s", out_path)
        return ""
    except Exception as e:
        # TTS 失败不应阻断视频生成主流程
        logger.warning("tts failed (fallback to silent) | err=%s", str(e)[:150])
        return ""


async def _save(tts, out_path: str):
    await tts.save(out_path)
