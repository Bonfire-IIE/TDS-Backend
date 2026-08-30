"""Keycloak 集成：ROPC 直连授权登录 + JWT 验签（JWKS）。

MVP 采用后端代理直连授权（direct access grant）：前端提交账号口令 -> 后端向
Keycloak token 端点换取真实 JWT -> 返回前端。令牌校验用 realm JWKS 验签。
生产升级为 Authorization Code + PKCE（见 design/backend-design.md）。
"""
from __future__ import annotations

from functools import lru_cache

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import settings


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401, code: str = "AUTH_FAILED", diagnostic: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.diagnostic = diagnostic


def _keycloak_failure(action: str, response: httpx.Response) -> AuthError:
    # 上游正文可能带 realm/client 信息，只进入服务端诊断，不回传浏览器。
    diagnostic = f"status={response.status_code} body={response.text[:500]}"
    if response.status_code in (401, 403):
        return AuthError(f"身份服务拒绝{action}，请检查客户端配置", 502, "IDENTITY_CLIENT_REJECTED", diagnostic)
    return AuthError(f"身份服务暂时无法完成{action}", 502, "IDENTITY_UPSTREAM_ERROR", diagnostic)


@lru_cache
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(f"{settings.keycloak_realm_url}/protocol/openid-connect/certs")


def password_login(username: str, password: str) -> dict:
    """ROPC：用账号口令换取令牌。返回 Keycloak token 响应。"""
    token_url = f"{settings.keycloak_realm_url}/protocol/openid-connect/token"
    data = {
        "grant_type": "password",
        "client_id": settings.keycloak_client_id,
        "client_secret": settings.keycloak_client_secret,
        "username": username,
        "password": password,
        "scope": "openid profile email",
    }
    try:
        with httpx.Client(timeout=10.0, trust_env=False) as c:
            resp = c.post(token_url, data=data)
    except httpx.TimeoutException as exc:
        raise AuthError("身份服务响应超时，请稍后重试", 503, "IDENTITY_TIMEOUT", repr(exc)) from exc
    except httpx.HTTPError as exc:
        raise AuthError("无法连接身份服务", 503, "IDENTITY_UNREACHABLE", repr(exc)) from exc
    if resp.status_code == 401:
        raise AuthError("用户名或密码错误")
    if resp.status_code != 200:
        raise _keycloak_failure("登录", resp)
    return resp.json()


def _admin_token() -> str:
    """服务账号 client_credentials 取 Admin API 令牌。"""
    token_url = f"{settings.keycloak_realm_url}/protocol/openid-connect/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.keycloak_admin_client_id,
        "client_secret": settings.keycloak_admin_client_secret,
    }
    try:
        with httpx.Client(timeout=10.0, trust_env=False) as c:
            resp = c.post(token_url, data=data)
    except httpx.TimeoutException as exc:
        raise AuthError("身份服务响应超时，请稍后重试", 503, "IDENTITY_TIMEOUT", repr(exc)) from exc
    except httpx.HTTPError as exc:
        raise AuthError("无法连接身份服务", 503, "IDENTITY_UNREACHABLE", repr(exc)) from exc
    if resp.status_code != 200:
        raise _keycloak_failure("用户管理认证", resp)
    return resp.json()["access_token"]


def register_user(
    username: str, password: str, email: str,
    first_name: str | None = None, last_name: str | None = None,
) -> str:
    """经 Admin API 开放注册：创建即时可登录的基础账户（不带交易角色）。

    返回新用户 id。用户名/邮箱已存在则抛 AuthError(409)。
    """
    admin_url = f"{settings.keycloak_base_url}/admin/realms/{settings.keycloak_realm}/users"
    payload = {
        "username": username,
        "enabled": True,
        "email": email,
        "firstName": first_name,
        "lastName": last_name,
        "emailVerified": True,
        "credentials": [{"type": "password", "value": password, "temporary": False}],
        # 认证状态：注册即未认证（游客级），实名/机构认证由平台运营方审批后置 true
        "attributes": {"verified": ["false"]},
    }
    headers = {"Authorization": f"Bearer {_admin_token()}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=10.0, trust_env=False) as c:
            resp = c.post(admin_url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise AuthError("身份服务响应超时，请稍后重试", 503, "IDENTITY_TIMEOUT", repr(exc)) from exc
    except httpx.HTTPError as exc:
        raise AuthError("无法连接身份服务", 503, "IDENTITY_UNREACHABLE", repr(exc)) from exc
    if resp.status_code == 409:
        raise AuthError("用户名或邮箱已存在", status_code=409)
    if resp.status_code not in (201, 204):
        raise _keycloak_failure("用户注册", resp)
    return resp.headers.get("Location", "").rsplit("/", 1)[-1]


def decode_token(token: str) -> dict:
    """用 JWKS 验签并解析访问令牌，返回 claims。"""
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.keycloak_realm_url,
            # Keycloak 访问令牌 aud 通常为 account，这里不强校验 aud
            options={"verify_aud": False},
        )
        return claims
    except jwt.ExpiredSignatureError as e:
        raise AuthError("令牌已过期") from e
    except jwt.InvalidTokenError as e:
        raise AuthError(f"无效令牌: {e}") from e


def extract_user(claims: dict) -> dict:
    """从 claims 提取用户信息与角色。"""
    return {
        "username": claims.get("preferred_username"),
        "email": claims.get("email"),
        "name": claims.get("name"),
        # 账户级角色（operator/supervisor）；过滤 Keycloak 内置默认角色；交易角色不在此（属合约上下文）
        "roles": [
            r
            for r in claims.get("realm_access", {}).get("roles", [])
            if not r.startswith("default-roles-") and r not in ("offline_access", "uma_authorization")
        ],
        # 认证状态：未认证=游客级。token 携带需在“认证审批”环节加 attribute mapper，暂默认 false
        "verified": str(claims.get("verified", "false")).lower() == "true",
        "sub": claims.get("sub"),
    }
