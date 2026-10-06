from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class MobileProfileKeyError(ValueError):
    pass


def decode_rsa_public_key(public_key_b64: str) -> tuple[rsa.RSAPublicKey, bytes]:
    try:
        der = base64.b64decode(public_key_b64, validate=True)
        key = serialization.load_der_public_key(der)
    except (ValueError, TypeError) as exc:
        raise MobileProfileKeyError("모바일 기기 공개키를 해석하지 못했습니다.") from exc
    if not isinstance(key, rsa.RSAPublicKey):
        raise MobileProfileKeyError("모바일 기기 키는 RSA 공개키여야 합니다.")
    if key.key_size < 2048:
        raise MobileProfileKeyError("모바일 기기 RSA 키는 2048비트 이상이어야 합니다.")
    return key, der


def public_key_verification_code(public_key_b64: str) -> str:
    _, der = decode_rsa_public_key(public_key_b64)
    number = int.from_bytes(hashlib.sha256(der).digest()[:4], "big") % 1_000_000
    return f"{number:06d}"


def encrypt_profile_token(public_key_b64: str, token: str) -> str:
    key, _ = decode_rsa_public_key(public_key_b64)
    encrypted = key.encrypt(
        token.encode("utf-8"),
        padding.OAEP(
            # Android Keystore's OAEPWithSHA-256 implementation uses SHA-1 for MGF1
            # on the API levels supported by the companion app.
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(encrypted).decode("ascii")
