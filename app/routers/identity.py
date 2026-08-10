"""identity 模块：登录（ROPC）与当前用户信息。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.security import get_current_user
from app.integrations.keycloak import AuthError, password_login, register_user

router = APIRouter(prefix="/identity", tags=["identity"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str
    first_name: str | None = None
    last_name: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip()
        if not value or "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("请输入有效的邮箱地址")
        return value


@router.post("/register", status_code=201)
def register(body: RegisterRequest) -> dict:
    """开放自助注册：创建基础账户，即时可登录（未认证/游客级）。"""
    try:
        uid = register_user(
            body.username, body.password, body.email, body.first_name, body.last_name
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return {"code": 0, "message": "注册成功，请登录", "data": {"id": uid, "username": body.username}}


@router.post("/login")
def login(body: LoginRequest) -> dict:
    try:
        token = password_login(body.username, body.password)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "access_token": token["access_token"],
            "refresh_token": token.get("refresh_token"),
            "expires_in": token.get("expires_in"),
            "token_type": token.get("token_type", "Bearer"),
        },
    }


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"code": 0, "message": "ok", "data": user}
