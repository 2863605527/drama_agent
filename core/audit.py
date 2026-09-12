"""审计日志（P2-11）：落库记录关键安全/操作事件，供事后追溯。

设计原则：
- 只记事件不存敏感明文（密码/Key 一律不落库，detail 只放业务标识）；
- 写入失败不影响主流程（try/except 吞掉并记日志）；
- 无角色体系，不提供查询 API（避免越权），文档说明可用 SQL 审计。
"""
import json

from sqlalchemy import Column, Integer, String, JSON, DateTime, BigInteger
from sqlalchemy.sql import func

from db.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    # Integer 主键：SQLite 下为 rowid 别名自动自增；MySQL 下 AUTO_INCREMENT
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)      # 匿名事件（如登录失败）可为空
    action = Column(String(64), nullable=False, index=True)   # register / login / login_failed / ...
    detail = Column(JSON, nullable=True)                      # 业务标识（不含敏感值）
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


async def audit(db, user_id, action: str, detail: dict | None = None, ip: str | None = None):
    """写入一条审计记录；失败仅记日志，不抛异常（审计不能拖垮主流程）。"""
    from tools.logger_tool import get_logger
    logger = get_logger("drama.audit")
    try:
        db.add(AuditLog(user_id=user_id, action=action,
                        detail=json.loads(json.dumps(detail or {}, ensure_ascii=False)),
                        ip=ip))
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.error("audit write failed | action=%s | err=%s", action, e)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
