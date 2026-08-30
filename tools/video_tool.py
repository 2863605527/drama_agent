import os
import re
import time
import subprocess
import json
from dotenv import load_dotenv
from tools import media_channel
from tools.media_channel import (
    cv_submit, cv_get_result, submit_video, poll_video,
    has_audio_stream, video_has_native_audio,
)
from tools.logger_tool import get_logger

logger = get_logger("drama.video")

load_dotenv()

from tools.brand_errors import translate_brand_error  # noqa: E402


def _translate_brand_error(resp):
    """视频错误翻译（共用 brand_errors.translate_brand_error + '视频' 标识）"""
    return translate_brand_error(resp, kind="视频")

# ===== 视频模型 req{} 参数（全部支持环境变量覆盖，可切换火山即梦不同文生视频模型）=====
# 模型 req_key，例如：jimeng_t2v_v30 / jimeng_t2v_v20 / jimeng_i2v_v21 等
VIDEO_REQ_KEY = os.getenv("VIDEO_REQ_KEY", "jimeng_t2v_v30")
# 单镜兜底时长（秒）：LLM 未分配时长时使用（通常会被大模型按剧本分配的 duration 覆盖）
VIDEO_DURATION = int(os.getenv("VIDEO_DURATION", "4"))
# 分辨率：720p / 1080p
VIDEO_RESOLUTION = os.getenv("VIDEO_RESOLUTION", "720p")
# 50430 并发限制时的等待重试序列（秒）：遇到并发上限会依次等待，累计最长约 3.5 分钟
VIDEO_RETRY_WAIT = [5, 10, 20, 40, 60, 60]

# ===== 视频时长策略（换模型只改 .env，不改代码）=====
# 平台支持的时长档位（秒），逗号分隔，如 "5,10" 表示平台只支持 5s/10s 两档（生成后裁剪到目标秒数）；
# 设为 any 表示平台支持任意时长（如 Seedance 1~15s 原生精确时长 + 自带音频），请求直接传 duration、无需裁剪
VIDEO_DURATION_SLOTS = os.getenv("VIDEO_DURATION_SLOTS", "5,10").strip().lower()
# 档位模式下各档位对应的请求参数字段值（逗号分隔，与 VIDEO_DURATION_SLOTS 一一对应）；any 模式下忽略
VIDEO_SLOT_FRAMES = os.getenv("VIDEO_SLOT_FRAMES", "121,241")
# 档位模式的请求参数字段名（火山即梦用 frames；换模型若用 duration_seconds 等其他字段，只改这里）
VIDEO_SLOT_PARAM = os.getenv("VIDEO_SLOT_PARAM", "frames")
# 任意时长模式的请求参数字段名（默认 duration；部分模型要求 seconds 等，可改）
VIDEO_ANY_PARAM = os.getenv("VIDEO_ANY_PARAM", "duration")
# LLM 可分配的单镜时长范围 min,max（档位制受平台档位约束，默认 2,10；任意时长模型可放宽，如 Seedance 可配 1,15）
VIDEO_DURATION_RANGE = os.getenv("VIDEO_DURATION_RANGE", "2,10")
# 生成后是否用 ffmpeg 裁剪到 LLM 分配的精确秒数：档位制=true（生成 5/10s 再裁剪）；
# 任意时长模型=false（原生精确时长，只混音不裁剪，避免二次压缩损伤画质）
VIDEO_TRIM = os.getenv("VIDEO_TRIM", "true").strip().lower() in ("1", "true", "yes", "on")

# 注意：cv 通道的 VisualService 与图片共用，统一由 media_channel 惰性初始化，
# 换供应商只改 .env 的 VIDEO_CHANNEL（volc_cv / volc_ark / generic_http），代码无需改动。


def _parse_slots():
    """解析时长档位配置。
    返回 [(档位秒数, 请求参数值), ...]（升序），或 None 表示任意时长模式。"""
    if VIDEO_DURATION_SLOTS in ("", "any", "none", "-"):
        return None
    slots = [float(x.strip()) for x in VIDEO_DURATION_SLOTS.split(",") if x.strip()]
    vals = [x.strip() for x in VIDEO_SLOT_FRAMES.split(",") if x.strip()]
    pairs = []
    for i, sec in enumerate(slots):
        pairs.append((sec, vals[i] if i < len(vals) else ""))
    return sorted(pairs)


VIDEO_SLOT_PAIRS = _parse_slots()

logger.info("video config | req_key=%s | duration=%ds | res=%s | slots=%s | range=%s | trim=%s",
            VIDEO_REQ_KEY, VIDEO_DURATION, VIDEO_RESOLUTION,
            VIDEO_DURATION_SLOTS if VIDEO_SLOT_PAIRS is None else [int(s) for s, _ in VIDEO_SLOT_PAIRS],
            VIDEO_DURATION_RANGE, VIDEO_TRIM)


def resolve_duration_params(target_seconds) -> tuple:
    """把 LLM 按剧本分配的「目标时长」解析为平台可用的请求参数。
    返回 (请求参数 dict, 实际生成秒数)，换模型无需改这里，只改 .env 配置即可。

    - 任意时长模式（VIDEO_DURATION_SLOTS=any）：直接传 target 秒，无需裁剪
    - 档位模式：选择「>= target 的最小档位」提交（不足取最大档位），生成后再由 finalize_shot_video 裁剪
    """
    target = max(1, int(target_seconds))
    if VIDEO_SLOT_PAIRS is None:
        return {VIDEO_ANY_PARAM: target}, target
    chosen_sec, chosen_val = VIDEO_SLOT_PAIRS[-1]  # 默认取最大档位（target 超过所有档位时）
    for sec, val in VIDEO_SLOT_PAIRS:
        if sec >= target:
            chosen_sec, chosen_val = sec, val
            break
    # 即梦视频（jimeng_t2v_v30 → 后端 seedance_t2v_com）的 frames 参数必须是整数，
    # 传字符串会报 50200 Invalid Input Parameters（json cannot unmarshal string into int）
    if VIDEO_SLOT_PARAM == "frames":
        try:
            chosen_val = int(chosen_val)
        except (ValueError, TypeError):
            pass
    return {VIDEO_SLOT_PARAM: chosen_val}, int(chosen_sec)


def submit_video_task(shot_prompt: str, char_ref_url: str = None, duration: int = None) -> str:
    """提交文生视频任务，返回 task_id，异步。
    duration 优先使用调用方传入值（大模型按剧本节奏分配），未传入则用环境变量 VIDEO_DURATION。
    时长参数完全由 .env 的时长策略配置驱动：
      - 档位制（如即梦 frames=121/241）：按目标时长选档位提交，下载后 ffmpeg 裁剪到精确秒数
      - 任意时长制（如 Seedance 1~15s）：直接传 duration，原生精确时长"""
    if duration is None:
        duration = VIDEO_DURATION
    duration = max(1, int(duration))
    dur_params, gen_seconds = resolve_duration_params(duration)
    if gen_seconds < duration:
        logger.warning("LLM allocated %ds but model max slot is %ds, will generate %ds (考虑换支持更长时长的模型或调大 VIDEO_DURATION_RANGE 对应档位)",
                       duration, gen_seconds, gen_seconds)
    # 通道分发：方舟 / 通用 HTTP 通道直接交给 media_channel（换供应商只改 .env，不改代码）
    if media_channel.VIDEO_CHANNEL != media_channel.CH_VOLC_CV:
        return submit_video(shot_prompt, char_ref_url, dur_params, gen_seconds)
    req = {
        "req_key": VIDEO_REQ_KEY,
        "prompt": shot_prompt,
        "resolution": VIDEO_RESOLUTION,
        "return_url": True,
    }
    req.update(dur_params)  # frames 档位 或 duration 字段，由配置决定
    # 如果有角色参考图，开启图生视频参考
    if char_ref_url:
        req["image_url"] = char_ref_url
    logger.info("submit video task | prompt=%s… | ref_img=%s | target=%ds | gen=%ds | params=%s",
                shot_prompt[:60], bool(char_ref_url), duration, gen_seconds, dur_params)
    # 提交（50430 并发限制时按退避序列等待重试，避免用户同时生成多个分镜视频时直接失败）
    retries = 0
    while True:
        try:
            resp = cv_submit(req)
        except Exception as e:
            # SDK 抛错（如网络/认证）：把异常 message 当作原始错误传入翻译
            raise Exception(_translate_brand_error(e)) from None
        code = resp.get("code")
        if code in (0, 10000):
            task_id = resp["data"]["task_id"]
            return task_id
        msg = str(resp.get("message", ""))
        # 并发限制：等待后重试
        if code == 50430 or "Concurrent Limit" in msg or "并发" in msg:
            if retries >= len(VIDEO_RETRY_WAIT):
                raise Exception(
                    "视频服务并发繁忙，已自动重试多次仍受限，请稍后再试"
                    "（可到 .env 调小 VIDEO_MAX_CONCURRENCY 减少同时生成数）"
                )
            wait = VIDEO_RETRY_WAIT[retries]
            logger.warning("video 50430 concurrent limit | retry %d/%d | wait %ds | msg=%s",
                           retries + 1, len(VIDEO_RETRY_WAIT), wait, msg[:100])
            retries += 1
            time.sleep(wait)
            continue
        # 服务未开通 / 权限不足
        if code == 50400 or "Access Denied" in msg:
            raise Exception(
                "视频服务未开通：请到火山引擎控制台开通「即梦AI-视频生成3.0 720P」服务"
                "(https://console.volcengine.com/ai/overview)，然后再试"
            )
        raise Exception(_translate_brand_error(resp))


def query_video_result(task_id: str, timeout=300):
    """轮询查询视频结果，超时5分钟。cv 通道走即梦查询接口；方舟/通用 HTTP 通道走 media_channel"""
    logger.info("poll video result | task=%s | timeout=%ds | channel=%s",
                task_id, timeout, media_channel.VIDEO_CHANNEL)
    start = time.time()
    while time.time() - start < timeout:
        if media_channel.VIDEO_CHANNEL != media_channel.CH_VOLC_CV:
            # 方舟 / 通用 HTTP：一次轮询返回状态
            st = poll_video(task_id)
            if st["status"] == "succeeded":
                if not st.get("video_url"):
                    raise Exception("视频生成成功但服务商未返回视频地址，请重试")
                logger.info("video done | task=%s | %ds elapsed", task_id, int(time.time() - start))
                return {"ok": True, "video_url": st["video_url"]}
            if st["status"] in ("failed", "cancelled", "cancel"):
                logger.warning("video %s | task=%s", st["status"], task_id)
                err_msg = st.get("error")
                if err_msg:
                    return {"ok": False, "msg": _translate_brand_error(err_msg)}
                status_zh = {"failed": "失败", "cancelled": "已取消", "cancel": "已取消"}.get(st["status"], st["status"])
                return {"ok": False, "msg": f"视频生成{status_zh}"}
            time.sleep(5)
            continue
        req = {"req_key": VIDEO_REQ_KEY, "task_id": task_id}
        try:
            resp = cv_get_result(req)
        except Exception as e:
            # SDK 抛错：把异常 message 翻译为中文
            raise Exception(_translate_brand_error(e)) from None
        if resp.get("code") not in (0, 10000):
            raise Exception(_translate_brand_error(resp))
        status = resp["data"]["status"]
        if status == "done":
            video_url = resp["data"]["video_url"]
            logger.info("video done | task=%s | %ds elapsed", task_id, int(time.time() - start))
            return {"ok": True, "video_url": video_url}
        if status in ["failed", "cancel"]:
            logger.warning("video %s | task=%s", status, task_id)
            return {"ok": False, "msg": _translate_brand_error(resp)}
        time.sleep(5)
    logger.error("video timeout | task=%s", task_id)
    return {"ok": False, "msg": "任务超时"}


# ---------------- 视频合成 ----------------

def _ffmpeg_exe() -> str:
    """获取 ffmpeg 可执行文件路径（优先系统安装，兜底 imageio-ffmpeg 自带的二进制）"""
    import shutil
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise RuntimeError("未找到 ffmpeg，请安装 imageio-ffmpeg（pip install imageio-ffmpeg）或系统 ffmpeg") from e


def download_video(url: str, save_path: str) -> str:
    """下载远程视频到本地文件，返回保存路径"""
    import requests
    logger.info("download video | %s… -> %s", url[:70], save_path)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    logger.info("download video ok | %s", save_path)
    return save_path


def finalize_shot_video(video_path: str, duration: int, audio_path: str = None, trim: bool = None) -> str:
    """分镜视频落盘后的后处理（原地覆盖 video_path）：
    1. 裁剪到 LLM 分配的精确时长（仅档位制模型需要：API 生成 5s/10s 档位，裁剪到目标秒数；
       任意时长模型设 VIDEO_TRIM=false 原生精确，跳过裁剪避免二次压缩）；
    2. 混入配音音轨（audio_path 有值时）或静音 AAC 音轨（文生视频原生无音频时）。
    语音比视频长时自动截断，比视频短时自动补静音（apad + -shortest）。
    若视频自带音轨（如方舟 Seedance 原生音频）且无需裁剪，直接原样保留，不做二次编码。"""
    ff = _ffmpeg_exe()
    duration = max(1, int(duration))
    if trim is None:
        trim = VIDEO_TRIM
    # 原生带音频 + 不裁剪 + 无配音：无需任何后处理，保留原视频（避免二次压缩损伤画质/音质）
    if not trim and audio_path is None and has_audio_stream(video_path):
        logger.info("video has native audio & no trim, keep as-is | %s", video_path)
        return video_path
    tmp_out = video_path + "._final.mp4"
    if audio_path and os.path.exists(audio_path):
        a_in = ["-i", audio_path]
        a_map = ["-map", "0:v:0", "-map", "1:a:0", "-af", "apad"]
    else:
        # 静音占位音轨：保证视频有标准 AAC 音轨（部分播放器对无音轨视频会异常）
        a_in = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        a_map = ["-map", "0:v:0", "-map", "1:a:0"]
    out_opts = [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart",
    ]
    if trim:
        # 裁剪到目标秒数（档位制模型：生成 5s/10s → 裁剪为 LLM 分配的秒数）
        out_opts = ["-t", str(duration)] + out_opts
    cmd = [ff, "-y", "-i", video_path] + a_in + a_map + out_opts + [tmp_out]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not os.path.exists(tmp_out):
        # 后处理失败不阻断主流程：保留原始视频（只是没有音轨/未裁剪）
        logger.warning("finalize_shot_video failed, keep raw video | %s | %s",
                       video_path, proc.stderr[-200:] if proc.stderr else "unknown")
        try:
            os.remove(tmp_out)
        except OSError:
            pass
        return video_path
    os.replace(tmp_out, video_path)
    logger.info("finalize shot video ok | %s | %.1fs | audio=%s",
                video_path, duration, bool(audio_path))
    return video_path


def probe_resolution(video_path: str) -> tuple:
    """用 ffprobe/ffmpeg 探测视频分辨率，返回 (width, height)，失败返回 (1080, 1920)"""
    ff = _ffmpeg_exe()
    cmd = [ff, "-i", video_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        m = re.search(r"(\d{2,4})x(\d{2,4})", proc.stderr)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 1080, 1920


def mix_segment_audio(video_path: str, audio_items: list, duration: float, trim: bool = None) -> str:
    """片段视频配音（多分镜台词按各自起始毫秒精确对齐混入，参考小云雀片段模式）：
    一个片段视频由多个分镜组成，每个分镜的 TTS 配音用 adelay 推迟到该分镜的起始时刻，
    再 amix 叠加成一条音轨混入视频 —— 音画时间轴天然对齐（模型按 duration-ms 执行分镜节奏）。
    :param video_path: 片段视频本地路径（原地覆盖）
    :param audio_items: [(audio_path, start_ms), ...] 每条配音及其在片段内的起始毫秒
    :param duration: 片段总时长（秒），trim=True 时裁剪到该时长
    """
    ff = _ffmpeg_exe()
    if trim is None:
        trim = VIDEO_TRIM
    audio_items = [(p, max(0, int(ms))) for p, ms in audio_items if p and os.path.exists(p)]
    if not audio_items:
        return finalize_shot_video(video_path, duration, None, trim)
    inputs = ["-i", video_path]
    filters, labels = [], []
    for i, (ap, start_ms) in enumerate(audio_items):
        inputs += ["-i", ap]
        # 立体声双通道各延迟 start_ms；先 aresample 统一采样率避免 amix 报错
        filters.append(f"[{i + 1}:a]aresample=48000,adelay={start_ms}|{start_ms}[a{i}]")
        labels.append(f"[a{i}]")
    fc = ";".join(filters) + ";" + "".join(labels) + \
        f"amix=inputs={len(labels)}:normalize=0,apad[aout]"
    tmp_out = video_path + "._seg.mp4"
    out_opts = [
        "-map", "0:v:0", "-map", "[aout]",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
    ]
    if trim:
        # 档位制模型：按档位生成（如 10s）后裁剪到片段精确总时长；需重编码视频
        out_opts = ["-t", str(duration), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"] + out_opts
    else:
        # 任意时长模型：原生精确时长，视频流直接 copy 不做二次压缩
        out_opts = ["-c:v", "copy"] + out_opts
    cmd = [ff, "-y"] + inputs + ["-filter_complex", fc] + out_opts + [tmp_out]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0 or not os.path.exists(tmp_out):
            raise RuntimeError(proc.stderr[-300:] if proc.stderr else "ffmpeg mix failed")
        os.replace(tmp_out, video_path)
        logger.info("mix segment audio ok | %s | %.1fs | %d cues", video_path, duration, len(audio_items))
        return video_path
    except Exception as e:
        # 混音失败不阻断主流程：退回单轨整体混入（不做时间对齐）
        logger.warning("mix_segment_audio failed, fallback to whole-track dub | %s | %s", video_path, str(e)[-200:])
        try:
            os.remove(tmp_out)
        except OSError:
            pass
        first_audio = audio_items[0][0]
        return finalize_shot_video(video_path, duration, first_audio, trim)


def compose_videos(video_paths: list, output_path: str, progress_cb=None) -> str:
    """
    将多个分镜视频按顺序合成为一个完整视频（ffmpeg 归一化 + concat + 重编码）。
    :param video_paths: 本地分镜视频路径列表（按分镜顺序）
    :param output_path: 合成视频输出路径
    :param progress_cb: 可选回调 progress_cb(index, total)
    :return: output_path
    """
    if not video_paths:
        raise ValueError("没有可合成的分镜视频")
    ff = _ffmpeg_exe()
    work_dir = os.path.dirname(output_path)
    os.makedirs(work_dir, exist_ok=True)

    # 1. 以第一个视频的分辨率为基准，所有分镜统一 scale + pad（竖屏短剧默认 1080x1920）
    w, h = probe_resolution(video_paths[0])
    if w >= h:
        tw, th = 1920, 1080
    else:
        tw, th = 1080, 1920
    vf = (
        f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
        f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,format=yuv420p"
    )

    # 2. 归一化每个分镜（避免不同编码/参数导致 concat 失败），失败的分镜直接跳过并记录。
    #    默认模型（即梦 cv 通道）生成视频无音轨，额外加入 anullsrc 静音轨确保合成后有声音轨道；
    #    若源视频自带音轨（如方舟 Seedance 原生音频），则保留原音轨，不再叠加静音。
    norm_list, total = [], len(video_paths)
    for i, src in enumerate(video_paths):
        if progress_cb:
            progress_cb(i + 1, total)
        dst = os.path.join(work_dir, f"_norm_{i:03d}.mp4")
        if has_audio_stream(src):
            a_in, a_map = [], ["-map", "0:v:0", "-map", "0:a:0"]
        else:
            a_in, a_map = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"], ["-map", "0:v:0", "-map", "1:a:0"]
        cmd = [
            ff, "-y",
            "-i", src,
        ] + a_in + [
            "-vf", vf,
        ] + a_map + [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-shortest", dst
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode != 0 or not os.path.exists(dst):
                continue
            norm_list.append(dst)
        except Exception:
            continue

    if not norm_list:
        raise RuntimeError("所有分镜视频均无法处理，合成失败")

    # 3. concat demuxer 合并 + 最终重编码输出（list 中写绝对路径，避免相对路径解析错误）
    logger.info("ffmpeg concat | %d normalized clips -> %s", len(norm_list), output_path)
    list_file = os.path.join(work_dir, "_concat_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in norm_list:
            abs_p = os.path.abspath(p).replace("\\", "/")
            f.write(f"file '{abs_p.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n")
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", output_path]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0 or not os.path.exists(output_path):
        raise RuntimeError(f"ffmpeg 合成失败：{proc.stderr[-300:]}")
    # 清理归一化中间文件
    for p in norm_list:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.remove(list_file)
    except OSError:
        pass
    return output_path
