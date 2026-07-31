from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.settings import settings

password_hasher = PasswordHash.recommended()


class TokenValidationError(Exception):
    """Access Token 无效、过期或缺少必要声明。"""


def hash_password(password: str) -> str:
    """使用 Argon2 对密码进行不可逆哈希。"""

    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """安全验证密码，非法哈希统一按验证失败处理。"""

    try:
        return password_hasher.verify(password, password_hash)
    except Exception:
        return False


def create_access_token(
    user_id: int,
    username: str,
) -> tuple[str, int]:
    """创建 JWT Access Token，并返回 Token 与有效秒数。"""

    issued_at = datetime.now(timezone.utc)
    expires_in = settings.jwt_access_token_expire_minutes * 60
    expires_at = issued_at + timedelta(seconds=expires_in)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": issued_at,
        "exp": expires_at,
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """校验并解析 JWT Access Token。"""

    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "iat", "exp"]},
        )
    except InvalidTokenError as exc:
        raise TokenValidationError from exc
