"""认证依赖：从 Bearer 令牌解析当前用户。"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.integrations.keycloak import AuthError, decode_token, extract_user

bearer = HTTPBearer(auto_error=True)


def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(bearer),
) -> dict:
    try:
        claims = decode_token(cred.credentials)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return extract_user(claims)


def require_roles(*required: str):
    """角色守卫依赖工厂：要求用户至少具备其一。"""

    def _dep(user: dict = Depends(get_current_user)) -> dict:
        if required and not (set(required) & set(user.get("roles", []))):
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return _dep
