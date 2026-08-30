from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Optional

class TaskStatus(str, Enum):
    PENDING = "pending"
    GENERATE_ASSET = "generating_asset"      # 角色图 + 场景图（昼夜双图）并行生成中
    HUMAN_REVIEW = "human_review"            # 图全部生成后的人工审核断点
    GENERATE_SHOT = "generating_shot"        # （旧流程保留）审核后生成分镜图
    GENERATE_VIDEO = "generating_video"      # 等待/正在逐片段生成视频（用户手动触发）
    DONE = "done"
    FAILED = "failed"

class Character(BaseModel):
    char_id: str
    name: str
    description: str
    reference_image: Optional[str] = None

class Scene(BaseModel):
    """场景：剧本中出现的独立场景，用于生成场景图（白天 / 黑夜两版）。
    场景图与角色立绘同属「形象资产」，放在前端角色形象栏展示。"""
    scene_key: str
    description: str  # 纯场景环境描述（无人物，含地点、时间、光线、氛围、主要物件）
    day_image_url: Optional[str] = None
    night_image_url: Optional[str] = None

class Shot(BaseModel):
    shot_id: str
    content: str  # 本镜场景描述（可引用 scene_key 对应场景，不再单独出图）
    camera: str
    lighting: str
    prompt: str
    character_names: Optional[List[str]] = None  # 本镜出现的角色名，用于一致性约束
    duration: Optional[int] = 4  # 本镜视频时长（秒），由大模型根据剧本节奏自动分配
    lines: Optional[str] = None  # 本镜台词/旁白（用于 TTS 配音），可为空
    scene_key: Optional[str] = None   # 场景标识（如"青云宗杂役房"），同场景连续分镜会被合并进同一个片段视频
    mouth_open: Optional[bool] = None  # 本镜台词是否为角色说出口的对白（视频生成时张嘴）；内心独白/旁白=False
    segment_id: Optional[str] = None  # 所属片段 ID（一个片段视频由多个分镜组成）
    video_url: Optional[str] = None  # 所属片段视频的本地 URL（同片段内所有分镜共享）

class Segment(BaseModel):
    """片段：多个连续分镜组成的一段视频（参考小云雀多分镜片段生成模式）。
    一个片段用一条多分镜 prompt 一次性生成，最终所有片段按顺序合成完整短剧。"""
    segment_id: str
    shot_ids: List[str] = Field(default_factory=list)  # 段内分镜（按剧情顺序）
    duration: int = 0  # 片段总时长（秒）= 段内各分镜时长之和
    scene_key: Optional[str] = None  # 片段主场景
    video_url: Optional[str] = None  # 片段视频本地 URL

class UpdateScriptRequest(BaseModel):
    """剧本编辑：标题 / 原始剧本内容"""
    title: Optional[str] = None
    raw_content: Optional[str] = None

class ReplaceImageRequest(BaseModel):
    task_id: str
    target_type: str  # character / scene_image
    target_id: str      # scene_image 格式：scene_key:day 或 scene_key:night

class RegenerateRequest(BaseModel):
    task_id: str
    target_type: str  # character / scene_image / shot_video / segment_video
    target_id: str    # scene_image 格式：scene_key:day 或 scene_key:night

class UpdateCharacterRequest(BaseModel):
    """角色信息编辑：姓名 / 性格详情"""
    char_id: str
    name: Optional[str] = None
    description: Optional[str] = None

class UpdateSceneRequest(BaseModel):
    """场景信息编辑：环境描述"""
    scene_key: str
    description: Optional[str] = None

class UpdateAudioModeRequest(BaseModel):
    """配音方式偏好：auto / native / tts"""
    audio_mode: str  # auto | native | tts

class UpdateShotRequest(BaseModel):
    """分镜信息编辑：文案 / 镜头 / 光影 / 生成 prompt（时长由大模型自动分配，不接受编辑）"""
    shot_id: str
    content: Optional[str] = None
    camera: Optional[str] = None
    lighting: Optional[str] = None
    prompt: Optional[str] = None

class ComposeVideoRequest(BaseModel):
    """触发分镜视频合成完整短剧"""
    task_id: str

class DramaScript(BaseModel):
    script_id: str
    title: str
    raw_content: str
    characters: List[Character]
    scenes: List[Scene]           # 剧本中出现的场景资产（每个场景生成昼夜双图）
    shots: List[Shot]
    segments: Optional[List[Segment]] = None  # 片段分组（step1 解析后由代码按场景+时长贪心分组）

class DramaTask(BaseModel):
    task_id: str
    thread_id: str
    user_prompt: str
    style: Optional[str] = "anime"  # 角色画风：anime / realistic / 3d / q版 / 国风 等
    status: TaskStatus
    script: Optional[DramaScript] = None
    final_video_url: Optional[str] = None
    audio_mode: Optional[str] = "auto"  # 配音方式：auto（按通道自动：ark 原生 / cv 走 TTS）/ native（强制原生）/ tts（强制 TTS）

class SubmitDramaRequest(BaseModel):
    user_prompt: str
    style: Optional[str] = "anime"

class HumanReviewConfirm(BaseModel):
    task_id: str
    accept: bool
    modify_characters: Optional[List[Character]] = None
