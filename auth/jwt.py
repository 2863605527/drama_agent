from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from core.config import settings


def create_access_token(user_id: int, username: str, token_version: int = 0,
                        expires_delta: Optional[timedelta] = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    # P0：ver=token_version，吊销机制——改密/封号/退出所有设备后版本号 +1，旧 token 立即失效
    payload = {"sub": str(user_id), "username": username, "ver": token_version, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
