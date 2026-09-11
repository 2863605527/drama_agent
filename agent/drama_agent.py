import asyncio
from typing import Dict, Optional, Set, Tuple
from schema.drama_schema import DramaTask, DramaScript, TaskStatus, HumanReviewConfirm
from skill.drama_make_skill import DramaMakeSkill
from agent.progress_hub import progress_hub
from tools.logger_tool import get_logger, bind_log_context
from db.database import AsyncSessionLocal
from db import crud
from core import crypto, metrics
from tasks.dispatcher import schedule_segment_video, schedule_compose

logger = get_logger("drama.agent")


class DramaAgent:
    def __init__(self):
        self.skill = DramaMakeSkill()
        self.task_store: Dict[str, DramaTask] = {}
        self._busy: Set[Tuple[str, str]] = set()
        # 已删除任务集合：防止删除后仍在后台运行的残留协程把任务又写回内存/数据库
        self._deleted_ids: Set[str] = set()
        # 日志防抖落库任务（800ms 内的多条日志合并写一次库）
        self._log_flush_tasks: Dict[str, asyncio.Task] = {}
        logger.info("DramaAgent initialized")

    def _bind_log_sink(self, task: DramaTask):
        """把该任务的进度事件（带 message 的）追加到 task.logs 并防抖持久化，
        使刷新页面 / 服务重启后仍能从详情接口回显历史执行日志。"""
        tid = task.task_id
        if task.logs is None:
            task.logs = []

        async def _sink(event: dict):
            msg = event.get("message")
            if not msg or task.task_id in self._deleted_ids:
                return
            task.logs.append({"seq": event.get("seq"), "message": msg})
            # 仅保留最近 300 条，避免日志无限膨胀
            if len(task.logs) > 300:
                task.logs = task.logs[-300:]
            old = self._log_flush_tasks.pop(tid, None)
            if old and not old.done():
                old.cancel()

            async def _flush():
                try:
                    await asyncio.sleep(0.8)
                    await self._save_task(task)
                except Exception:
                    pass
                finally:
                    self._log_flush_tasks.pop(tid, None)

            self._log_flush_tasks[tid] = asyncio.create_task(_flush())

        progress_hub.bind_sink(tid, _sink)

    @staticmethod
    def _has_plain_sensitive(config: Optional[dict]) -> bool:
        """判断配置 dict 中是否含明文敏感字段（用于一次性迁移加密）。"""
        from schema.channel_schema import SENSITIVE_KEYS, iter_profile_dicts
        if not isinstance(config, dict):
            return False
        for _kind, prof in iter_profile_dicts(config):
            p = prof or {}
            for key in SENSITIVE_KEYS:
                v = p.get(key)
                if v and not (str(v).startswith("enc:") or str(v).startswith("b64:")):
                    return True
        return False

    @staticmethod
    def _decrypt_channel(raw) -> Optional[dict]:
        """DB 里的任务通道快照是【加密】落库（P1-3 安全加固：不落明文 Key）。
        这里统一解密为内存明文供执行使用；非 dict / 解密失败时原样兜底。"""
        if not isinstance(raw, dict):
            return None
        try:
            dec = crypto.decrypt_config(raw)
            return dec or None
        except Exception:
            return raw or None

    async def initialize(self):
        """启动时从 MySQL 加载所有任务到内存，实现重启不丢"""
        try:
            async with AsyncSessionLocal() as db:
                from db.models import Task as DBTask
                from sqlalchemy import select
                result = await db.execute(select(DBTask))
                count = 0
                for db_task in result.scalars().all():
                    try:
                        task = DramaTask(
                            task_id=db_task.task_id,
                            thread_id=db_task.task_id,
                            user_prompt=db_task.user_prompt,
                            style=db_task.style or "anime",
                            status=db_task.status or "pending",
                            audio_mode=db_task.audio_mode or "auto",
                            final_video_url=db_task.final_video_url,
                            user_id=db_task.user_id,
                            channel_profile=self._decrypt_channel(db_task.channel_config),
                            parent_id=getattr(db_task, "parent_id", None),
                            episode_no=getattr(db_task, "episode_no", None) or 1,
                            series_title=getattr(db_task, "series_title", None),
                            logs=getattr(db_task, "logs", None) or [],
                        )
                        if db_task.script_data:
                            task.script = DramaScript(**db_task.script_data)
                        # P1-3 存量迁移：早期任务通道快照是明文落库，检测到明文敏感字段则加密一次并落库
                        if isinstance(db_task.channel_config, dict) and self._has_plain_sensitive(db_task.channel_config):
                            await crud.update_task(db, db_task.task_id,
                                                   channel_config=crypto.encrypt_config(db_task.channel_config))
                        self.task_store[db_task.task_id] = task
                        self._bind_log_sink(task)
                        # 关键：用持久化日志恢复 seq 水位。否则进程重启后 progress_hub
                        # 的 seq 从 1 重新计数，前端拿着旧水位（更大的 seq）会把所有
                        # 新事件当"重复"丢弃——日志面板从此冻结（2026-09-04 实测踩坑）
                        try:
                            seq_floor = max((l.get("seq") or 0) for l in (task.logs or [])
                                            if isinstance(l, dict))
                            if seq_floor > 0:
                                progress_hub.set_seq_floor(task.task_id, seq_floor)
                        except Exception:
                            pass
                        count += 1
                    except Exception as e:
                        logger.warning("skip corrupted task %s: %s", db_task.task_id, e)
                logger.info("loaded %d tasks from MySQL", count)
        except Exception as e:
            logger.error("failed to load tasks from MySQL: %s", e)

    async def _save_task(self, task: DramaTask):
        """更新内存并持久化到 MySQL"""
        if task.task_id in self._deleted_ids:
            return  # 任务已被用户删除，后台残留协程不得再写回内存/数据库
        self.task_store[task.task_id] = task
        try:
            async with AsyncSessionLocal() as db:
                script_data = task.script.model_dump(mode="json") if task.script else None
                status_val = task.status.value if hasattr(task.status, "value") else str(task.status)
                existing = await crud.get_task_by_id(db, task.task_id)
                # 指标只统计【真实状态变更】，避免 0.8s 防抖内同一状态反复保存导致计数虚高
                if existing is None or (existing.status or "pending") != status_val:
                    metrics.TASK_STATUS.labels(status_val).inc()
                if existing:
                    await crud.update_task(
                        db, task.task_id,
                        status=status_val,
                        script_data=script_data,
                        final_video_url=task.final_video_url,
                        audio_mode=task.audio_mode,
                        logs=task.logs,
                        channel_config=crypto.encrypt_config(task.channel_profile or {}),  # 加密落库：不存明文 Key（P1-3）
                    )
                else:
                    await crud.create_task(
                        db, task.task_id, task.user_id or 0,
                        task.user_prompt, task.style or "anime", task.audio_mode or "auto",
                        channel_config=crypto.encrypt_config(task.channel_profile or {}),
                        parent_id=task.parent_id, episode_no=task.episode_no or 1,
                        series_title=task.series_title, logs=task.logs,
                    )
                    await crud.update_task(
                        db, task.task_id,
                        status=status_val, script_data=script_data,
                        final_video_url=task.final_video_url,
                    )
        except Exception as e:
            logger.error("failed to persist task %s: %s", task.task_id, e)

    async def _load_user_channel_profile(self, user_id: Optional[int]) -> Optional[dict]:
        """读取用户在前端配置的通道（解密为明文）；未配置/读取失败返回 None（走 .env 默认）。"""
        if not user_id:
            return None
        try:
            async with AsyncSessionLocal() as db:
                enc = await crud.get_user_channel_config(db, user_id)
            if not enc:
                return None
            profile = crypto.decrypt_config(enc)
            # 只保留真正自定义的段，全是 env 则视为无覆盖
            from schema.channel_schema import is_custom
            if not any(is_custom(profile.get(k)) for k in ("llm", "image", "video")):
                return None
            logger.info("task use user channel profile | user=%s | llm=%s image=%s video=%s",
                        user_id,
                        (profile.get("llm") or {}).get("channel"),
                        (profile.get("image") or {}).get("channel"),
                        (profile.get("video") or {}).get("channel"))
            return profile
        except Exception as e:
            logger.warning("load user channel profile failed, fallback to .env | user=%s | %s", user_id, e)
            return None

    async def _refresh_media_profile(self, task: DramaTask) -> DramaTask:
        """手动重绘/重生成/续写时，用用户「当前最新」的 LLM/图片/视频通道覆盖任务创建时的快照，
        这样用户在前端改了任意通道后，旧任务点重绘/重生成也会立即走新通道（含大模型）。
        视频是独立 job（从 DB 重新加载），所以这里变更后立即落库。"""
        try:
            latest = await self._load_user_channel_profile(getattr(task, "user_id", None))
            if not latest:
                return task
            from schema.channel_schema import is_custom
            snap = dict(task.channel_profile or {})
            changed = False
            for seg in ("llm", "image", "video"):
                if is_custom(latest.get(seg)) and snap.get(seg) != latest.get(seg):
                    snap[seg] = latest.get(seg)
                    changed = True
            if changed:
                task.channel_profile = snap
                await self._save_task(task)
                logger.info("manual action apply latest channel profile | task=%s | llm=%s image=%s video=%s",
                            task.task_id,
                            (snap.get("llm") or {}).get("channel"),
                            (snap.get("image") or {}).get("channel"),
                            (snap.get("video") or {}).get("channel"))
        except Exception as e:
            logger.warning("refresh media profile failed, keep task snapshot | task=%s | %s",
                           getattr(task, "task_id", "?"), e)
        return task

    async def _build_inherit_context(self, parent: DramaTask, episode_no: int, series_title: str) -> dict:
        """组装「续写下一集」的上下文：父集角色立绘 / 场景昼夜图 + 前情剧本，
        供 step1 解析时按名字/场景键继承资产。续集 retry 时同样用它重建，避免重试后退化为全新剧本。"""
        return {
            "episode_no": episode_no,
            "series_title": series_title,
            "prev_title": parent.script.title,
            "prev_raw": parent.script.raw_content or "",
            "characters": [
                {"name": c.name, "description": c.description, "reference_image": c.reference_image}
                for c in parent.script.characters],
            "scenes": [
                {"scene_key": s.scene_key, "description": s.description,
                 "day_image_url": s.day_image_url, "night_image_url": s.night_image_url}
                for s in parent.script.scenes],
        }

    async def submit_new_task(self, user_prompt: str, style: str = "anime",
                              user_id: Optional[int] = None,
                              parent_id: Optional[str] = None) -> DramaTask:
        """提交新任务：立即注册任务并返回（PENDING），
        流水线在后台执行，进度通过 SSE 事件流实时推送。
        parent_id 非空时为「续写下一集」：继承父系列已有角色/场景资产与通道，剧情承接前情。"""
        inherit_context = None
        episode_no, series_title, root_id, inherited_profile = 1, None, None, None
        if parent_id:
            parent = await self.load_task(parent_id)
            if not parent or not parent.script:
                raise ValueError("上一集不存在或尚未解析出剧本，无法续写")
            root_id = parent.parent_id or parent.task_id  # 系列根（第一集）id
            # 集数 = 同系列已有最大集数 + 1
            async with AsyncSessionLocal() as db:
                sib_rows = await crud.list_user_tasks(db, user_id or parent.user_id or 0)
            same_series_eps = [ (r.episode_no or 1) for r in sib_rows
                                if r.task_id == root_id or r.parent_id == root_id ]
            episode_no = (max(same_series_eps) if same_series_eps else parent.episode_no or 1) + 1
            series_title = parent.series_title or parent.script.title
            style = style or parent.style or "anime"
            inherited_profile = parent.channel_profile
            inherit_context = await self._build_inherit_context(parent, episode_no, series_title)
            logger.info("episode continue | root=%s | episode_no=%d | inherit chars=%d scenes=%d",
                        root_id, episode_no,
                        len(inherit_context["characters"]), len(inherit_context["scenes"]))

        task = await self.skill.create_task(user_prompt, style)
        if user_id:
            task.user_id = user_id
        if parent_id:
            task.parent_id = root_id
            task.episode_no = episode_no
            task.series_title = series_title
            task.inherit_context = inherit_context
        # 通道快照：续写优先继承父任务通道；否则用用户级通道配置；事后修改不影响在跑任务
        task.channel_profile = inherited_profile if parent_id else await self._load_user_channel_profile(user_id)
        if parent_id:
            # 续写时 LLM/图片/视频跟随用户「当前最新」配置覆盖快照：
            # 父任务快照可能是旧版 null（当时未配通道），若不刷新会导致续写仍走 .env 兜底的失效 Key（401）
            task = await self._refresh_media_profile(task)
        self._deleted_ids.discard(task.task_id)
        await self._save_task(task)
        progress_hub.create_stream(task.task_id)
        self._bind_log_sink(task)
        if parent_id:
            await progress_hub.publish(task.task_id, {"event": "log",
                "message": f"📚 开始续写《{series_title}》第 {episode_no} 集，正在承接上一集剧情与资产…"})
        logger.info("task submitted | %s | user=%s | episode=%s | pipeline starting in background",
                    task.task_id, user_id, task.episode_no)
        asyncio.create_task(self._run_initial_pipeline(task))
        return task

    async def _run_initial_pipeline(self, task: DramaTask):
        """后台流水线：剧本解析 → 展示空的角色/场景模块，等待用户手动逐个生成图片。"""
        bind_log_context(task_id=task.task_id)   # 该后台任务全链路日志自动带 task_id
        logger.info("pipeline[start] | %s", task.task_id)
        try:
            task = await self.skill.step1_parse_script(task)
            await self._save_task(task)
            char_n = len(task.script.characters)
            scene_n = len(task.script.scenes)
            await progress_hub.publish(task.task_id, {
                "event": "status", "status": "generating_asset",
                "message": "🎨 剧本解析完成，请逐个生成角色立绘与场景图（每场景需白天/黑夜两版）"
            })
            await progress_hub.publish(task.task_id, {"event": "log",
                "message": f"📋 剧本已解析：{char_n} 个角色 + {scene_n} 个场景（每场景昼夜 2 张图）= 共 {char_n + scene_n * 2} 张图待生成。请在下方「角色形象与场景」栏逐个点击「生成」按钮，全部完成后再确认审核进入视频阶段。"})
            logger.info("pipeline[paused at manual asset gen] | %s", task.task_id)
        except Exception as e:
            task.status = TaskStatus.FAILED
            await self._save_task(task)
            logger.error("pipeline[failed] | %s | err=%s", task.task_id, str(e)[:200])
            await progress_hub.publish(task.task_id, {"event": "fail", "message": f"❌ 流水线出错：{e}"})
            await progress_hub.publish(task.task_id, {"event": "log", "message": f"❌ 流水线出错：{e}"})

    async def delete_task(self, task_id: str) -> bool:
        """删除任务：清内存工作副本、关闭 SSE 进度流、删 MySQL 行。
        先打删除标记，确保仍在后台运行的残留协程不会把它再写回。"""
        task = self.task_store.get(task_id)
        self._deleted_ids.add(task_id)
        self.task_store.pop(task_id, None)
        # 释放该任务可能持有的忙锁
        for key in [k for k in self._busy if k[0] == task_id]:
            self._busy.discard(key)
        progress_hub.drop(task_id)
        ok = False
        try:
            async with AsyncSessionLocal() as db:
                ok = await crud.delete_task(db, task_id)
        except Exception as e:
            self._deleted_ids.discard(task_id)
            logger.error("delete task failed | %s | %s", task_id, e)
            raise
        # 顺带释放该任务在 MCP 层可能绑定的上下文（无副作用）
        logger.info("task deleted | %s | existed=%s", task_id, task is not None)
        return ok

    async def retry_task(self, task_id: str) -> Optional[DramaTask]:
        """失败/已完成任务「重新开始」：清空旧剧本与产物，重置为 pending，原地重跑初始解析流水线。
        保持同一 task_id，前端左侧选中态不跳变；旧执行日志清空后重新推送。"""
        task = await self.load_task(task_id)
        if not task:
            return None
        if task.status == TaskStatus.PENDING:
            raise ValueError("任务正在生成中，无需重复开始，请稍候")
        # 重跑前跟随用户「当前最新」通道（LLM/图片/视频）：旧快照可能缺失/过期（如 llm 段
        # 为 null 时走 .env 兜底、Key 失效导致 401），重新开始时一律用最新配置
        task = await self._refresh_media_profile(task)
        # 续集重跑：重建续写上下文（inherit_context 不落库，直接从 DB 重建任务时会丢失，
        # 导致重试退化为「全新剧本」、上一集角色立绘/场景图全部不带入——必须从父任务重新组装）
        if getattr(task, "parent_id", None):
            try:
                parent = await self.load_task(task.parent_id)
                if parent and parent.script:
                    task.inherit_context = await self._build_inherit_context(
                        parent,
                        task.episode_no or 2,
                        task.series_title or parent.series_title or parent.script.title)
                    logger.info("retry episode rebuild inherit | task=%s | parent=%s | chars=%d scenes=%d",
                                task.task_id, parent.task_id,
                                len(task.inherit_context["characters"]),
                                len(task.inherit_context["scenes"]))
            except Exception as e:
                logger.warning("retry rebuild inherit failed, run as standalone | task=%s | %s",
                               task.task_id, str(e)[:120])
        task.script = None
        task.final_video_url = None
        task.status = TaskStatus.PENDING
        self._deleted_ids.discard(task_id)
        await self._save_task(task)
        # 重置进度流，清掉上一次（含失败）的历史日志
        progress_hub.drop(task_id)
        progress_hub.create_stream(task_id)
        task.logs = []
        self._bind_log_sink(task)
        await progress_hub.publish(task_id, {"event": "status", "status": "pending"})
        await progress_hub.publish(task_id, {"event": "log",
                                             "message": "🔁 已重新开始，正在重新解析剧本…"})
        logger.info("task retry | %s", task_id)
        asyncio.create_task(self._run_initial_pipeline(task))
        return task

    async def human_review_handle(self, req: HumanReviewConfirm) -> Optional[DramaTask]:
        task = await self.load_task(req.task_id)
        if not task:
            return None
        if req.modify_characters:
            task.script.characters = req.modify_characters
        if req.accept:
            missing = []
            for c in task.script.characters:
                if not c.reference_image:
                    missing.append(f"角色「{c.name}」立绘")
            for sc in task.script.scenes:
                if not sc.day_image_url:
                    missing.append(f"场景「{sc.scene_key}」白天图")
                if not sc.night_image_url:
                    missing.append(f"场景「{sc.scene_key}」黑夜图")
            if missing:
                msg = f"❌ 还有 {len(missing)} 张图未生成/上传：{'、'.join(missing[:6])}{'…' if len(missing) > 6 else ''}。请先全部生成后再确认审核。"
                await progress_hub.publish(task.task_id, {"event": "log", "message": msg})
                raise ValueError(msg)
            task.status = TaskStatus.GENERATE_VIDEO
            await self._save_task(task)
            asyncio.create_task(self._run_video_pipeline(task))
        return task

    async def _run_video_pipeline(self, task: DramaTask):
        """审核通过后的阶段切换：不自动生成视频，
        片段视频与合成都由用户在前端手动触发"""
        bind_log_context(task_id=task.task_id)
        logger.info("pipeline[video stage] | %s", task.task_id)
        try:
            task = await self.skill.step3_after_human_review(task)
            await self._save_task(task)
        except Exception as e:
            task.status = TaskStatus.FAILED
            await self._save_task(task)
            logger.error("pipeline[video stage failed] | %s | err=%s", task.task_id, str(e)[:200])
            await progress_hub.publish(task.task_id, {"event": "fail", "message": f"❌ 视频阶段切换出错：{e}"})
            await progress_hub.publish(task.task_id, {"event": "log", "message": f"❌ 视频阶段切换出错：{e}"})

    def get_task(self, task_id: str) -> Optional[DramaTask]:
        """仅查内存（运行中工作副本），查不到返回 None"""
        return self.task_store.get(task_id)

    @staticmethod
    def _task_from_db(db_task) -> DramaTask:
        """DB 任务行 -> DramaTask 对象"""
        task = DramaTask(
            task_id=db_task.task_id,
            thread_id=db_task.task_id,
            user_prompt=db_task.user_prompt,
            style=db_task.style or "anime",
            status=db_task.status or "pending",
            audio_mode=db_task.audio_mode or "auto",
            final_video_url=db_task.final_video_url,
            user_id=db_task.user_id,
            channel_profile=DramaAgent._decrypt_channel(getattr(db_task, "channel_config", None)),
            parent_id=getattr(db_task, "parent_id", None),
            episode_no=getattr(db_task, "episode_no", None) or 1,
            series_title=getattr(db_task, "series_title", None),
            logs=getattr(db_task, "logs", None) or [],
        )
        if db_task.script_data:
            task.script = DramaScript(**db_task.script_data)
        return task

    async def _after_job(self, task_id: str, busy_key: tuple):
        """后台/Celery 长任务结束后：从 DB 刷新内存工作副本并释放忙锁。
        本地 asyncio 通道下 job 直接改的是从 DB 重建的对象，必须回刷 task_store，
        否则 load_task 会命中过期内存副本、看不到新生成的视频 URL。"""
        try:
            async with AsyncSessionLocal() as db:
                row = await crud.get_task_by_id(db, task_id)
                if row:
                    self.task_store[task_id] = self._task_from_db(row)
                else:
                    self.task_store.pop(task_id, None)
        except Exception as e:
            logger.warning("refresh task after job failed, drop cache | %s | %s", task_id, e)
            self.task_store.pop(task_id, None)
        finally:
            self._busy.discard(busy_key)

    async def load_task(self, task_id: str) -> Optional[DramaTask]:
        """统一加载入口：先查内存（运行中副本最新），没有则从 MySQL 恢复。
        API 层应使用本方法，避免依赖内存状态，支持多实例/重启后访问历史任务。"""
        task = self.task_store.get(task_id)
        if task:
            return task
        async with AsyncSessionLocal() as db:
            db_task = await crud.get_task_by_id(db, task_id)
            if not db_task:
                return None
            task = self._task_from_db(db_task)
            self.task_store[task_id] = task
            self._bind_log_sink(task)
            return task

    async def list_user_tasks(self, user_id: int) -> list:
        """列出指定用户的所有任务（以 DB 为准，内存副本覆盖最新状态）"""
        async with AsyncSessionLocal() as db:
            db_tasks = await crud.list_user_tasks(db, user_id)
            result = []
            for db_task in db_tasks:
                cached = self.task_store.get(db_task.task_id)
                result.append(cached if cached else self._task_from_db(db_task))
            return result

    async def update_script(self, task_id: str, title: Optional[str] = None,
                          raw_content: Optional[str] = None) -> Optional[DramaTask]:
        task = await self.load_task(task_id)
        if not task or not task.script:
            return None
        changed = []
        if title is not None and title.strip():
            task.script.title = title.strip()
            changed.append("标题")
        if raw_content is not None and raw_content.strip():
            task.script.raw_content = raw_content.strip()
            changed.append("剧本内容")
        if not changed:
            return task
        await self._save_task(task)
        await progress_hub.publish(task_id, {
            "event": "script_update",
            "title": task.script.title,
            "raw_content": task.script.raw_content
        })
        await progress_hub.publish(task_id, {"event": "log", "message": f"✏️ 剧本已更新{'、'.join(changed)}"})
        return task

    # ---------------- 手动替换图片 ----------------
    async def replace_image(self, task_id: str, target_type: str, target_id: str, image_url: str) -> Optional[DramaTask]:
        task = await self.load_task(task_id)
        if not task or not task.script:
            return None
        if target_type == "character":
            char = next((c for c in task.script.characters if c.char_id == target_id), None)
            if not char:
                return None
            char.reference_image = image_url
            idx = task.script.characters.index(char)
            await progress_hub.publish(task_id, {
                "event": "char", "index": idx, "total": len(task.script.characters),
                "char_id": char.char_id, "name": char.name, "description": char.description,
                "image_url": image_url, "status": "ok", "manual": True
            })
            await progress_hub.publish(task_id, {"event": "log", "message": f"🖼️ 角色「{char.name}」形象图已手动替换"})
        elif target_type == "scene_image":
            if ":" not in target_id:
                return None
            scene_key, variant = target_id.rsplit(":", 1)
            if variant not in ("day", "night"):
                return None
            scene = next((sc for sc in task.script.scenes if sc.scene_key == scene_key), None)
            if not scene:
                return None
            idx = task.script.scenes.index(scene)
            if variant == "day":
                scene.day_image_url = image_url
                # 白天底图被替换，旧黑夜图与之不再匹配，清空并提示基于新白天图重生成
                if scene.night_image_url:
                    scene.night_image_url = None
                    await progress_hub.publish(task_id, {
                        "event": "scene_img", "index": idx, "total": len(task.script.scenes),
                        "scene_key": scene.scene_key, "variant": "night",
                        "image_url": None, "status": "reset"
                    })
                    await progress_hub.publish(task_id, {"event": "log",
                                                         "message": "ℹ️ 白天图已更换，原黑夜图已清空，请基于新白天图重新生成黑夜图"})
            else:
                scene.night_image_url = image_url
            await progress_hub.publish(task_id, {
                "event": "scene_img", "index": idx, "total": len(task.script.scenes),
                "scene_key": scene.scene_key, "variant": variant,
                "image_url": image_url, "status": "ok", "manual": True
            })
            await progress_hub.publish(task_id, {"event": "log", "message": f"🖼️ 场景「{scene.scene_key}」（{'白天' if variant == 'day' else '黑夜'}）图片已手动替换"})
        else:
            return None
        await self._save_task(task)
        # 手动上传补齐最后一张图后，同样自动从「待生成形象」跃迁到「人工审核」
        await self._maybe_advance_to_review(task)
        return task

    async def clear_image(self, task_id: str, target_type: str, target_id: str) -> Optional[DramaTask]:
        """用户主动清除某张已生成/上传的图片（角色立绘 / 场景白天或黑夜）。
        只清空图片字段并广播，任务状态只进不退；清除白天图时连带清空依赖它的黑夜图。"""
        task = await self.load_task(task_id)
        if not task or not task.script:
            return None
        if target_type == "character":
            char = next((c for c in task.script.characters if c.char_id == target_id), None)
            if not char:
                return None
            idx = task.script.characters.index(char)
            char.reference_image = None
            await progress_hub.publish(task_id, {
                "event": "char", "index": idx, "total": len(task.script.characters),
                "char_id": char.char_id, "name": char.name, "description": char.description,
                "image_url": None, "status": "clear", "manual": True})
            await progress_hub.publish(task_id, {"event": "log",
                                                 "message": f"🧹 已清除角色「{char.name}」的形象图"})
        elif target_type == "scene_image":
            if ":" not in target_id:
                return None
            scene_key, variant = target_id.rsplit(":", 1)
            if variant not in ("day", "night"):
                return None
            scene = next((sc for sc in task.script.scenes if sc.scene_key == scene_key), None)
            if not scene:
                return None
            idx = task.script.scenes.index(scene)

            async def _emit(v):
                await progress_hub.publish(task_id, {
                    "event": "scene_img", "index": idx, "total": len(task.script.scenes),
                    "scene_key": scene.scene_key, "variant": v,
                    "image_url": None, "status": "clear", "manual": True})

            if variant == "day":
                scene.day_image_url = None
                await _emit("day")
                if scene.night_image_url:  # 黑夜依赖白天，一并清除
                    scene.night_image_url = None
                    await _emit("night")
                await progress_hub.publish(task_id, {"event": "log",
                                                     "message": f"🧹 已清除场景「{scene.scene_key}」白天图（依赖它的黑夜图一并清除）"})
            else:
                scene.night_image_url = None
                await _emit("night")
                await progress_hub.publish(task_id, {"event": "log",
                                                     "message": f"🧹 已清除场景「{scene.scene_key}」黑夜图"})
        else:
            return None
        await self._save_task(task)
        return task

    # ---------------- 失败重试 ----------------
    @staticmethod
    def _all_assets_ready(task: DramaTask) -> bool:
        """判断角色立绘 + 每个场景的昼夜图是否全部就绪（含续写继承来的已有图）。"""
        script = task.script
        if not script:
            return False
        chars = script.characters or []
        scenes = script.scenes or []
        if not chars or not scenes:
            return False
        if not all(getattr(c, "reference_image", None) for c in chars):
            return False
        for sc in scenes:
            if not (getattr(sc, "day_image_url", None) and getattr(sc, "night_image_url", None)):
                return False
        return True

    async def _maybe_advance_to_review(self, task: DramaTask) -> None:
        """资产阶段对账（手动逐张出图 / 上传后调用）：
        仅在仍处于「待生成形象」且全部图就绪时，自动跃迁到「人工审核」。
        一旦进入人工审核及之后的阶段，状态只进不退——用户重绘/替换图片只更新图片本身，
        不再回退状态（是否继续由用户自己决定）。"""
        try:
            cur = task.status.value if hasattr(task.status, "value") else str(task.status)
            if cur == TaskStatus.GENERATE_ASSET.value and self._all_assets_ready(task):
                task.status = TaskStatus.HUMAN_REVIEW
                await self._save_task(task)
                await progress_hub.publish(task.task_id, {"event": "log",
                                                          "message": "🎉 角色立绘与昼夜场景图已全部就绪，进入人工审核"})
                await progress_hub.publish(task.task_id, {"event": "status", "status": "human_review",
                                                          "message": "⏸️ 角色与场景图全部生成完毕，等待人工审核"})
        except Exception as e:
            logger.warning("maybe_advance_to_review failed | task=%s | err=%s", task.task_id, e)

    async def regenerate(self, task_id: str, target_type: str, target_id: str) -> Optional[DramaTask]:
        task = await self.load_task(task_id)
        if not task or not task.script:
            return None
        bind_log_context(task_id=task_id)
        await self._refresh_media_profile(task)  # 手动重绘/重生成跟随用户当前最新图片/视频通道

        # ---------- 图片类：耗时短，同步执行后返回 ----------
        if target_type in ("character", "scene_image"):
            key = f"{target_type}:{target_id}"
            if (task_id, key) in self._busy:
                logger.warning("regenerate ignored (busy) | %s | %s", task_id, key)
                return task
            self._busy.add((task_id, key))
            try:
                if target_type == "character":
                    await self.skill.regenerate_character_image(task, target_id)
                else:
                    await self.skill.regenerate_scene_image(task, target_id)
                await self._save_task(task)
                # 手动逐张出图：最后一张补齐后，自动从「待生成形象」跃迁到「人工审核」
                await self._maybe_advance_to_review(task)
            except Exception as e:
                await progress_hub.publish(task_id, {"event": "log", "message": f"❌ 重试出错：{e}"})
            finally:
                self._busy.discard((task_id, key))
            return task

        # ---------- 视频类：长任务，异步分发（本地后台 / Celery），不阻塞 HTTP ----------
        segment_id = None
        if target_type == "segment_video":
            segment_id = target_id
        elif target_type == "shot_video":
            shot = next((s for s in task.script.shots if s.shot_id == target_id), None)
            segment_id = shot.segment_id if shot else None
            if not segment_id:
                # 兼容旧任务（无片段分组的单镜）：本地后台重生成
                return await self._legacy_shot_regen(task_id, target_id)
        else:
            return None

        seg = next((g for g in (task.script.segments or []) if g.segment_id == segment_id), None)
        if seg is None:
            return task
        key = f"segment_video:{segment_id}"
        if (task_id, key) in self._busy:
            logger.warning("segment video ignored (busy) | %s | %s", task_id, key)
            return task
        self._busy.add((task_id, key))
        mode = await schedule_segment_video(
            task_id, segment_id, on_finish=lambda: self._after_job(task_id, (task_id, key)))
        if mode == "celery":
            self._busy.discard((task_id, key))   # worker 独立进程，Web 不长期持本地忙锁   # worker 独立进程，Web 不长期持本地忙锁
        logger.info("segment video scheduled | task=%s | seg=%s | mode=%s", task_id, segment_id, mode)
        return task

    async def _legacy_shot_regen(self, task_id: str, shot_id: str) -> Optional[DramaTask]:
        """旧任务（无片段分组）的单镜视频重生成：本地 asyncio 后台执行。"""
        task = await self.load_task(task_id)
        if not task:
            return None
        key = f"shot_video:{shot_id}"
        if (task_id, key) in self._busy:
            return task
        self._busy.add((task_id, key))

        async def _bg():
            try:
                await self.skill.regenerate_shot_video(task, shot_id)
                await self._save_task(task)
            except Exception as e:
                await progress_hub.publish(task_id, {"event": "log", "message": f"❌ 重试出错：{e}"})
            finally:
                self._busy.discard((task_id, key))

        asyncio.create_task(_bg())
        return task

    # ---------------- 角色信息编辑 ----------------
    async def update_character(self, task_id: str, char_id: str, name: Optional[str] = None,
                               description: Optional[str] = None) -> Optional[DramaTask]:
        task = await self.load_task(task_id)
        if not task or not task.script:
            return None
        char = next((c for c in task.script.characters if c.char_id == char_id), None)
        if not char:
            return None
        changed = []
        if name is not None and name.strip():
            char.name = name.strip()
            changed.append("姓名")
        if description is not None and description.strip():
            char.description = description.strip()
            changed.append("性格详情")
        if not changed:
            return task
        await self._save_task(task)
        await progress_hub.publish(task_id, {
            "event": "char_update",
            "char_id": char.char_id,
            "name": char.name,
            "description": char.description,
            "image_url": char.reference_image
        })
        await progress_hub.publish(task_id, {"event": "log", "message": f"✏️ 角色「{char.name}」已更新{'、'.join(changed)}"})
        return task

    # ---------------- 配音方式偏好 ----------------
    async def update_audio_mode(self, task_id: str, audio_mode: str) -> Optional[DramaTask]:
        task = await self.load_task(task_id)
        if not task:
            return None
        if audio_mode not in ("auto", "native", "tts"):
            return task
        task.audio_mode = audio_mode
        await self._save_task(task)
        label = {"auto": "自动（按通道）", "native": "原生音频", "tts": "TTS 配音"}[audio_mode]
        await progress_hub.publish(task_id, {"event": "log", "message": f"🎙️ 配音方式已切换为：{label}"})
        return task

    # ---------------- 场景信息编辑 ----------------
    async def update_scene(self, task_id: str, scene_key: str,
                           description: Optional[str] = None) -> Optional[DramaTask]:
        task = await self.load_task(task_id)
        if not task or not task.script:
            return None
        scene = next((sc for sc in task.script.scenes if sc.scene_key == scene_key), None)
        if not scene:
            return None
        if description is not None and description.strip():
            scene.description = description.strip()
        else:
            return task
        await self._save_task(task)
        await progress_hub.publish(task_id, {
            "event": "scene_update",
            "scene_key": scene.scene_key,
            "description": scene.description,
            "day_image_url": scene.day_image_url,
            "night_image_url": scene.night_image_url
        })
        await progress_hub.publish(task_id, {"event": "log", "message": f"✏️ 场景「{scene.scene_key}」描述已更新"})
        return task

    # ---------------- 分镜信息编辑 ----------------
    async def update_shot(self, task_id: str, shot_id: str, content: Optional[str] = None,
                          camera: Optional[str] = None, lighting: Optional[str] = None,
                          prompt: Optional[str] = None) -> Optional[DramaTask]:
        task = await self.load_task(task_id)
        if not task or not task.script:
            return None
        shot = next((s for s in task.script.shots if s.shot_id == shot_id), None)
        if not shot:
            return None
        changed = []
        if content is not None and content.strip():
            shot.content = content.strip()
            changed.append("文案")
        if camera is not None and camera.strip():
            shot.camera = camera.strip()
            changed.append("镜头")
        if lighting is not None and lighting.strip():
            shot.lighting = lighting.strip()
            changed.append("光影")
        if prompt is not None and prompt.strip():
            shot.prompt = prompt.strip()
            changed.append("画面描述")
        if not changed:
            return task
        await self._save_task(task)
        idx = task.script.shots.index(shot)
        await progress_hub.publish(task_id, {
            "event": "shot_update",
            "index": idx,
            "total": len(task.script.shots),
            "shot_id": shot.shot_id,
            "content": shot.content,
            "camera": shot.camera,
            "lighting": shot.lighting,
            "prompt": shot.prompt,
            "video_url": shot.video_url
        })
        await progress_hub.publish(task_id, {"event": "log", "message": f"✏️ 分镜 {idx + 1} 已更新{'、'.join(changed)}"})
        return task

    # ---------------- 合成完整视频 ----------------
    async def compose_video(self, task_id: str) -> Optional[DramaTask]:
        task = await self.load_task(task_id)
        if not task:
            return None
        key = "compose"
        if (task_id, key) in self._busy:
            return task
        self._busy.add((task_id, key))
        # 长任务统一走分发器：本地 asyncio 后台 / Celery 队列（USE_CELERY 切换）
        mode = await schedule_compose(
            task_id, on_finish=lambda: self._after_job(task_id, (task_id, key)))
        if mode == "celery":
            # worker 独立进程执行，Web 进程不长期持有本地忙锁（状态以 DB/SSE 为准）
            self._busy.discard((task_id, key))
        logger.info("compose scheduled | task=%s | mode=%s", task_id, mode)
        return task
