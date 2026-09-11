"""认证接口：注册 / 登录 / 当前用户信息"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import rate_limit
from auth.deps import get_current_user
from auth.jwt import create_access_token
from auth.schemas import RegisterRequest, LoginRequest, TokenResponse
from auth.validators import validate_username, validate_password
from core.config import settings
from core.security import hash_password, verify_password
from db import crud
from db.database import get_db
from tools.logger_tool import get_logger

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = get_logger("drama.api.auth")


@router.post("/register", response_model=TokenResponse,
             dependencies=[Depends(rate_limit(settings.login_rate_limit))])
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """用户注册（限流：防批量注册；账号/密码格式白名单校验，禁止中文与特殊字符）"""
    name_err = validate_username(req.username)
    if name_err:
        raise HTTPException(status_code=400, detail=name_err)
    pwd_err = validate_password(req.password)
    if pwd_err:
        raise HTTPException(status_code=400, detail=pwd_err)
    req.username = req.username.strip()
    existing = await crud.get_user_by_username(db, req.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已被注册")
    user = await crud.create_user(db, req.username, hash_password(req.password))
    token = create_access_token(user.id, user.username)
    logger.info("user registered | id=%s | name=%s", user.id, user.username)
    return TokenResponse(access_token=token, username=user.username)


@router.post("/login", response_model=TokenResponse,
             dependencies=[Depends(rate_limit(settings.login_rate_limit))])
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录（限流：防暴力破解）"""
    user = await crud.get_user_by_username(db, req.username)
    if not user or not verify_password(req.password, user.password_hash):
        logger.warning("login failed | name=%s", req.username)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token(user.id, user.username)
    return TokenResponse(access_token=token, username=user.username)


@router.get("/me")
async def get_me(current_user=Depends(get_current_user)):
    """获取当前登录用户信息"""
    return {"id": current_user.id, "username": current_user.username}
