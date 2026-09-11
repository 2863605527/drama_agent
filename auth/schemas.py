from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=20, description="用户名：字母开头，仅字母/数字/下划线")
    password: str = Field(..., min_length=6, max_length=20, description="密码：仅字母/数字")


class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
