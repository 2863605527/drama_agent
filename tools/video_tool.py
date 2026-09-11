import os
import re
import time
import subprocess
from dotenv import load_dotenv
from tools import media_channel
from tools.media_channel import (
    cv_submit, cv_get_result, submit_video, poll_video,
    has_audio_stream,
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
VIDEO_DURATION_SLOTS = os.getenv("VIDEO_DURATION_SLOTS", "5,10").strip().lower()
VIDEO_SLOT_FRAMES = os.getenv("VIDEO_SLOT_FRAMES", "121,241")
VIDEO_SLOT_PARAM = os.getenv("VIDEO_SLOT_PARAM", "frames")
VIDEO_ANY_PARAM = os.getenv("VIDEO_ANY_PARAM", "duration")
VIDEO_DURATION_RANGE = os.getenv("VIDEO_DURATION_RANGE", "2,10")
VIDEO_TRIM = os.getenv("VIDEO_TRIM", "true").strip().lower() in ("1", "true", "yes", "on")


def _parse_slots():
    """解析时长档位配置，返回 [(档位秒数, 请求参数值), ...]（升序），或 None 表示任意时长模式。"""
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
    """把 LLM 分配的目标时长解析为平台可用的请求参数，返回 (请求参数 dict, 实际生成秒数)。"""
    target = max(1, int(target_seconds))
    if VIDEO_SLOT_PAIRS is None:
        return {VIDEO_ANY_PARAM: target}, target
    chosen_sec, chosen_val = VIDEO_SLOT_PAIRS[-1]
    for sec, val in VIDEO_SLOT_PAIRS:
        if sec >= target:
            chosen_sec, chosen_val = sec, val
            break
    if VIDEO_SLOT_PARAM == "frames":
        try:
            chosen_val = int(chosen_val)
        except (ValueError, TypeError):
            pass
    return {VIDEO_SLOT_PARAM: chosen_val}, int(chosen_sec)


def _cv_req_key(profile):
    return media_channel._p(profile, "req_key", VIDEO_REQ_KEY)


def _cv_resolution(profile):
    return media_channel._p(profile, "resolution", VIDEO_RESOLUTION)


def submit_video_task(shot_prompt: str, char_ref_url: str = None, duration: int = None,
                      profile=None) -> str:
    """提交文生视频任务，返回 task_id。profile 为用户运行时通道配置（可空，走 .env 默认）。"""
    if duration is None:
        duration = VIDEO_DURATION
    duration = max(1, int(duration))
    dur_params, gen_seconds = resolve_duration_params(duration)
    if gen_seconds < duration:
        logger.warning("LLM allocated %ds but model max slot is %ds, will generate %ds",
                       duration, gen_seconds, gen_seconds)
    channel = media_channel.effective_video_channel(profile)
    # 方舟 / 通用 HTTP 通道交给 media_channel（透传 profile）
    if channel != media_channel.CH_VOLC_CV:
        return submit_video(shot_prompt, char_ref_url, dur_params, gen_seconds, profile)
    req = {
        "req_key": _cv_req_key(profile),
        "prompt": shot_prompt,
        "resolution": _cv_resolution(profile),
        "return_url": True,
    }
    req.update(dur_params)
    refs = media_channel._ref_list(char_ref_url)
    if refs:
        # 即梦图生视频只接受单张首帧：取第一张（场景图）。本地 /assets 转 base64，远程传 URL
        first_ref = refs[0]
        local_data = media_channel._local_image_to_data_url(first_ref)
        if local_data and local_data.startswith("data:"):
            req["binary_data_base64"] = [local_data.split(",", 1)[1]]
        else:
            req["image_url"] = first_ref
    logger.info("submit video task | prompt=%s… | ref_imgs=%d (cv uses first) | target=%ds | gen=%ds | params=%s",
                shot_prompt[:60], len(refs), duration, gen_seconds, dur_params)
    retries = 0
    while True:
        try:
            resp = cv_submit(req, profile)
        except Exception as e:
            raise Exception(_translate_brand_error(e)) from None
        code = resp.get("code")
        if code in (0, 10000):
            return resp["data"]["task_id"]
        msg = str(resp.get("message", ""))
        if code == 50430 or "Concurrent Limit" in msg or "并发" in msg:
            if retries >= len(VIDEO_RETRY_WAIT):
                raise Exception(
                    "视频服务并发繁忙，已自动重试多次仍受限，请稍后再试"
                    "（可到 .env 调小 VIDEO_MAX_CONCURRENCY 减少同时生成数）"
                )
            wait = VIDEO_RETRY_WAIT[retries]
            logger.warning("video 50430 concurrent limit | retry %d/%d | wait %ds",
                           retries + 1, len(VIDEO_RETRY_WAIT), wait)
            retries += 1
            time.sleep(wait)
            continue
        if code == 50400 or "Access Denied" in msg:
            raise Exception(
                "视频服务未开通：请到火山引擎控制台开通「即梦AI-视频生成3.0 720P」服务"
                "(https://console.volcengine.com/ai/overview)，然后再试"
            )
        raise Exception(_translate_brand_error(resp))


def query_video_result(task_id: str, timeout=300, profile=None):
    """轮询直到出片，统一返回 {ok, video_url, msg}。cv 走即梦查询；方舟/HTTP 走 media_channel。"""
    channel = media_channel.effective_video_channel(profile)
    logger.info("poll video result | task=%s | timeout=%ds | channel=%s", task_id, timeout, channel)
    start = time.time()
    while time.time() - start < timeout:
        if channel != media_channel.CH_VOLC_CV:
            st = poll_video(task_id, profile)
            if st["status"] == "succeeded":
                if not st.get("video_url"):
                    raise Exception("视频生成成功但服务商未返回视频地址，请重试")
                logger.info("video done | task=%s | %ds elapsed", task_id, int(time.time() - start))
                return {"ok": True, "video_url": st["video_url"]}
            if st["status"] in ("failed", "cancelled", "cancel"):
                err_msg = st.get("error")
                if err_msg:
                    return {"ok": False, "msg": _translate_brand_error(err_msg)}
                status_zh = {"failed": "失败", "cancelled": "已取消", "cancel": "已取消"}.get(
                    st["status"], st["status"])
                return {"ok": False, "msg": f"视频生成{status_zh}"}
            time.sleep(5)
            continue
        req = {"req_key": _cv_req_key(profile), "task_id": task_id}
        try:
            resp = cv_get_result(req, profile)
        except Exception as e:
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


# ---------------- 视频下载 / 后处理（本地 ffmpeg，与通道无关）----------------

def _ffmpeg_exe() -> str:
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
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(save_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
    logger.info("download video ok | %s", save_path)
    return save_path


def finalize_shot_video(video_path: str, duration: int, audio_path: str = None, trim: bool = None) -> str:
    """分镜视频落盘后处理（原地覆盖）：裁剪到精确时长 + 混入配音/静音轨；原生音频且不裁剪则原样保留。"""
    ff = _ffmpeg_exe()
    duration = max(1, int(duration))
    if trim is None:
        trim = VIDEO_TRIM
    if not trim and audio_path is None and has_audio_stream(video_path):
        logger.info("video has native audio & no trim, keep as-is | %s", video_path)
        return video_path
    tmp_out = video_path + "._final.mp4"
    if audio_path and os.path.exists(audio_path):
        a_in = ["-i", audio_path]
        a_map = ["-map", "0:v:0", "-map", "1:a:0", "-af", "apad"]
    else:
        a_in = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        a_map = ["-map", "0:v:0", "-map", "1:a:0"]
    out_opts = [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-shortest", "-movflags", "+faststart",
    ]
    if trim:
        out_opts = ["-t", str(duration)] + out_opts
    cmd = [ff, "-y", "-i", video_path] + a_in + a_map + out_opts + [tmp_out]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not os.path.exists(tmp_out):
        logger.warning("finalize_shot_video failed, keep raw video | %s | %s",
                       video_path, proc.stderr[-200:] if proc.stderr else "unknown")
        try:
            os.remove(tmp_out)
        except OSError:
            pass
        return video_path
    os.replace(tmp_out, video_path)
    logger.info("finalize shot video ok | %s | %.1fs | audio=%s", video_path, duration, bool(audio_path))
    return video_path


def probe_resolution(video_path: str) -> tuple:
    """探测视频分辨率，返回 (width, height)，失败返回 (1080, 1920)"""
    ff = _ffmpeg_exe()
    try:
        proc = subprocess.run([ff, "-i", video_path], capture_output=True, text=True, timeout=60)
        m = re.search(r"(\d{2,4})x(\d{2,4})", proc.stderr)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return 1080, 1920


def mix_segment_audio(video_path: str, audio_items: list, duration: float, trim: bool = None) -> str:
    """片段视频配音：多分镜 TTS 按起始毫秒 adelay 对齐后 amix 混入（原地覆盖）。"""
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
        out_opts = ["-t", str(duration), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20"] + out_opts
    else:
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
        logger.warning("mix_segment_audio failed, fallback to whole-track dub | %s | %s",
                       video_path, str(e)[-200:])
        try:
            os.remove(tmp_out)
        except OSError:
            pass
        first_audio = audio_items[0][0]
        return finalize_shot_video(video_path, duration, first_audio, trim)


def compose_videos(video_paths: list, output_path: str, progress_cb=None) -> str:
    """将多个片段/分镜视频按顺序归一化后 concat 合成为完整视频。"""
    if not video_paths:
        raise ValueError("没有可合成的分镜视频")
    ff = _ffmpeg_exe()
    work_dir = os.path.dirname(output_path)
    os.makedirs(work_dir, exist_ok=True)

    w, h = probe_resolution(video_paths[0])
    tw, th = (1920, 1080) if w >= h else (1080, 1920)
    vf = (
        f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
        f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,format=yuv420p"
    )

    norm_list, total = [], len(video_paths)
    for i, src in enumerate(video_paths):
        if progress_cb:
            progress_cb(i + 1, total)
        dst = os.path.join(work_dir, f"_norm_{i:03d}.mp4")
        if has_audio_stream(src):
            a_in, a_map = [], ["-map", "0:v:0", "-map", "0:a:0"]
        else:
            a_in, a_map = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"], ["-map", "0:v:0", "-map", "1:a:0"]
        cmd = [ff, "-y", "-i", src] + a_in + ["-vf", vf] + a_map + [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-shortest", dst,
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
