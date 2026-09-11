import os
import time
import uuid
import requests
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

# 远程图片 Content-Type -> 扩展名
_CT_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
           "image/webp": ".webp", "image/gif": ".gif"}


def persist_remote_image(url: str) -> str:
    """把供应商返回的远程图片下载到 assets/images 并返回本地 URL。

    供应商签名链接会过期（火山约 24h、硅基流动仅 1h），不落盘则刷新后裂图、图生图参考也会失效；
    下载失败时退回原远程 URL，不阻断主流程。本地 /assets、data: 原样返回。
    """
    if not url or not url.startswith(("http://", "https://")):
        return url
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        ct = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        ext = _CT_EXT.get(ct, ".png")
        img_dir = os.path.join("assets", "images")
        os.makedirs(img_dir, exist_ok=True)
        name = f"img_{uuid.uuid4().hex}{ext}"
        with open(os.path.join(img_dir, name), "wb") as f:
            f.write(resp.content)
        local = f"/assets/images/{name}"
        logger.info("image persisted | %s -> %s (%d KB)", url[:60], local, len(resp.content) // 1024)
        return local
    except Exception as e:
        logger.warning("persist image failed, keep remote url | %s", str(e)[:120])
        return url


def generate_character_image(char_desc: str, retries: int = 5, profile=None, ref_image_url: str = "") -> str:
    """
    调用图片生成（供应商/通道由 .env 的 IMAGE_CHANNEL 或用户 profile 决定），返回图片url（带重试，应对服务端瞬时故障）
    :param char_desc: 角色/场景描述prompt
    :param profile: 用户运行时通道配置（dict，已解密），为空则走 .env 默认通道
    :param ref_image_url: 参考图 URL，非空时走图生图（以该图为底图按 prompt 编辑），用于黑夜场景图参考白天图
    :return: 本地图片可访问url（生成后下载落盘，避免签名链接过期裂图）
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            logger.info("image gen attempt %d/%d | ref=%s | prompt=%s…",
                        attempt, retries, "yes" if ref_image_url else "no", char_desc[:60])
            url = generate_image(char_desc, IMAGE_WIDTH, IMAGE_HEIGHT, profile, ref_image_url)
            logger.info("image gen ok | %s…", url[:80])
            return persist_remote_image(url)
        except Exception as e:
            last_err = e
            err_text = str(e)
            logger.warning("image gen attempt %d failed: %s", attempt, err_text[:120])
            if attempt < retries:
                # 火山 50430/50400 并发限流：退避拉长，等并发窗口释放
                if "50430" in err_text or "50400" in err_text or "Concurrent" in err_text:
                    time.sleep(8 * attempt)
                else:
                    time.sleep(2 * attempt)
    # 把最后一次异常翻译为中文抛出
    if last_err is not None:
        raise Exception(translate_brand_error(last_err, kind="图片")) from None
    raise RuntimeError("图片生成失败：未知错误")
