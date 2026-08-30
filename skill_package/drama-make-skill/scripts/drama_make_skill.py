import uuid
import json
import re
import os
import asyncio
import threading
from typing import Optional
from schema.drama_schema import DramaTask, TaskStatus, DramaScript, Character, Scene, Shot, Segment
from tools.llm_tool import parse_script_from_prompt, llm_chat
from tools.image_tool import generate_character_image
from tools.video_tool import submit_video_task, query_video_result, download_video, compose_videos, finalize_shot_video, mix_segment_audio
from tools.video_tool import video_has_native_audio, VIDEO_SLOT_PAIRS
from tools.tts_tool import synthesize_speech, ENABLE_TTS
from agent.progress_hub import progress_hub
from tools.logger_tool import get_logger

logger = get_logger("drama.skill")

# 进程级视频生成并发控制：同一时刻最多同时生成 VIDEO_MAX_CONCURRENCY 个分镜视频，
# 超出配额的分镜自动排队等待（可配合 video_tool 的 50430 退避重试双保险），
# 避免火山 API 并发限制（code 50430）导致生成直接失败。
VIDEO_MAX_CONCURRENCY = max(1, int(os.getenv("VIDEO_MAX_CONCURRENCY", "2")))
_VIDEO_SLOT = threading.BoundedSemaphore(VIDEO_MAX_CONCURRENCY)
logger.info("video concurrency limit | max=%d concurrent tasks", VIDEO_MAX_CONCURRENCY)

# 图片生成并发控制：角色立绘与分镜图在同一阶段并行生成，
# 同一时刻最多 IMAGE_MAX_CONCURRENCY 张图片在生成（火山视觉服务并发有限，默认 3）。
IMAGE_MAX_CONCURRENCY = max(1, int(os.getenv("IMAGE_MAX_CONCURRENCY", "3")))
logger.info("image concurrency limit | max=%d concurrent tasks", IMAGE_MAX_CONCURRENCY)

# 单镜时长范围（LLM 分配约束，与 tools/video_tool.py 的 VIDEO_DURATION_RANGE 一致）：
# 档位制模型（如即梦 5s/10s）默认 2,10；换任意时长模型（如 Seedance 1~15s）时把 .env 的
# VIDEO_DURATION_RANGE 一并放宽即可，这里自动跟随，无需改代码。
_dr = [x.strip() for x in os.getenv("VIDEO_DURATION_RANGE", "2,10").split(",")]
VIDEO_DUR_MIN = max(1, int(_dr[0] or "2"))
VIDEO_DUR_MAX = max(VIDEO_DUR_MIN, int(_dr[1] or "10"))
logger.info("video duration range | %d~%d seconds (LLM allocatable)", VIDEO_DUR_MIN, VIDEO_DUR_MAX)

# 单个片段（多分镜连续视频）的总时长硬性上限（秒）：
# 超过该值必须在分组/拆分阶段强制切段，避免出现一条"装不下一整段表演"的超长视频。
# 默认 15 秒（对齐小云雀单条多分镜视频的合理时长；换支持更长时长的模型可调大）。
SEGMENT_MAX_DURATION = max(VIDEO_DUR_MIN, int(os.getenv("SEGMENT_MAX_DURATION", "15")))
logger.info("segment max duration | %ds (hard cap)", SEGMENT_MAX_DURATION)

def _extract_json(text: str):
    """从 LLM 输出中健壮地提取 JSON（兼容 ```json 代码块 + 字符串内真实换行）"""
    text = text.strip()
    # 去掉 markdown 代码块围栏
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    # 截取第一个 { 到最后一个 } 之间的内容
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"LLM 输出中未找到 JSON 对象: {text[:200]}")
    payload = text[start:end + 1]
    # LLM 偶尔会在字符串字面量里塞入真实换行/Tab（应当是 \n 转义形式），
    # 标准 JSON 不允许；先按 strict=False 让 json 容忍控制字符
    try:
        return json.loads(payload, strict=False)
    except json.JSONDecodeError:
        # 兜底：手工把字符串里的裸换行/制表/回车转义掉再解析
        sanitized = re.sub(r"[\x00-\x1f]", lambda m: "\\u%04x" % ord(m.group()), payload)
        return json.loads(sanitized)

class DramaMakeSkill:
    """短剧生产Skill，完整SOP业务流水线，支持人工审核断点"""
    def __init__(self):
        pass

    async def create_task(self, user_prompt: str, style: str = "anime") -> DramaTask:
        logger.info("create_task | style=%s | prompt=%s…", style, user_prompt[:60])
        task_id = str(uuid.uuid4())
        thread_id = str(uuid.uuid4())
        task = DramaTask(
            task_id=task_id,
            thread_id=thread_id,
            user_prompt=user_prompt,
            style=style,
            status=TaskStatus.PENDING
        )
        return task

    async def step1_parse_script(self, task: DramaTask) -> DramaTask:
        """步骤1：解析剧本"""
        tid = task.task_id
        await progress_hub.publish(tid, {"event": "status", "status": "parsing", "message": "📝 正在解析剧本…"})
        await progress_hub.publish(tid, {"event": "log", "message": "🤖 大模型正在起草剧本大纲…"})
        raw_text = await asyncio.to_thread(parse_script_from_prompt, task.user_prompt)
        await progress_hub.publish(tid, {"event": "log", "message": "✅ 剧本草稿生成完成，正在拆解角色与分镜…"})
        # 时长档位区间按 VIDEO_DURATION_RANGE 动态三等分（2~10 → 2~4/5~7/8~10；1~15 → 1~5/6~10/11~15）
        _span = VIDEO_DUR_MAX - VIDEO_DUR_MIN + 1
        _third = max(1, _span // 3)
        _b1_end = min(VIDEO_DUR_MIN + _third - 1, VIDEO_DUR_MAX)
        _b2_end = min(_b1_end + _third, VIDEO_DUR_MAX)
        _b3_start = _b2_end + 1
        if _b3_start > VIDEO_DUR_MAX:
            _b3_start = max(VIDEO_DUR_MIN, _b2_end - 1)  # 区间不足三档时合并兜底
        _band1 = f"{VIDEO_DUR_MIN}~{_b1_end}"
        _band2 = f"{_b1_end + 1}~{_b2_end}" if _b2_end > _b1_end else f"{_b1_end}~{_b2_end}"
        _band3 = f"{_b3_start}~{VIDEO_DUR_MAX}" if VIDEO_DUR_MAX > _b3_start else f"{_b3_start}~{_b3_start}"
        _conflict_min = VIDEO_DUR_MIN + max(1, (VIDEO_DUR_MAX - VIDEO_DUR_MIN) // 2)  # 冲突/高潮档位下限
        style_desc = self._style_prompt(task.style)
        parse_prompt = f"""把下面剧本解析为严格 JSON，包含：
- title: 剧本标题
- characters: 角色数组，每个角色包含：
  - char_id: 字符串（可填空）
  - name: 角色姓名
  - description: 极其详细的外貌描述（性别、年龄段、发型颜色与造型、脸型、眼形与瞳色、鼻梁、嘴唇、肤色、身高体型、服装的颜色/款式/材质、配饰、独特标记），描述必须保证同一角色在不同分镜中外貌100%一致（同一发型发色、同一服装款式、同一五官特征）
- scenes: 场景资产数组。先通读剧本，提取所有可能出现的独立场景（如"青云宗杂役房"、"黄昏街道"），每个场景包含：
  - scene_key: 场景标识（**必须用 4~8 字中文短语**，如"青云宗杂役房"、"黄昏街道"、"空教室"，不要用英文或拼音；同一场景的所有分镜必须填完全相同的 scene_key）
  - description: **纯场景环境描述**（绝不出现任何人物、动作、神态，只写场景地点、环境、主要物件、氛围、天气。例如："破旧的修仙界杂役房，清冷月光从木窗洒入，一盏豆油灯在桌上摇曳，墙皮斑驳，木床、破旧木桌、蒲团"）
- shots: 分镜数组，每个分镜包含：
  - shot_id: 字符串（可填空）
  - scene_key: 本镜场景名（必须对应 scenes 中的 scene_key）
  - content: 本镜场景描述（可引用 scenes 中对应 scene_key 的 description，再补充本镜光线、时间、氛围）
  - camera: 镜头（景别+机位+镜头运动，如："中景，平视机位"、"近景特写，镜头缓慢上摇至面部"、"远景，俯拍，镜头缓慢推近"）
  - lighting: 光影描述（如：自然光、逆光、暖色光、霓虹、冷调、伦勃朗布光）
  - duration: 整数（本镜视频时长，单位秒）。**时长完全由剧本内容与叙事节奏决定**，{VIDEO_DUR_MIN}~{VIDEO_DUR_MAX} 秒只是当前视频平台的技术上限（换平台会随之调整，不是固定档位），必须由你像导演一样按剧本节奏精确分配，严格执行以下计算规则：
    * 第一步·先算台词基础时长：数出本镜 lines 的台词总字数，按 4~5 字/秒的正常语速折算朗读秒数（旁白/内心独白同样计入），这就是该镜的台词时长
    * 第二步·叠加动作余量：有角色动作/走位/互动 → 台词时长 +1~2 秒；情绪高潮、冲突、打斗、追逐等复杂动作 → 台词时长 +2~3 秒且总长不低于 {_conflict_min} 秒
    * 第三步·无台词分镜按叙事功能定档：特写、情感酝酿、气氛铺垫 → 5~8 秒；过场、空镜、简单动作 → 2~4 秒
    * 最终 duration = 台词时长 + 动作余量，再 clamp 到 {VIDEO_DUR_MIN}~{VIDEO_DUR_MAX} 秒
    * 差异化硬性要求：全剧分镜时长必须长短交错、贴合叙事节奏，至少出现 3 种不同档位（{_band1} / {_band2} / {_band3} 各至少覆盖一镜），禁止所有分镜使用同一个时长，禁止相邻分镜时长相同
  - lines: 本镜的台词/旁白（用于后期配音，字符串，可为空""）。格式：每句一行，台词写成"角色名：台词内容"，旁白/内心独白直接写文字。没有台词也没有旁白就填空字符串。台词内容必须与剧本一致，不要自己编造。
  - mouth_open: 布尔值。本镜 lines 是否为角色**说出口的对白**（true=张嘴说话，视频生成时角色口型要与台词同步）；内心独白、旁白、画外音、无台词一律填 false（视频生成时角色不张嘴）
  - prompt: 中文视频提示词，像专业导演的分镜脚本一样详细描述本镜中角色在场景里的动作、表情、互动与表演层次，必须包含：景别与镜头运动、角色的具体动作与神态变化、面部朝向与视线方向、情绪转折；用@角色名标注本镜出现的角色。例如："@林小夏 站在樱花树下，中景平视，微风吹起她的长发，她先是低头凝视手中的信，眼神黯淡，随后缓缓抬头望向远方，视线穿过飘落的樱花，嘴角浮起一丝苦涩的笑"@陆远 从远处巷口缓缓走近，停在三步之外，欲言又止"
  - character_names: 本镜出现的角色name列表
- segments: 片段数组。**由你像导演/剪辑师一样决定剧本切成几个片段**，每个片段是一段连续表演、可一次生成一条多分镜视频。每个片段包含：
  - segment_id: 字符串（可填空，由系统补全）
  - scene_key: 本片段的主场景（取片段内首镜或主导场景的 scene_key）
  - shot_ids: 本片段包含的分镜 shot_id 列表（按剧本顺序，**多个分镜组成一个片段**）
  - 分组原则：① 同一连续场景的多个分镜应合为**一个片段**（不要每镜一段）；② 一个片段可含 2~4 个分镜；③ 场景切换才切新片段；④ **片段总时长（所有分镜 duration 之和）必须 ≤ {SEGMENT_MAX_DURATION} 秒（硬性上限，超过必须拆成两段，禁止出现 20 秒以上的长片段）**；⑤ 短剧本（3~6 镜）通常只切 1~2 个片段，禁止把每个分镜单独切成一段。

# 严格要求（务必遵守）
1. 画风统一：所有角色必须完全相同的艺术风格（{style_desc}），相同色调，相同线条，相同光影处理，如同来自同一动画/影视作品。场景描述也必须符合该画风与色调。
2. 场景 description 与分镜 content 严禁出现人物动作/神态/对白，只描述场景、环境、物件。人物形象在角色资产中单独生成。
3. 角色 description 必须极度详细（不少于 80 字），确保后续所有分镜中角色外形 100% 一致。
4. 分镜 prompt 用中文，角色名用@圈出，像导演分镜脚本一样写清景别、镜头运动、动作表演层次、面部朝向与视线、情绪转折。**台词/画外音/内心独白直接写进 prompt 描述里**（如"他嘴唇哆嗦着说：'你……你怎么知道？！'"、"同时画外音传来@陆远 不带感情的声音：'年化利息120%'"),不要把台词单独抽出来标注口型。
5. scene_key 必须全局唯一且稳定：同一场景的连续分镜填完全相同 scene_key，不同场景必须不同。
6. mouth_open 必须准确：只有角色真正张嘴说出的对白才填 true；内心独白、自语默念、旁白、画外音都填 false。
7. 只返回 JSON，不要 markdown 代码块。

# 剧本题材风格
{style_desc}

# 剧本内容
{raw_text}"""
        json_str = await asyncio.to_thread(llm_chat, [{"role": "user", "content": parse_prompt}])
        data = _extract_json(json_str)
        # 补全/规范化 LLM 可能返回的字段：id 必须是字符串
        for c in data["characters"]:
            c["char_id"] = str(c.get("char_id") or uuid.uuid4())

        # 场景解析与兜底：若 LLM 未返回 scenes，则从 shots 的 scene_key 自动生成
        raw_scenes = data.get("scenes") or []
        scene_map: dict = {}
        for sc in raw_scenes:
            key = str(sc.get("scene_key") or "").strip()
            if not key:
                continue
            sc["scene_key"] = key
            sc["description"] = str(sc.get("description") or "").strip()
            sc.setdefault("day_image_url", None)
            sc.setdefault("night_image_url", None)
            scene_map[key] = sc

        for _si, s in enumerate(data["shots"]):
            s["shot_id"] = str(s.get("shot_id") or uuid.uuid4())
            # 兜底：LLM 可能漏写 duration 或写超长/超短（范围跟随 .env VIDEO_DURATION_RANGE，换模型自动适配）
            dur = s.get("duration")
            try:
                dur = int(dur)
            except Exception:
                dur = min(4, VIDEO_DUR_MAX)
            if dur < VIDEO_DUR_MIN:
                dur = VIDEO_DUR_MIN
            if dur > VIDEO_DUR_MAX:
                dur = VIDEO_DUR_MAX
            s["duration"] = dur
            # 台词/旁白：用于 TTS 配音，容错处理
            lines = s.get("lines")
            if isinstance(lines, list):
                parts = []
                for x in lines:
                    if isinstance(x, dict):
                        ch = x.get("character") or x.get("name") or x.get("speaker") or ""
                        tx = x.get("text") or x.get("content") or x.get("line") or ""
                        if ch and tx:
                            parts.append(f"{ch}：{tx}")
                        elif tx:
                            parts.append(str(tx))
                    elif x:
                        parts.append(str(x))
                lines = "\n".join(parts)
            s["lines"] = (lines or "").strip() if isinstance(lines, str) else ""
            # 口型标注兜底：有对白台词默认张嘴，否则不张嘴
            mo = s.get("mouth_open")
            if not isinstance(mo, bool):
                mo = bool(s["lines"])
            s["mouth_open"] = mo
            # 场景键兜底
            sk = s.get("scene_key")
            sk = str(sk).strip() if isinstance(sk, str) and sk.strip() else f"__shot_{_si}__"
            s["scene_key"] = sk
            # 若 LLM 未提供该场景，从 content 自动生成
            if sk not in scene_map:
                scene_map[sk] = {
                    "scene_key": sk,
                    "description": (s.get("content") or "").strip() or sk,
                    "day_image_url": None,
                    "night_image_url": None
                }

        # 规范 scene_map 为 Scene 列表
        scenes = [Scene(**scene_map[k]) for k in scene_map]

        script = DramaScript(
            script_id=str(uuid.uuid4()),
            title=data["title"],
            raw_content=raw_text,
            characters=[Character(**c) for c in data["characters"]],
            scenes=scenes,
            shots=[Shot(**s) for s in data["shots"]]
        )
        # 片段分组：优先采用 LLM 输出的 segments（导演视角决定每段含几个分镜），
        # LLM 未输出或格式异常时回退到代码贪心分组兜底
        raw_segs = data.get("segments") or []
        if raw_segs and isinstance(raw_segs, list):
            seg_objs = []
            for sg in raw_segs:
                if not isinstance(sg, dict):
                    continue
                ids = sg.get("shot_ids") or []
                # 只保留真实存在的 shot_id，按剧本顺序整理
                valid_ids = [sid for sid in ids if any(s.shot_id == str(sid) for s in script.shots)]
                if not valid_ids:
                    continue
                seg_id = str(uuid.uuid4())
                seg_dur = sum((s.duration or 4) for s in script.shots if s.shot_id in valid_ids)
                seg_key = str(sg.get("scene_key") or "").strip() or next(
                    (s.scene_key for s in script.shots if s.shot_id == valid_ids[0]), "")
                seg_objs.append(Segment(segment_id=seg_id, shot_ids=valid_ids,
                                        duration=int(seg_dur), scene_key=seg_key))
                for sid in valid_ids:
                    shot = next(s for s in script.shots if s.shot_id == sid)
                    shot.segment_id = seg_id
            # 兜底：若有分镜未被任何片段覆盖，补一个片段
            covered = set(sid for sg in seg_objs for sid in sg.shot_ids)
            orphans = [s for s in script.shots if s.shot_id not in covered]
            if orphans:
                self._assign_segments(script)  # 退化重算并覆盖
            else:
                script.segments = seg_objs
            # 强制时长校验：LLM 分组可能超出 SEGMENT_MAX_DURATION，超长片段在此拆分
            seg_objs = self._enforce_segment_duration(script)
            if len(seg_objs) != len(script.segments or []):
                logger.info("segments duration-enforced | %d -> %d segments (max %ds)",
                            len(script.segments or []), len(seg_objs), self._segment_max_duration())
            logger.info("segments from LLM | %d segments | max_dur=%ds | layout=%s",
                        len(seg_objs), self._segment_max_duration(),
                        [(len(g.shot_ids), g.duration) for g in seg_objs])
        else:
            self._assign_segments(script)
        task.script = script
        task.status = TaskStatus.GENERATE_ASSET
        seg_cnt = len(script.segments) if script.segments else 0
        logger.info("step1 done | task=%s | title=%s | %d characters, %d scenes, %d shots, %d segments",
                    tid, data["title"], len(data["characters"]), len(scenes), len(data["shots"]), seg_cnt)
        await progress_hub.publish(tid, {"event": "log", "message": f"🎬 剧本《{data['title']}》解析成功：{len(data['characters'])} 个角色，{len(scenes)} 个场景，{len(data['shots'])} 个分镜，划分为 {seg_cnt} 个片段"})
        return task

    # ---------------- 片段分组 ----------------
    @staticmethod
    def _segment_max_duration() -> int:
        """单个片段视频的总时长硬性上限（秒）：SEGMENT_MAX_DURATION（默认 15）。"""
        return SEGMENT_MAX_DURATION

    @staticmethod
    def _enforce_segment_duration(script: DramaScript, seg_max: Optional[int] = None) -> list:
        """把超过时长上限的片段在分镜边界拆成多个片段（LLM 分组后强制校验用）。
        返回新片段列表，并同步每个分镜的 segment_id。"""
        seg_max = seg_max or DramaMakeSkill._segment_max_duration()
        new_segs: list = []
        for seg in list(script.segments or []):
            shots = [s for s in script.shots if s.shot_id in seg.shot_ids]
            # 按剧本顺序切段：累积时长一旦超过上限就在该分镜前切
            cur_ids: list = []
            cur_dur = 0
            for s in shots:
                d = int(s.duration or 4)
                if cur_ids and cur_dur + d > seg_max:
                    sid = str(uuid.uuid4())
                    for x in script.shots:
                        if x.shot_id in cur_ids:
                            x.segment_id = sid
                    new_segs.append(Segment(segment_id=sid, shot_ids=list(cur_ids),
                                            duration=int(cur_dur), scene_key=seg.scene_key))
                    cur_ids, cur_dur = [], 0
                cur_ids.append(s.shot_id)
                cur_dur += d
            if cur_ids:
                sid = str(uuid.uuid4())
                for x in script.shots:
                    if x.shot_id in cur_ids:
                        x.segment_id = sid
                new_segs.append(Segment(segment_id=sid, shot_ids=list(cur_ids),
                                        duration=int(cur_dur), scene_key=seg.scene_key))
        script.segments = new_segs
        return new_segs

    def _assign_segments(self, script: DramaScript) -> None:
        """把分镜按「同场景连续 + 时长预算」贪心分组为片段（参考小云雀模式）：
        - 同一 scene_key 的连续分镜合并进同一片段；
        - 片段总时长不得超过 SEGMENT_MAX_DURATION（默认 15 秒，硬性上限）；
        - 每段最多 4 个分镜（过长 prompt 会稀释模型注意力）；
        - 场景切换即切新片段（保证片段视频可用首镜场景图锚定场景）。"""
        seg_max = self._segment_max_duration()
        seg_shot_limit = max(1, int(os.getenv("SEGMENT_MAX_SHOTS", "4")))
        segments: list = []
        cur_ids: list = []
        cur_dur = 0
        cur_key = None
        for shot in script.shots:
            key = shot.scene_key or ""
            if cur_ids:
                same_scene = (key == cur_key)
                fits = (cur_dur + (shot.duration or 4) <= seg_max and len(cur_ids) < seg_shot_limit)
                if not (same_scene and fits):
                    segments.append((cur_key, cur_ids, cur_dur))
                    cur_ids, cur_dur = [], 0
            cur_ids.append(shot.shot_id)
            cur_dur += (shot.duration or 4)
            cur_key = key
        if cur_ids:
            segments.append((cur_key, cur_ids, cur_dur))
        seg_objs = []
        for i, (key, ids, dur) in enumerate(segments):
            seg_id = str(uuid.uuid4())
            for sid in ids:
                shot = next(s for s in script.shots if s.shot_id == sid)
                shot.segment_id = seg_id
            seg_objs.append(Segment(segment_id=seg_id, shot_ids=ids, duration=int(dur), scene_key=key))
        script.segments = seg_objs
        logger.info("segments assigned | %d segments | max_dur=%ds | layout=%s",
                    len(seg_objs), seg_max,
                    [(len(g.shot_ids), g.duration) for g in seg_objs])

    async def step2_gen_asset(self, task: DramaTask) -> DramaTask:
        """步骤2：角色立绘 + 场景图（每个场景白天/黑夜双图）在同一阶段并行生成（加速流程），
        全部处理完（单张失败不中断，可单独重试）后统一进入人工审核断点。
        - 图片并发受 IMAGE_MAX_CONCURRENCY 控制（默认 3），超出自动排队；
        - 角色事件走 event=char，场景图事件走 event=scene_img（含 variant=day/night），前端实时渲染。"""
        tid = task.task_id
        task.status = TaskStatus.GENERATE_ASSET
        await progress_hub.publish(tid, {"event": "status", "status": "generating_asset",
                                         "message": "🎨 正在并行生成角色形象与场景图（昼夜双图）…"})
        chars = task.script.characters
        scenes = task.script.scenes
        total_img_jobs = len(chars) + len(scenes) * 2
        await progress_hub.publish(tid, {"event": "log",
                                         "message": f"🎨 开始并行绘制 {len(chars)} 个角色立绘 + {len(scenes)} 个场景（每场景昼夜 2 张图，共 {len(scenes) * 2} 张场景图，合计 {total_img_jobs} 张图，并发 {IMAGE_MAX_CONCURRENCY}）…"})
        sem = asyncio.Semaphore(IMAGE_MAX_CONCURRENCY)

        async def _char_job(i: int, char):
            async with sem:
                await progress_hub.publish(tid, {"event": "log", "message": f"🎨 正在绘制角色形象：{char.name}…"})
                try:
                    url = await asyncio.to_thread(generate_character_image, self._build_character_image_prompt(char, task.style))
                    char.reference_image = url
                    await progress_hub.publish(tid, {
                        "event": "char", "index": i, "total": len(chars),
                        "char_id": char.char_id, "name": char.name, "description": char.description,
                        "image_url": url, "status": "ok"
                    })
                except Exception as e:
                    logger.warning("step2 char failed | task=%s | char=%s | err=%s", tid, char.name, str(e)[:100])
                    await progress_hub.publish(tid, {
                        "event": "char", "index": i, "total": len(chars),
                        "char_id": char.char_id, "name": char.name, "description": char.description,
                        "image_url": None, "status": "failed", "error": str(e)[:120]
                    })
                    await progress_hub.publish(tid, {"event": "log", "message": f"⚠️ 角色「{char.name}」形象生成失败：{str(e)[:80]}（可在审核前点击重试）"})

        async def _scene_job(i: int, scene: Scene, variant: str):
            async with sem:
                already = scene.day_image_url if variant == "day" else scene.night_image_url
                if already:
                    await progress_hub.publish(tid, {
                        "event": "scene_img", "index": i, "total": len(scenes),
                        "scene_key": scene.scene_key, "variant": variant,
                        "image_url": already, "status": "ok"
                    })
                    return
                label = "白天" if variant == "day" else "黑夜"
                await progress_hub.publish(tid, {"event": "log",
                                                 "message": f"🖼️ 正在绘制场景「{scene.scene_key}」{label}图 {i + 1}/{len(scenes)}…"})
                try:
                    img_prompt = self._build_scene_image_prompt(task, scene, variant)
                    img_url = await asyncio.to_thread(generate_character_image, img_prompt)
                    if variant == "day":
                        scene.day_image_url = img_url
                    else:
                        scene.night_image_url = img_url
                    await progress_hub.publish(tid, {
                        "event": "scene_img", "index": i, "total": len(scenes),
                        "scene_key": scene.scene_key, "variant": variant,
                        "image_url": img_url, "status": "ok"
                    })
                except Exception as e:
                    logger.warning("step2 scene_img failed | task=%s | scene=%s | variant=%s | err=%s",
                                   tid, scene.scene_key, variant, str(e)[:100])
                    await progress_hub.publish(tid, {
                        "event": "scene_img", "index": i, "total": len(scenes),
                        "scene_key": scene.scene_key, "variant": variant,
                        "image_url": None, "status": "failed", "error": str(e)[:120]
                    })
                    await progress_hub.publish(tid, {"event": "log", "message": f"⚠️ 场景「{scene.scene_key}」{label}图生成失败：{str(e)[:80]}（可在审核前点击重试）"})

        jobs = [_char_job(i, c) for i, c in enumerate(chars)]
        jobs += [_scene_job(i, sc, variant) for i, sc in enumerate(scenes) for variant in ("day", "night")]
        await asyncio.gather(*jobs)
        task.status = TaskStatus.HUMAN_REVIEW
        await progress_hub.publish(tid, {"event": "log", "message": "🎉 角色立绘与场景图（昼夜双图）全部处理完毕，进入人工审核"})
        await progress_hub.publish(tid, {"event": "status", "status": "human_review",
                                         "message": "⏸️ 角色与场景图生成完毕，等待人工审核"})
        return task

    def _build_scene_image_prompt(self, task: DramaTask, scene: Scene, variant: str) -> str:
        """场景图只生成纯场景/纯环境，不出现任何人物；variant=day/night 控制昼夜光线。
        画风必须与角色立绘完全一致（同一 style 前缀 + 同一锁定指令），
        关键词同时给中英文负面指令，火山Seedream不一定强遵守纯中文负面。
        黑夜生成时如果已有白天图，必须在 prompt 中显式要求「保持与白天完全相同的构图」，
        强制黑夜图 = 白天图改为夜晚光照版本。"""
        style_desc = self._style_prompt(task.style)
        desc = (scene.description or "").strip()
        # 安全兜底：移除可能残留的角色名和@标注
        for char in task.script.characters:
            desc = desc.replace(char.name, "")
        desc = re.sub(r"@\S+", "", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
        desc = re.sub(r"[，。,\.]$", "", desc)
        # 昼夜光线注入
        if variant == "night":
            time_line = "夜晚场景，月光或夜色笼罩，暗调环境，星光/灯光点缀，整体偏冷/偏暗"
            time_en = "night scene, moonlight or darkness, dim environment, starlight or lamp light, cool/dark tone"
        else:
            time_line = "白天场景，自然日光照射，明亮清晰，正常白昼氛围"
            time_en = "daytime scene, natural sunlight, bright and clear, normal daylight atmosphere"
        # realistic 风格的"动画/影视"措辞改为"真实取景/电影剧照"（用 task.style，不是未定义变量 style）
        if task.style == "realistic":
            consistency = (
                "本画面与角色立绘属于同一部真实拍摄短剧/电影中的场景，"
                "与角色立绘完全相同的写实摄影风格与色调，统一光线、镜头质感、色彩分级"
            )
            style_en = "same photorealistic style as the character design sheets, consistent color grading, same camera and lens, unified art direction"
        else:
            consistency = (
                "本画面与角色立绘属于同一部作品的场景背景，"
                "与角色立绘完全相同的艺术风格与画风，统一色调，统一线条粗细，"
                "统一光影处理，统一渲染管线，同一色彩板，如同同一部动画/影视中的场景"
            )
            style_en = "same art style as the character design sheets, consistent color palette, same rendering pipeline, unified art direction"
        # 中英文双向负面prompt
        neg_en = "no people, no humans, no persons, no characters, no figures, no silhouettes, no crowds, empty scene, object only, environmental shot, location shot, background only, no portrait, no face"
        neg_zh = "无人出现、无人物、无肖像、无面部特写、只有环境与场景、空镜、纯背景、禁止人物"
        # 黑夜图必须保持白天图完全相同的构图/建筑/物件，只改光照
        if variant == "night" and getattr(scene, "day_image_url", None):
            consistency += "。构图与白天版本完全一致（相同的建筑/物件/景别/机位/角度），仅将日光替换为月光/夜色、整体改为冷暗色调"
            style_en += ", exactly same composition as the day version (identical building, objects, framing, camera angle), only daylight replaced by moonlight, cool dark tone"
        return (
            f"{style_desc}。{consistency}。{desc}。{time_line}。"
            f"{style_en}. {time_en}. "
            f"Negative prompt: {neg_en}. Negative: {neg_zh}."
        )

    def _style_prompt(self, style: str) -> str:
        """根据用户选择的画风返回统一风格前缀。
        关键词设计要点：避免"动画/插画"等触发卡通的词；realistic 显式加入摄影器材/真人关键词
        提升火山即梦 jimeng_*/Seedream 等通用图模型对"真人写实"风格的响应。"""
        styles = {
            "anime": "日式动漫风格，2D 赛璐珞画风，精致线条，柔和光影，统一角色设计",
            "realistic": "真人实拍照片风格，佳能 EOS R5 全画幅相机，85mm 人像镜头，自然肤色，"
                          "真实皮肤毛孔纹理，电影级光影，如同真实演员定妆照，写实摄影作品，非插画非卡通",
            "3d": "3D 卡通渲染风格，皮克斯式角色设计，细腻毛发与服装材质，统一角色模型",
            "q版": "Q版萌系风格，二头身比例，圆润可爱，大眼睛，统一萌系角色设计",
            "国风": "中国古典水墨/国漫风格，飘逸衣袂，淡雅配色，东方美学，统一古风角色设计",
            "cyberpunk": "赛博朋克风格，霓虹光效，机械义肢元素，未来城市背景，统一科幻角色设计",
        }
        return styles.get(style, styles["anime"])

    def _build_character_image_prompt(self, char, style: str = "anime") -> str:
        """构建角色图片生成prompt，强制锁定统一艺术风格，确保多个角色画风一致。
        同时加注「同一系列」概念，让火山Seedream把这些角色当作一组成品。
        realistic 风格时去掉"动画/插画"等关键词，避免触发卡通化。"""
        desc = (char.description or "").strip()
        style_desc = self._style_prompt(style)
        # realistic 风格时使用"演员定妆照"一致性，其他风格用"动画系列"措辞
        if style == "realistic":
            consistency = (
                "同一短剧/电影的演员定妆照系列，统一画风，统一色调，"
                "统一光线与镜头质感，如同同一部真实拍摄短剧中的角色"
            )
            neg_en = "no other characters, no extra people, single person, solo, neutral background, no anime, no cartoon, no illustration, no 2D, photorealistic only"
        else:
            consistency = (
                "同一动画系列角色设计，统一画风，统一色调，统一线条粗细，"
                "统一光影处理，统一背景风格，统一渲染管线，如同来自同一部作品"
            )
            neg_en = "no other characters, no extra people, single person, solo, white background, clean background"
        return (
            f"{style_desc}。{consistency}。全身像角色立绘，{desc}。"
            f"Negative prompt: {neg_en}。精细画质，4K，电影质感，character design sheet"
        )

    async def step3_after_human_review(self, task: DramaTask) -> DramaTask:
        """人工确认之后：不自动生成任何视频。
        角色/分镜图已在 step2 生成完毕，本步只切换到「生成片段视频」阶段，
        由用户在前端逐片段点击「生成所在片段视频」手动触发；
        已生成 2 个及以上片段即可点击「合成视频」（支持只合成已生成的部分片段）。"""
        tid = task.task_id
        task.status = TaskStatus.GENERATE_VIDEO
        seg_cnt = len(task.script.segments or [])
        await progress_hub.publish(tid, {"event": "status", "status": "generating_video",
                                         "message": "🎥 审核通过！请在分镜卡片中逐片段生成视频"})
        await progress_hub.publish(tid, {"event": "log",
                                         "message": f"🎥 审核通过！剧本共 {seg_cnt} 个片段：请在各分镜卡片点击「生成所在片段视频」逐段生成；已生成 2 段以上即可点击「合成视频」拼接（也可全部生成后合成完整短剧）"})
        await progress_hub.publish(tid, {"event": "done"})
        return task

    # ---------------- 失败重试 ----------------
    async def regenerate_character_image(self, task: DramaTask, char_id: str) -> DramaTask:
        """重新生成单个角色形象图"""
        tid = task.task_id
        char = next((c for c in task.script.characters if c.char_id == char_id), None)
        if not char:
            raise ValueError(f"角色 {char_id} 不存在")
        idx = task.script.characters.index(char)
        await progress_hub.publish(tid, {"event": "log", "message": f"🔄 正在重新生成角色「{char.name}」形象…"})
        try:
            url = await asyncio.to_thread(generate_character_image, self._build_character_image_prompt(char, task.style))
            char.reference_image = url
            await progress_hub.publish(tid, {
                "event": "char", "index": idx, "total": len(task.script.characters),
                "char_id": char.char_id, "name": char.name, "description": char.description,
                "image_url": url, "status": "ok"
            })
            await progress_hub.publish(tid, {"event": "log", "message": f"✅ 角色「{char.name}」形象重新生成成功"})
        except Exception as e:
            await progress_hub.publish(tid, {
                "event": "char", "index": idx, "total": len(task.script.characters),
                "char_id": char.char_id, "name": char.name, "description": char.description,
                "image_url": None, "status": "failed", "error": str(e)[:120]
            })
            await progress_hub.publish(tid, {"event": "log", "message": f"⚠️ 角色「{char.name}」重新生成失败：{str(e)[:80]}"})
        return task

    async def regenerate_scene_image(self, task: DramaTask, target_id: str) -> DramaTask:
        """重新生成单张场景图。target_id 格式：scene_key:day 或 scene_key:night"""
        tid = task.task_id
        if ":" not in target_id:
            target_id = target_id + ":day"
        scene_key, variant = target_id.rsplit(":", 1)
        if variant not in ("day", "night"):
            variant = "day"
        scene = next((sc for sc in task.script.scenes if sc.scene_key == scene_key), None)
        if not scene:
            raise ValueError(f"场景 {scene_key} 不存在")
        idx = task.script.scenes.index(scene)
        label = "白天" if variant == "day" else "黑夜"
        await progress_hub.publish(tid, {"event": "log", "message": f"🔄 正在重新绘制场景「{scene_key}」{label}图…"})
        try:
            img_prompt = self._build_scene_image_prompt(task, scene, variant)
            img_url = await asyncio.to_thread(generate_character_image, img_prompt)
            if variant == "day":
                scene.day_image_url = img_url
            else:
                scene.night_image_url = img_url
            await progress_hub.publish(tid, {
                "event": "scene_img", "index": idx, "total": len(task.script.scenes),
                "scene_key": scene.scene_key, "variant": variant,
                "image_url": img_url, "status": "ok"
            })
            await progress_hub.publish(tid, {"event": "log", "message": f"✅ 场景「{scene_key}」{label}图重新生成成功"})
        except Exception as e:
            await progress_hub.publish(tid, {
                "event": "scene_img", "index": idx, "total": len(task.script.scenes),
                "scene_key": scene.scene_key, "variant": variant,
                "image_url": None, "status": "failed", "error": str(e)[:120]
            })
            await progress_hub.publish(tid, {"event": "log", "message": f"⚠️ 场景「{scene_key}」{label}图重新生成失败：{str(e)[:80]}"})
        return task

    def _char_lock_tags(self, char: Character) -> str:
        """从角色 description 中提取最影响视频一致性的短标签：服装、发色、标志性外貌。"""
        desc = char.description or ""
        tags = []
        # 服装关键词（校服/古装/西装/连衣裙等）
        m = re.search(r"(?:穿着|身穿|身着|服装|衣服|校服|西装|衬衫|连衣裙|旗袍|汉服)([^，。；.]+)", desc)
        if m:
            tags.append("服装：" + m.group(1).strip())
        # 发型发色
        m = re.search(r"((?:黑色|棕色|金色|银白色|红色|紫色|蓝色|绿色)?(?:长发|短发|马尾|卷发|直发|双马尾|丸子头)[^，。；.]*)", desc)
        if m:
            tags.append("发型发色：" + m.group(1).strip())
        # 瞳色
        m = re.search(r"((?:黑色|棕色|蓝色|绿色|紫色|琥珀色|灰色)眼(?:睛|眸))", desc)
        if m:
            tags.append("瞳色：" + m.group(1).strip())
        if not tags:
            # 兜底：取 description 前 60 字
            tags.append("外貌：" + desc[:60])
        return "；".join(tags)

    @staticmethod
    def _char_asset_tag(char: Character) -> str:
        """小云雀风格角色资产占位标签。"""
        return f"<node-asset>char_{char.char_id}</node-asset>"

    @staticmethod
    def _scene_asset_tag(scene_key: str, variant: str = "day") -> str:
        """小云雀风格场景资产占位标签。"""
        return f"<node-asset>scene_{scene_key}_{variant}</node-asset>"

    def _build_shot_video_prompt(self, task: DramaTask, shot: Shot) -> str:
        """构建视频生成 prompt（中文），保留@角色名标注，并附加角色外貌/服装锁定确保一致性。
        关键策略：
        1. 最前置「角色必须长成下面角色立绘的样子」强制指令；
        2. 每个出现角色给「外貌锁定短语」；
        3. 角色服装/发色/瞳色关键词优先，因为视频模型对短标签最敏感；
        4. 追加负面词禁止生成新角色。"""
        style_desc = self._style_prompt(task.style)
        base = (shot.prompt or "").strip()
        if not base:
            base = shot.content or ""
        # 确定本镜出现的角色
        names = set(shot.character_names or [])
        for char in task.script.characters:
            if f"@{char.name}" in base:
                names.add(char.name)
        # 过滤出真实存在的角色
        chars_in_shot = [c for c in task.script.characters if c.name in names]

        parts = [base]
        # 画风指令：与角色立绘、分镜图保持同一画风
        parts.append(f"\n画风：{style_desc}，与角色立绘和分镜图完全统一的画风与色调。")

        if chars_in_shot:
            lock_lines = []
            for char in chars_in_shot:
                lock_lines.append(
                    f"- @{char.name} 必须严格保持角色立绘中的形象：{self._char_lock_tags(char)}；"
                    f"不得改变发型、发色、服装款式、五官比例，禁止出现其他外貌。"
                )
            parts.append(
                "\n角色外貌锁定（本镜中每个角色都必须与角色立绘完全一致，不可 invent 新形象）：\n"
                + "\n".join(lock_lines)
            )
            parts.append(
                "\n角色设定（详细外貌）：\n"
                + "\n".join(f"@{c.name}：{c.description.strip()}" for c in chars_in_shot)
            )

        # 负面约束：禁止换人、禁止多个人物、禁止改变服装
        neg = (
            "Negative prompt: 禁止出现新角色，禁止改变角色服装，禁止改变角色发型发色，"
            "禁止同一角色外貌不一致，禁止额外人物，禁止面目全非，保持角色身份一致"
        )
        parts.append("\n" + neg)
        return "\n".join(parts)

    # ---------------- 片段视频（小云雀多分镜模式） ----------------
    @staticmethod
    def _parse_lines(shot: Shot) -> list:
        """把 lines 规范化为 [(speaker, text), ...]，speaker 可能为空（旁白）。"""
        out = []
        for raw in (shot.lines or "").split("\n"):
            line = raw.strip()
            if not line:
                continue
            m = re.match(r"^([^：:]{1,12})[：:](.+)$", line)
            if m:
                out.append((m.group(1).strip(), m.group(2).strip()))
            else:
                out.append(("", line))
        return out

    def _format_shot_speech(self, shot: Shot, chars_in_seg: list) -> str:
        """把本镜台词按小云雀风格嵌入片段 prompt：
        - mouth_open=True（说出口的对白）→ 角色张嘴说出台词，口型同步；
        - mouth_open=False（内心独白/旁白）→ 独白响起，角色没有张嘴。"""
        parsed = self._parse_lines(shot)
        if not parsed:
            return ""
        speech_parts = []
        for speaker, text in parsed:
            if speaker and speaker in chars_in_seg:
                if shot.mouth_open:
                    speech_parts.append(f"{speaker}张嘴说：“{text}”（口型与台词同步）")
                else:
                    speech_parts.append(f"{speaker}的内心独白响起：“{text}”（{speaker}没有张嘴）")
            elif speaker:
                if shot.mouth_open:
                    speech_parts.append(f"{speaker}张嘴说：“{text}”（口型与台词同步）")
                else:
                    speech_parts.append(f"内心独白响起：“{text}”（角色没有张嘴）")
            else:
                if shot.mouth_open:
                    speech_parts.append(f"角色张嘴说：“{text}”（口型与台词同步）")
                else:
                    speech_parts.append(f"内心独白响起：“{text}”（角色没有张嘴）")
        return "；".join(speech_parts)

    def _build_segment_video_prompt(self, task: DramaTask, seg, channel: str = None) -> str:
        """构建片段视频 prompt：
        - volc_ark（方舟 Seedance）：保留 <node-asset> 标签（Seedance 原生支持）+ role=reference_image
        - volc_cv（火山即梦 jimeng_t2v_v30）：**剥离 <node-asset> 标签**（即梦不识别 XML 标签），
          替换为「该角色」+ 强化"参考图就是本片段场景"一致性指令
        角色外貌锁定 + 画风统一。"""
        script = task.script
        shots = [next(s for s in script.shots if s.shot_id == sid) for sid in seg.shot_ids]
        style_desc = self._style_prompt(task.style)
        scene_key = seg.scene_key or (shots[0].scene_key if shots else "")
        # 通道探测
        from tools.media_channel import VIDEO_CHANNEL
        ch = (channel or VIDEO_CHANNEL or "volc_cv").lower()
        use_node_asset = (ch == "volc_ark")  # 只有方舟支持节点资产标签

        # 场景锚定
        if use_node_asset:
            header = f"本片段场景设定在: {self._scene_asset_tag(scene_key, 'day')}。生成一个由以下{len(shots)}个分镜组成的视频。"
        else:
            # cv 通道：不用节点标签，用「场景图参考」措辞（参考图 URL 已传入 model）
            scene_name = scene_key or "本片段"
            header = f"本片段的场景就是下方传入的参考图（{scene_name}），必须严格按参考图的构图、光线、建筑、物件来生成整个视频。生成一个由以下{len(shots)}个分镜组成的视频。"

        def _replace_char_at(prompt_text: str) -> str:
            """把 @角色名 替换为节点标签（ark）或角色中文名（cv）"""
            out = prompt_text
            for c in script.characters:
                if use_node_asset:
                    out = out.replace(f"@{c.name}", self._char_asset_tag(c))
                else:
                    # cv 通道：把 @林夏 改为「林夏」+ 显式一致性指令
                    out = out.replace(f"@{c.name}", f"「{c.name}」")
            return out

        # 分镜逐条描述
        seg_lines = []
        for i, shot in enumerate(shots):
            ms = int((shot.duration or 4) * 1000)
            desc = (shot.prompt or "").strip()
            if not desc:
                bits = [b for b in [(shot.camera or "").strip(), (shot.content or "").strip()] if b]
                desc = "，".join(bits) if bits else "（无描述）"
            desc = _replace_char_at(desc)
            if use_node_asset:
                seg_lines.append(f"分镜{i + 1}<duration-ms>{ms}</duration-ms>: {desc}")
            else:
                # cv 通道：去掉 <duration-ms> 标签（即梦不识别），用「分镜N（约Xs）」自然语言
                seg_lines.append(f"分镜{i + 1}（约 {ms // 1000} 秒）: {desc}")

        # 片段内出现的所有角色
        names = set()
        for shot in shots:
            names.update(shot.character_names or [])
            for c in script.characters:
                if f"@{c.name}" in (shot.prompt or ""):
                    names.add(c.name)
        chars_in_seg = [c for c in script.characters if c.name in names]

        parts = [header, "\n".join(seg_lines)]
        parts.append(f"\n画风：{style_desc}，与下方参考图完全统一的画风与色调。")
        if chars_in_seg:
            if use_node_asset:
                lock_lines = [
                    f"- {self._char_asset_tag(char)} 必须全程严格保持角色立绘中的形象：{self._char_lock_tags(char)}；"
                    f"不得改变发型、发色、服装款式、五官比例，禁止出现其他外貌。"
                    for char in chars_in_seg
                ]
                parts.append("\n角色外貌锁定（片段中每个角色都必须与角色立绘完全一致，不可发明新形象）：\n" + "\n".join(lock_lines))
                parts.append("\n角色设定（详细外貌）：\n" +
                             "\n".join(f"{self._char_asset_tag(c)}：{c.description.strip()}" for c in chars_in_seg))
            else:
                # cv 通道：自然语言描述，无标签
                lock_lines = [
                    f"- 角色「{char.name}」必须全程严格保持下方参考图中的形象：{self._char_lock_tags(char)}；"
                    f"不得改变发型、发色、服装款式、五官比例，禁止出现其他外貌。"
                    for char in chars_in_seg
                ]
                parts.append("\n角色外貌锁定（片段中每个角色都必须与角色立绘完全一致，不可发明新形象）：\n" + "\n".join(lock_lines))
                parts.append("\n角色设定（详细外貌）：\n" +
                             "\n".join(f"角色「{c.name}」：{c.description.strip()}" for c in chars_in_seg))
        # 场景一致性强化（cv 通道）：参考图就是场景
        if not use_node_asset:
            parts.append(
                "\n场景一致性（必须严格遵守）：整个视频的构图、景别、光线、建筑物、物件、地面、天空"
                "都必须与下方传入的参考图完全一致；不得发明新场景、新建筑、新陈设；"
                "角色在场景内的站位、动作必须合理且连续。"
            )
        parts.append(
            "\nNegative prompt: 禁止出现新角色，禁止改变角色服装，禁止改变角色发型发色，"
            "同一角色外貌全程一致，禁止额外人物，禁止面目全非，保持角色身份一致，"
            "每个分镜之间保持连续的动作与场景逻辑。"
        )
        return "\n".join(parts)
    async def _generate_segment_video(self, task: DramaTask, seg) -> bool:
        """生成单个片段视频（一段含多个分镜的多分镜连续表演视频，参考小云雀模式）：
        1. 用小云雀风格多分镜 prompt 提交（首镜场景图作参考锚定场景）；
        2. 下载落盘（火山链接 24h 失效）；
        3. 配音：原生音频通道直接保留；否则逐镜 TTS 并按各分镜起始毫秒对齐混入；
        4. 段内所有 shot 的 video_url 指向同一段视频（前端逐镜卡片共享展示）。
        返回是否成功。"""
        tid = task.task_id
        script = task.script
        shots = [next(s for s in script.shots if s.shot_id == sid) for sid in seg.shot_ids]
        seg_idx = script.segments.index(seg) + 1
        seg_total = len(script.segments)
        seg_dur = seg.duration or sum(s.duration or 4 for s in shots)
        await progress_hub.publish(tid, {"event": "log",
                                          "message": f"🎞️ 正在生成片段 {seg_idx}/{seg_total}（{len(shots)} 个分镜 · {seg_dur} 秒）…"})
        if not _VIDEO_SLOT.acquire(blocking=False):
            await progress_hub.publish(tid, {"event": "log",
                                              "message": f"⏳ 片段 {seg_idx} 排队中：已有 {VIDEO_MAX_CONCURRENCY} 个视频在生成，等待空闲配额…"})
        await asyncio.to_thread(_VIDEO_SLOT.acquire)
        try:
            try:
                prompt = self._build_segment_video_prompt(task, seg)
                # 参考图：片段对应场景的白天场景图锚定场景；缺失时回退段内主要角色立绘
                ref_url = ""
                scene = next((sc for sc in script.scenes if sc.scene_key == seg.scene_key), None)
                if scene:
                    ref_url = scene.day_image_url or scene.night_image_url
                if not ref_url:
                    for s in shots:
                        for c in script.characters:
                            if c.name in (s.character_names or []) and c.reference_image:
                                ref_url = c.reference_image
                                break
                        if ref_url:
                            break
                video_task_id = await asyncio.to_thread(submit_video_task, prompt, ref_url, seg_dur)
                result = await asyncio.to_thread(query_video_result, video_task_id)
                if not result.get("ok"):
                    err = (result.get("msg") or "未知错误")[:120]
                    logger.warning("segment video failed | task=%s | seg=%d | err=%s", tid, seg_idx, err)
                    for s in shots:
                        await progress_hub.publish(tid, {"event": "shot", "index": script.shots.index(s),
                                                         "total": len(script.shots), "shot_id": s.shot_id,
                                                         "video_url": None, "status": "failed", "error": err})
                    await progress_hub.publish(tid, {"event": "segment", "index": seg_idx, "total": seg_total,
                                                     "segment_id": seg.segment_id, "status": "failed", "error": err})
                    await progress_hub.publish(tid, {"event": "log",
                                                      "message": f"⚠️ 片段 {seg_idx}/{seg_total} 视频生成失败：{err[:60]}（可点击重试）"})
                    return False
                # 下载落盘（临时签名链接 24h 失效，必须立即保存）
                await progress_hub.publish(tid, {"event": "log", "message": f"⏬ 片段 {seg_idx} 视频生成完成，正在落盘到本地…"})
                local_path = os.path.join("assets", "videos", f"{tid}_{seg.segment_id}.mp4")
                await asyncio.to_thread(download_video, result["video_url"], local_path)
                # 配音：auto 按通道（ark 原生 / cv 走 TTS）；native 强制原生；tts 强制 TTS
                audio_mode = getattr(task, "audio_mode", "auto") or "auto"
                is_native = video_has_native_audio()
                use_native = (audio_mode == "native") or (audio_mode == "auto" and is_native)
                if use_native:
                    await progress_hub.publish(tid, {"event": "log",
                                                      "message": f"🔊 配音方式：原生音频（{'强制保留' if audio_mode=='native' else '当前通道原生带声音'}），跳过 TTS"})
                else:
                    audio_items = []
                    start_ms = 0
                    for s in shots:
                        if ENABLE_TTS and (s.lines or "").strip():
                            mp3 = os.path.join("assets", "audio", f"{tid}_{s.shot_id}.mp3")
                            try:
                                audio_path = await asyncio.to_thread(synthesize_speech, s.lines, mp3)
                                if audio_path:
                                    audio_items.append((audio_path, start_ms))
                            except Exception as te:
                                logger.warning("segment tts failed | task=%s | shot=%s | err=%s",
                                               tid, s.shot_id, str(te)[:100])
                        start_ms += int((s.duration or 4) * 1000)
                    if audio_items:
                        await progress_hub.publish(tid, {"event": "log",
                                                          "message": f"🎙️ 正在为片段 {seg_idx} 按 {len(audio_items)} 条台词时间轴对齐混音…"})
                        await asyncio.to_thread(mix_segment_audio, local_path, audio_items, seg_dur)
                    else:
                        await asyncio.to_thread(finalize_shot_video, local_path, seg_dur, None)
                local_url = f"/assets/videos/{tid}_{seg.segment_id}.mp4"
                seg.video_url = local_url
                for s in shots:
                    s.video_url = local_url
                    await progress_hub.publish(tid, {"event": "shot", "index": script.shots.index(s),
                                                     "total": len(script.shots), "shot_id": s.shot_id,
                                                     "video_url": local_url, "status": "ok"})
                await progress_hub.publish(tid, {"event": "segment", "index": seg_idx, "total": seg_total,
                                                 "segment_id": seg.segment_id, "status": "ok",
                                                 "video_url": local_url, "duration": seg_dur,
                                                 "shot_count": len(shots)})
                await progress_hub.publish(tid, {"event": "log",
                                                  "message": f"✅ 片段 {seg_idx}/{seg_total} 视频生成成功（{len(shots)} 个分镜 · {seg_dur} 秒，已保存到本地）"})
                return True
            except Exception as e:
                logger.error("segment video error | task=%s | seg=%d | err=%s", tid, seg_idx, str(e)[:150])
                err = str(e)[:120]
                for s in shots:
                    await progress_hub.publish(tid, {"event": "shot", "index": script.shots.index(s),
                                                     "total": len(script.shots), "shot_id": s.shot_id,
                                                     "video_url": None, "status": "failed", "error": err})
                await progress_hub.publish(tid, {"event": "segment", "index": seg_idx, "total": seg_total,
                                                 "segment_id": seg.segment_id, "status": "failed", "error": err})
                await progress_hub.publish(tid, {"event": "log",
                                                  "message": f"⚠️ 片段 {seg_idx}/{seg_total} 视频生成失败：{err[:60]}（可点击重试）"})
                return False
        finally:
            _VIDEO_SLOT.release()

    async def regenerate_segment_video(self, task: DramaTask, segment_id: str) -> DramaTask:
        """生成/重新生成单个片段视频（用户在前端手动触发）。
        合成完全由用户手动点击「合成视频」触发，不再自动合成。"""
        seg = next((g for g in (task.script.segments or []) if g.segment_id == segment_id), None)
        if not seg:
            raise ValueError(f"片段 {segment_id} 不存在")
        await self._generate_segment_video(task, seg)
        return task

    async def regenerate_shot_video(self, task: DramaTask, shot_id: str) -> DramaTask:
        """重新生成视频：新任务（有片段分组）自动转发为生成该分镜所属片段；
        旧任务（无分组）保持单镜模式。
        火山即梦返回的video_url是临时签名链接，几小时后失效导致前端403，
        因此生成成功后立即下载到本地assets/videos/下保存为本地URL。
        进程级并发控制：同一时刻最多 VIDEO_MAX_CONCURRENCY 个视频在生成，超出自动排队。"""
        tid = task.task_id
        shot = next((s for s in task.script.shots if s.shot_id == shot_id), None)
        if not shot:
            raise ValueError(f"分镜 {shot_id} 不存在")
        # ---- 新模式：该分镜属于某个片段 → 重新生成整个片段视频 ----
        if shot.segment_id and task.script.segments:
            seg = next((g for g in task.script.segments if g.segment_id == shot.segment_id), None)
            if seg:
                await progress_hub.publish(tid, {"event": "log",
                                                  "message": f"🔄 分镜属于片段（含 {len(seg.shot_ids)} 个分镜），正在重新生成该片段视频…"})
                return await self.regenerate_segment_video(task, seg.segment_id)
        # ---- 旧模式兜底：单镜视频 ----
        idx = task.script.shots.index(shot)
        await progress_hub.publish(tid, {"event": "log", "message": f"🔄 正在生成分镜 {idx + 1} 视频…"})
        # 排队等待视频生成配额（非阻塞探测 + 阻塞等待，双段提示）
        if not _VIDEO_SLOT.acquire(blocking=False):
            await progress_hub.publish(tid, {"event": "log", "message": f"⏳ 分镜 {idx + 1} 排队中：已有 {VIDEO_MAX_CONCURRENCY} 个视频在生成，等待空闲配额…"})
        await asyncio.to_thread(_VIDEO_SLOT.acquire)
        try:
            try:
                # 选择参考图：旧任务（无场景资产）优先本镜第一个出现角色的立绘
                ref_url = ""
                names = set(shot.character_names or [])
                for char in task.script.characters:
                    if f"@{char.name}" in (shot.prompt or ""):
                        names.add(char.name)
                main_char = next((c for c in task.script.characters if c.name in names and c.reference_image), None)
                if main_char:
                    ref_url = main_char.reference_image
                    logger.info("shot video use character reference | task=%s shot=%d char=%s", tid, idx + 1, main_char.name)

                video_task_id = await asyncio.to_thread(
                    submit_video_task,
                    self._build_shot_video_prompt(task, shot),
                    ref_url,
                    shot.duration
                )
                result = await asyncio.to_thread(query_video_result, video_task_id)
                if result.get("ok"):
                    logger.info("shot video ok | task=%s | shot=%d | downloading…", tid, idx + 1)
                    remote_url = result["video_url"]
                    await progress_hub.publish(tid, {"event": "log", "message": f"⏬ 视频生成完成，正在落盘到本地避免临时链接失效…"})
                    local_path = os.path.join("assets", "videos", f"{tid}_{shot_id}.mp4")
                    await asyncio.to_thread(download_video, remote_url, local_path)
                    # 配音：若当前视频通道原生带音频（方舟 Seedance + ARK_VIDEO_AUDIO=true），
                    # 跳过 edge-tts 配音，避免覆盖模型原生声音；否则合成台词语音混入视频
                    audio_path = ""
                    native_audio = video_has_native_audio()
                    if native_audio:
                        await progress_hub.publish(tid, {"event": "log", "message": f"🔊 当前模型原生带声音（Seedance 音频），跳过 TTS 配音"})
                    elif ENABLE_TTS and (shot.lines or "").strip():
                        await progress_hub.publish(tid, {"event": "log", "message": f"🎙️ 正在为分镜 {idx + 1} 合成台词配音…"})
                        audio_path = await asyncio.to_thread(
                            synthesize_speech, shot.lines,
                            os.path.join("assets", "audio", f"{tid}_{shot_id}.mp3")
                        )
                        if audio_path:
                            await progress_hub.publish(tid, {"event": "log", "message": f"🔊 分镜 {idx + 1} 配音合成完成，正在混入视频…"})
                    # 后处理：裁剪到大模型分配的精确时长 + 混入音轨（配音或静音占位；原生音频则原样保留）
                    await asyncio.to_thread(finalize_shot_video, local_path, shot.duration or 4, audio_path or None)
                    local_url = f"/assets/videos/{tid}_{shot_id}.mp4"
                    shot.video_url = local_url
                    await progress_hub.publish(tid, {"event": "shot", "index": idx, "total": len(task.script.shots), "shot_id": shot.shot_id, "video_url": local_url, "status": "ok"})
                    if audio_path:
                        await progress_hub.publish(tid, {"event": "log", "message": f"✅ 分镜 {idx + 1} 视频生成成功（{shot.duration} 秒，含配音，已保存到本地）"})
                    else:
                        await progress_hub.publish(tid, {"event": "log", "message": f"✅ 分镜 {idx + 1} 视频生成成功（{shot.duration} 秒，已保存到本地）"})
                else:
                    await progress_hub.publish(tid, {"event": "shot", "index": idx, "total": len(task.script.shots), "shot_id": shot.shot_id, "video_url": None, "status": "failed", "error": result.get("msg", "未知错误")[:120]})
                    await progress_hub.publish(tid, {"event": "log", "message": f"⚠️ 分镜 {idx + 1} 视频生成失败：{result.get('msg', '未知错误')[:60]}"})
            except Exception as e:
                logger.error("shot video failed | task=%s | shot=%d | err=%s", tid, idx + 1, str(e)[:150])
                await progress_hub.publish(tid, {"event": "shot", "index": idx, "total": len(task.script.shots), "shot_id": shot.shot_id, "video_url": None, "status": "failed", "error": str(e)[:120]})
                await progress_hub.publish(tid, {"event": "log", "message": f"⚠️ 分镜 {idx + 1} 视频生成失败：{str(e)[:60]}"})
        finally:
            _VIDEO_SLOT.release()
        return task

    # ---------------- 合成完整视频 ----------------
    async def compose_final_video(self, task: DramaTask) -> DramaTask:
        """把已生成的片段视频按顺序合成完整短剧视频（ffmpeg，用户手动触发）。
        **支持部分合成**：不要求所有片段都已生成——
        - 已生成片段 ≥ 2 个即可合成（用户不想继续生成后面片段时，直接用现有片段拼接）；
        - 全部生成完毕时合成完整全集；
        - 仅生成 1 个片段（且总片段数 > 1）或 0 个时拒绝合成并提示。
        片段模式：按片段顺序拼接；旧任务（无片段分组）：按分镜逐镜拼接（同样支持 ≥2 部分合成）。"""
        tid = task.task_id
        if not task.script or not task.script.shots:
            raise ValueError("剧本分镜为空，无法合成")
        segs = task.script.segments or []
        local_paths, missing, total, unit = [], [], 0, "片段"
        if segs:
            # ---- 片段模式 ----
            total = len(segs)
            for i, seg in enumerate(segs):
                local_path = os.path.join("assets", "videos", f"{tid}_{seg.segment_id}.mp4")
                if seg.video_url and os.path.exists(local_path):
                    local_paths.append(local_path)
                else:
                    missing.append(i + 1)
        else:
            # ---- 单镜模式（旧任务兼容）----
            unit = "分镜"
            total = len(task.script.shots)
            for i, shot in enumerate(task.script.shots):
                local_path = os.path.join("assets", "videos", f"{tid}_{shot.shot_id}.mp4")
                if shot.video_url and os.path.exists(local_path):
                    local_paths.append(local_path)
                else:
                    missing.append(i + 1)
        if not local_paths:
            msg = f"还没有任何已生成的{unit}视频，请先点击「生成所在片段视频」生成至少 2 个{unit}再合成"
            await progress_hub.publish(tid, {"event": "compose", "status": "failed", "message": msg})
            await progress_hub.publish(tid, {"event": "log", "message": f"⚠️ {msg}"})
            return task
        if len(local_paths) < 2 and total > 1:
            msg = f"目前仅生成 1/{total} 个{unit}，至少生成 2 个{unit}才能合成（或全部生成后合成完整短剧）"
            await progress_hub.publish(tid, {"event": "compose", "status": "failed", "message": msg})
            await progress_hub.publish(tid, {"event": "log", "message": f"⚠️ {msg}"})
            return task
        partial = bool(missing)
        if partial:
            await progress_hub.publish(tid, {"event": "log",
                                             "message": f"ℹ️ 部分合成模式：跳过未生成的 {len(missing)} 个{unit}（第 {missing} 个{unit}），仅拼接已生成的 {len(local_paths)} 个{unit}"})
        await progress_hub.publish(tid, {"event": "status", "status": "composing", "message": "🎬 正在合成完整短剧视频…"})
        await progress_hub.publish(tid, {"event": "log",
                                         "message": f"🎬 开始合成：{len(local_paths)}/{total} 个已生成{unit}视频 → ffmpeg 拼接为完整视频…"})
        try:
            # ffmpeg 合成（本地路径已就绪，无需再下载）
            await progress_hub.publish(tid, {"event": "compose", "status": "progress", "index": 1, "total": len(local_paths),
                                             "message": f"🧩 正在用 ffmpeg 拼接 {len(local_paths)} 个{unit}视频…"})
            final_dir = os.path.join("assets", "final")
            os.makedirs(final_dir, exist_ok=True)
            output_path = os.path.join(final_dir, f"{tid}.mp4")
            await asyncio.to_thread(compose_videos, local_paths, output_path, None)
            # 完成：更新任务 + 发布 final 事件
            task.final_video_url = f"/assets/final/{tid}.mp4"
            if not missing:
                task.status = TaskStatus.DONE
            logger.info("compose ok | task=%s | output=%s | %d/%d %s%s", tid, task.final_video_url,
                        len(local_paths), total, unit, " (partial)" if partial else "")
            await progress_hub.publish(tid, {"event": "compose", "status": "ok", "index": len(local_paths), "total": len(local_paths),
                                             "message": "✅ 合成完成！"})
            final_msg = (f"🎉 短剧视频已合成：拼接了 {len(local_paths)}/{total} 个{unit}（跳过未生成的 {len(missing)} 个）"
                         if partial else f"🎉 完整短剧视频已合成：全部 {total} 个{unit}")
            await progress_hub.publish(tid, {"event": "final", "status": "ok",
                                             "final_video_url": task.final_video_url,
                                             "message": final_msg})
            await progress_hub.publish(tid, {"event": "log", "message": f"{final_msg}：{task.final_video_url}"})
        except Exception as e:
            logger.error("compose failed | task=%s | err=%s", tid, str(e)[:200])
            await progress_hub.publish(tid, {"event": "compose", "status": "failed", "message": f"合成失败：{e}"})
            await progress_hub.publish(tid, {"event": "log", "message": f"❌ 视频合成失败：{e}"})
        return task