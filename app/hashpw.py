"""Genera el valor para APP_PASSWORD_HASH.

    docker run --rm -it nominas:local python -m app.hashpw
"""
import getpass

from app.auth import generar_hash

if __name__ == "__main__":
    p1 = getpass.getpass("Contraseña nueva: ")
    p2 = getpass.getpass("Repite la contraseña: ")
    if not p1 or p1 != p2:
        raise SystemExit("No coinciden o están vacías.")
    print("\nPega esto en APP_PASSWORD_HASH (stack de Portainer):\n")
    print(generar_hash(p1))
