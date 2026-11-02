"""Login de un solo usuario.

La contraseña se guarda como hash scrypt en la variable APP_PASSWORD_HASH.
Formato: scrypt:<n>:<r>:<p>:<sal_hex>:<hash_hex>   (sin '$', para que
docker compose no intente interpolarlo).

Generar el hash:   docker exec -it nominas python -m app.hashpw
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets


def generar_hash(password: str) -> str:
    n, r, p = 2**14, 8, 1
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=sal, n=n, r=r, p=p, dklen=32)
    return f"scrypt:{n}:{r}:{p}:{sal.hex()}:{h.hex()}"


def verificar(password: str, guardado: str) -> bool:
    try:
        alg, n, r, p, sal, h = guardado.split(":")
        if alg != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(sal),
                              n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(h)))
        return hmac.compare_digest(calc, bytes.fromhex(h))
    except (ValueError, TypeError):
        return False


def configurado() -> bool:
    return bool(os.environ.get("APP_USER") and os.environ.get("APP_PASSWORD_HASH"))


def comprobar_credenciales(usuario: str, password: str) -> bool:
    if not configurado():
        return False
    ok_user = hmac.compare_digest(usuario.encode(), os.environ["APP_USER"].encode())
    ok_pass = verificar(password, os.environ["APP_PASSWORD_HASH"])
    return ok_user and ok_pass
