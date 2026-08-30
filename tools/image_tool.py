import os
import time
from dotenv import load_dotenv
from tools.media_channel import generate_image
from tools.logger_tool import get_logger
from tools.brand_errors import translate_brand_error

logger = get_logger("drama.image")

load_dotenv()

# ===== 图片模型配置（换模型/换通道只改 .env，不改代码）=====
# cv 通道 req_key，例如：jimeng_high_aes_general_v21_L / jimeng_high_aes_general_v21 / seededit_v2.0_i2i 等；
# 换通道（IMAGE_CHANNEL=volc_ark / generic_http）时此值不生效，改用 ARK_IMAGE_MODEL / IMAGE_HTTP_URL
IMAGE_REQ_KEY = os.getenv("IMAGE_REQ_KEY", "jimeng_high_aes_general_v21_L")
# 出图尺寸（角色立绘为方图，分镜图共用同一模型）
IMAGE_WIDTH = int(os.getenv("IMAGE_WIDTH", "1024"))
IMAGE_HEIGHT = int(os.getenv("IMAGE_HEIGHT", "1024"))

logger.info("image config | req_key=%s | size=%dx%d", IMAGE_REQ_KEY, IMAGE_WIDTH, IMAGE_HEIGHT)


def generate_character_image(char_desc: str, retries: int = 5) -> str:
    """
    调用图片生成（供应商/通道由 .env 的 IMAGE_CHANNEL 决定），返回图片url（带重试，应对服务端瞬时故障）
    :param char_desc: 角色/场景描述prompt
    :return: 图片可访问url
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            logger.info("image gen attempt %d/%d | prompt=%s…", attempt, retries, char_desc[:60])
            url = generate_image(char_desc, IMAGE_WIDTH, IMAGE_HEIGHT)
            logger.info("image gen ok | %s…", url[:80])
            return url
        except Exception as e:
            last_err = e
            err_text = str(e)
            logger.warning("image gen attempt %d failed: %s", attempt, err_text[:120])
            if attempt < retries:
                # 火山 50430 并发限流：退避拉长，等并发窗口释放
                if "50430" in err_text or "Concurrent" in err_text:
                    time.sleep(8 * attempt)
                else:
                    time.sleep(2 * attempt)
    # 把最后一次异常翻译为中文抛出
    if last_err is not None:
        raise Exception(translate_brand_error(last_err, kind="图片")) from None
    raise RuntimeError("图片生成失败：未知错误")
