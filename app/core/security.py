"""비밀번호 해싱.

bcrypt 는 72바이트를 넘는 입력을 잘라내거나 거부하므로,
Django 의 bcrypt_sha256 과 같은 방식으로 sha256 을 먼저 씌워 길이를 고정한다.
"""

from __future__ import annotations

import base64
import hashlib

import bcrypt


def _prehash(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)  # 44바이트 -> bcrypt 한계 안쪽


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False
