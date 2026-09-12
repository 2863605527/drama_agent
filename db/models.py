from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.sql import func
from db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    # P0：token 版本号。改密码 / 封号 / 「退出所有设备」时 +1，已签发 JWT 全部失效（吊销机制）
    token_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class UserChannelConfig(Base):
    """用户级模型通道配置（LLM/图片/视频通道、模型、Key；Key 加密后存于 config JSON）。"""
    __tablename__ = "user_channel_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True, nullable=False)
    config = Column(JSON, nullable=True)           # 加密后的 {llm/image/video: {...}}
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    user_prompt = Column(Text, nullable=False)
    style = Column(String(32), default="anime")
    audio_mode = Column(String(16), default="auto")
    status = Column(String(32), default="pending")
    script_data = Column(JSON, nullable=True)  # DramaScript 完整序列化
    channel_config = Column(JSON, nullable=True)  # 提交时的用户通道配置快照（解密后的明文，仅本任务使用）
    final_video_url = Column(String(512), nullable=True)
    # —— 多集续写 ——
    parent_id = Column(String(64), nullable=True, index=True)  # 系列根任务（第一集）id
    episode_no = Column(Integer, default=1)                    # 第几集
    series_title = Column(String(255), nullable=True)          # 系列剧名
    logs = Column(JSON, nullable=True)                         # 持久化执行日志 [{seq,message}]
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Asset(Base):
    """个人资产元数据。

    图片/视频/音频的文件本体存磁盘（assets/，未来可换对象存储），数据库只登记元数据：
    归属用户、类型、来源、体积、被引用次数等，用于用户隔离、素材库、配额与安全的生命周期回收。
    一个 /assets/... URL 对应一行（url 唯一），登记幂等。
    """
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String(512), unique=True, index=True, nullable=False)   # 访问 URL，如 /assets/images/img_x.png
    rel_path = Column(String(512), nullable=False)                       # 相对 assets 根的路径，如 images/img_x.png
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # 归属用户（逻辑隔离）
    asset_type = Column(String(32), default="unknown", index=True)
    # character/scene_day/scene_night/segment_video/shot_video/shot_audio/final_video/upload/image/unknown
    source = Column(String(16), default="ai", index=True)                # ai=模型生成，upload=用户上传（永不自动删）
    task_id = Column(String(64), nullable=True, index=True)              # 首次产生该资产的任务（上传素材可被复用，可空）
    mime = Column(String(64), nullable=True)
    size_bytes = Column(BigInteger, default=0)
    sha256 = Column(String(64), nullable=True, index=True)               # 去重/校验（大文件可跳过）
    ref_count = Column(Integer, default=0, index=True)                   # 被任务引用次数（定期重建，GC 以实时扫描为准）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
