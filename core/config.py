"""统一配置管理：基于 pydantic-settings，启动时校验必需环境变量。

tools 层历史代码仍可直接用 os.getenv 读取同一批环境变量（本模块导入时会 load_dotenv），
新代码统一使用 ``from core.config import settings``。
"""
import os
from functools import lru_cache
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---------- 应用 ----------
    app_name: str = "Drama-Agent"
    app_port: int = 8010
    debug: bool = False
    environment: str = Field(default="production", description="development / production")
    cors_origins: str = Field(
        default="http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8010,http://localhost:8010",
        description="逗号分隔的允许来源（P1-6 安全收敛：不再默认 *；生产环境务必在 .env 配置实际域名）")

    # ---------- MySQL ----------
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "drama"
    mysql_password: str = "drama_2024"
    mysql_database: str = "drama_agent"

    @property
    def database_url(self) -> str:
        return (f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
                f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4")

    # ---------- JWT ----------
    jwt_secret_key: str = "please-change-this-to-a-random-secret-string"
    jwt_expire_minutes: int = 1440
    jwt_algorithm: str = "HS256"

    # ---------- LLM ----------
    llm_api_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.7
    llm_max_retries: int = 3
    llm_retry_base: float = 2.0

    # ---------- 火山引擎 ----------
    volc_access_key: str = ""
    volc_secret_key: str = ""
    volc_region: str = "cn-beijing"

    # ---------- 图片 ----------
    image_channel: str = "volc_cv"
    image_req_key: str = "jimeng_high_aes_general_v21_L"
    image_max_concurrency: int = 3
    image_width: int = 1024
    image_height: int = 1024

    # ---------- 视频 ----------
    video_channel: str = "volc_cv"
    video_req_key: str = "jimeng_t2v_v30"
    video_max_concurrency: int = 2
    video_duration_range: str = "3,15"
    video_duration_slots: str = "121:5,241:10"
    video_trim: bool = True
    video_resolution: str = "1080p"
    video_duration: int = 4
    video_any_param: str = ""
    video_slot_frames: str = ""
    video_slot_param: str = ""

    # ---------- 片段分组 ----------
    segment_max_duration: int = 15
    segment_max_shots: int = 4

    # ---------- TTS ----------
    enable_tts: bool = True
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_rate: str = "+0%"

    # ---------- 方舟（可选）----------
    ark_api_key: str = ""
    ark_api_url: str = ""
    ark_video_model: str = ""
    ark_image_model: str = ""
    ark_video_audio: bool = True
    ark_video_dur_min: int = 1
    ark_video_dur_max: int = 15
    ark_video_ratio: str = "9:16"
    ark_video_resolution: str = "720p"

    # ---------- MCP ----------
    python_bin: str = "python"
    mcp_call_timeout: int = 180

    # ---------- 可观测性 ----------
    log_format: str = Field(default="text", description="text 彩色文本 / json 结构化单行 JSON")
    sentry_dsn: str = Field(default="", description="Sentry DSN，留空则不启用错误上报")
    sentry_traces_sample: float = Field(default=0.05, description="Sentry 性能采样率 0~1")
    app_version: str = Field(default="0.1.0", description="版本号，用于 Sentry release 与指标标签")

    # ---------- 限流 ----------
    login_rate_limit: str = "5/minute"   # 登录/注册窗口
    api_rate_limit: str = "120/minute"   # 全局 API 窗口

    # ---------- 多实例扩展（可选，单机留空）：Redis 用于分布式限流与 SSE 跨实例广播 ----------
    redis_url: str = ""

    # ---------- 异步任务队列（可选）：USE_CELERY=true 时视频/合成走 Celery+Redis ----------
    # 默认 false：本地开发用进程内 asyncio 后台任务，零额外依赖；
    # 生产设 true 并提供 REDIS_URL：长任务交给独立 celery worker，Web 进程不阻塞、可水平扩容。
    use_celery: bool = False
    celery_broker_url: str = ""        # 留空则回退 redis_url
    celery_result_backend: str = ""    # 留空则回退 redis_url
    celery_concurrency: int = 2        # 单 worker 并发视频任务数（对齐 VIDEO_MAX_CONCURRENCY）
    task_soft_time_limit: int = 1800   # 单任务软超时（秒）
    task_hard_time_limit: int = 2100   # 单任务硬超时（秒）

    def validate_required(self) -> list[str]:
        """返回缺失的关键配置列表（启动时调用，缺则打印警告；生产环境缺密钥直接报错）"""
        problems = []
        if not self.llm_api_key:
            problems.append("LLM_API_KEY 未配置，剧本生成将失败")
        if not self.volc_access_key or not self.volc_secret_key:
            problems.append("VOLC_ACCESS_KEY/VOLC_SECRET_KEY 未配置，图片/视频生成将失败")
        if self.environment == "production" and self.jwt_secret_key == "please-change-this-to-a-random-secret-string":
            problems.append("生产环境必须修改 JWT_SECRET_KEY 为随机字符串")
        return problems

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if not raw:
            return []
        return [x.strip() for x in raw.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
