import asyncio
from typing import Dict, Optional, Set, Tuple
from schema.drama_schema import DramaTask, TaskStatus, HumanReviewConfirm
from skill.drama_make_skill import DramaMakeSkill
from agent.progress_hub import progress_hub
from tools.logger_tool import get_logger

logger = get_logger("drama.agent")


class DramaAgent:
    def __init__(self):
        self.skill = DramaMakeSkill()
        self.task_store: Dict[str, DramaTask] = {}  # 内存存储；正式项目替换sqlite
        self._busy: Set[Tuple[str, str]] = set()  # (task_id, resource_key) 防并发重试
        logger.info("DramaAgent initialized")

    async def submit_new_task(self, user_prompt: str, style: str = "anime") -> DramaTask:
        """提交新任务：立即注册任务并返回（PENDING），
        流水线在后台执行，进度通过 SSE 事件流实时推送。"""
        task = await self.skill.create_task(user_prompt, style)
        self.task_store[task.task_id] = task
        progress_hub.create_stream(task.task_id)
        logger.info("task submitted | %s | pipeline starting in background", task.task_id)
        asyncio.create_task(self._run_initial_pipeline(task))
        return task

    async def _run_initial_pipeline(self, task: DramaTask):
        """后台流水线：剧本解析 → 展示空的角色/场景模块，等待用户手动逐个生成图片。
        图片（角色立绘 + 场景昼夜双图）不再自动生成，由用户在前端逐个点击「生成」或「上传」，
        全部就绪后通过人工审核进入视频阶段。"""
        logger.info("pipeline[start] | %s", task.task_id)
        try:
            task = await self.skill.step1_parse_script(task)
            self.task_store[task.task_id] = task
            # 不再自动 step2_gen_asset：停在 GENERATE_ASSET，等用户手动生成图片
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
            self.task_store[task.task_id] = task
            logger.error("pipeline[failed] | %s | err=%s", task.task_id, str(e)[:200])
            await progress_hub.publish(task.task_id, {"event": "fail", "message": f"❌ 流水线出错：{e}"})
            await progress_hub.publish(task.task_id, {"event": "log", "message": f"❌ 流水线出错：{e}"})

    async def human_review_handle(self, req: HumanReviewConfirm) -> Optional[DramaTask]:
        task = self.task_store.get(req.task_id)
        if not task:
            return None
        if req.modify_characters:
            task.script.characters = req.modify_characters
        if req.accept:
            # 门槛校验：所有角色立绘 + 所有场景昼夜双图必须就绪，否则拒绝进入视频阶段
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
            # 审核通过：图片已全部就绪，进入「逐片段生成视频」阶段
            task.status = TaskStatus.GENERATE_VIDEO
            self.task_store[task.task_id] = task
            asyncio.create_task(self._run_video_pipeline(task))
        return task

    async def _run_video_pipeline(self, task: DramaTask):
        """审核通过后的阶段切换：不自动生成视频，
        片段视频与合成都由用户在前端手动触发"""
        logger.info("pipeline[video stage] | %s", task.task_id)
        try:
            task = await self.skill.step3_after_human_review(task)
            self.task_store[task.task_id] = task
        except Exception as e:
            task.status = TaskStatus.FAILED
            self.task_store[task.task_id] = task
            logger.error("pipeline[video stage failed] | %s | err=%s", task.task_id, str(e)[:200])
            await progress_hub.publish(task.task_id, {"event": "fail", "message": f"❌ 视频阶段切换出错：{e}"})
            await progress_hub.publish(task.task_id, {"event": "log", "message": f"❌ 视频阶段切换出错：{e}"})

    def get_task(self, task_id: str) -> Optional[DramaTask]:
        return self.task_store.get(task_id)

    async def update_script(self, task_id: str, title: Optional[str] = None,
                          raw_content: Optional[str] = None) -> Optional[DramaTask]:
        """手动编辑剧本标题与原始剧本内容，更新模型并通知前端"""
        task = self.task_store.get(task_id)
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
        self.task_store[task_id] = task
        await progress_hub.publish(task_id, {
            "event": "script_update",
            "title": task.script.title,
            "raw_content": task.script.raw_content
        })
        await progress_hub.publish(task_id, {"event": "log", "message": f"✏️ 剧本已更新{'、'.join(changed)}"})
        return task

    # ---------------- 手动替换图片 ----------------
    async def replace_image(self, task_id: str, target_type: str, target_id: str, image_url: str) -> Optional[DramaTask]:
        """手动替换角色形象图 / 分镜图，更新模型并发布事件通知前端"""
        task = self.task_store.get(task_id)
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
            # target_id 格式：scene_key:day 或 scene_key:night
            if ":" not in target_id:
                return None
            scene_key, variant = target_id.rsplit(":", 1)
            if variant not in ("day", "night"):
                return None
            scene = next((sc for sc in task.script.scenes if sc.scene_key == scene_key), None)
            if not scene:
                return None
            if variant == "day":
                scene.day_image_url = image_url
            else:
                scene.night_image_url = image_url
            idx = task.script.scenes.index(scene)
            await progress_hub.publish(task_id, {
                "event": "scene_img", "index": idx, "total": len(task.script.scenes),
                "scene_key": scene.scene_key, "variant": variant,
                "image_url": image_url, "status": "ok", "manual": True
            })
            await progress_hub.publish(task_id, {"event": "log", "message": f"🖼️ 场景「{scene.scene_key}」（{'白天' if variant == 'day' else '黑夜'}）图片已手动替换"})
        else:
            return None
        self.task_store[task_id] = task
        return task

    # ---------------- 失败重试 ----------------
    async def regenerate(self, task_id: str, target_type: str, target_id: str) -> Optional[DramaTask]:
        """重新生成失败的角色图 / 分镜图 / 片段视频（带防并发保护）"""
        task = self.task_store.get(task_id)
        if not task or not task.script:
            return None
        # 防并发键：片段模式下 shot_video 归并到所属片段，
        # 避免同片段两个分镜按钮同时点击导致同一片段生成两遍
        key = f"{target_type}:{target_id}"
        if target_type == "shot_video" and task.script.segments:
            shot = next((s for s in task.script.shots if s.shot_id == target_id), None)
            if shot and shot.segment_id:
                key = f"segment_video:{shot.segment_id}"
        if (task_id, key) in self._busy:
            logger.warning("regenerate ignored (busy) | %s | %s", task_id, key)
            return task  # 该资源正在重新生成中，忽略重复请求
        self._busy.add((task_id, key))
        try:
            if target_type == "character":
                await self.skill.regenerate_character_image(task, target_id)
            elif target_type == "scene_image":
                # target_id 格式：scene_key:day / scene_key:night
                await self.skill.regenerate_scene_image(task, target_id)
            elif target_type == "shot_video":
                # 新任务自动转发为"该分镜所属片段"的重新生成（skill 内部判断）
                await self.skill.regenerate_shot_video(task, target_id)
            elif target_type == "segment_video":
                await self.skill.regenerate_segment_video(task, target_id)
            else:
                return None
            self.task_store[task_id] = task
        except Exception as e:
            await progress_hub.publish(task_id, {"event": "log", "message": f"❌ 重试出错：{e}"})
        finally:
            self._busy.discard((task_id, key))
        return task

    # ---------------- 角色信息编辑（姓名 / 性格详情） ----------------
    async def update_character(self, task_id: str, char_id: str, name: Optional[str] = None,
                               description: Optional[str] = None) -> Optional[DramaTask]:
        """手动编辑角色姓名与性格详情，更新模型并发布事件通知前端"""
        task = self.task_store.get(task_id)
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
        self.task_store[task_id] = task
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
        """切换配音方式：auto（按通道自动：ark 原生 / cv 走 TTS）/ native（强制原生音频）/ tts（强制 TTS 配音）"""
        task = self.task_store.get(task_id)
        if not task:
            return None
        if audio_mode not in ("auto", "native", "tts"):
            return task
        task.audio_mode = audio_mode
        self.task_store[task_id] = task
        label = {"auto": "自动（按通道）", "native": "原生音频", "tts": "TTS 配音"}[audio_mode]
        await progress_hub.publish(task_id, {"event": "log", "message": f"🎙️ 配音方式已切换为：{label}"})
        return task

    # ---------------- 场景信息编辑 ----------------
    async def update_scene(self, task_id: str, scene_key: str,
                           description: Optional[str] = None) -> Optional[DramaTask]:
        """手动编辑场景环境描述，更新模型并通知前端（下次重新生成场景图时生效）"""
        task = self.task_store.get(task_id)
        if not task or not task.script:
            return None
        scene = next((sc for sc in task.script.scenes if sc.scene_key == scene_key), None)
        if not scene:
            return None
        if description is not None and description.strip():
            scene.description = description.strip()
        else:
            return task
        self.task_store[task_id] = task
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
        """手动编辑分镜文案、镜头、光影、生成 prompt，更新模型并通知前端。
        注意：分镜时长 duration 由大模型解析剧本时自动分配，不提供手动编辑入口。"""
        task = self.task_store.get(task_id)
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
        self.task_store[task_id] = task
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
        """触发将全部分镜视频合成为一个完整短剧视频（后台执行，带防并发）"""
        task = self.task_store.get(task_id)
        if not task:
            return None
        key = "compose"
        if (task_id, key) in self._busy:
            return task  # 合成任务已在执行中
        self._busy.add((task_id, key))
        asyncio.create_task(self._run_compose(task))
        return task

    async def _run_compose(self, task: DramaTask):
        logger.info("pipeline[compose] | %s", task.task_id)
        try:
            task = await self.skill.compose_final_video(task)
            self.task_store[task.task_id] = task
        except Exception as e:
            logger.error("pipeline[compose failed] | %s | err=%s", task.task_id, str(e)[:200])
            await progress_hub.publish(task.task_id, {"event": "compose", "status": "failed", "message": f"合成出错：{e}"})
            await progress_hub.publish(task.task_id, {"event": "log", "message": f"❌ 合成出错：{e}"})
        finally:
            self._busy.discard((task.task_id, "compose"))
