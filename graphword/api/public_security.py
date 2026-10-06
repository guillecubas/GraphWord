"""Contraseña de demostración para toda la API pública, incluido Swagger."""
import base64
import binascii
import hashlib
import hmac

from starlette.responses import Response

ITERATIONS = 200_000


def password_hash(password, salt):
    # Guardar una derivación de la contraseña, no su texto original.
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS
    ).hex()


class PasswordProtectedAPI:
    def __init__(self, app, username, salt, expected_hash):
        # No arrancar una API pública si falta la protección.
        if not username or len(salt) != 64 or len(expected_hash) != 64:
            raise ValueError("Public authentication is not configured")
        bytes.fromhex(salt)
        bytes.fromhex(expected_hash)
        self.app = app
        self.username = username
        self.salt = salt
        self.expected_hash = expected_hash

    def authorized(self, header):
        if len(header) > 2048:
            return False
        try:
            scheme, value = header.split(" ", 1)
            if scheme.lower() != "basic":
                return False
            decoded = base64.b64decode(value, validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeError, binascii.Error):
            return False
        actual_hash = password_hash(password, self.salt)
        user_matches = hmac.compare_digest(username.encode(), self.username.encode())
        password_matches = hmac.compare_digest(actual_hash, self.expected_hash)
        return user_matches and password_matches

    async def __call__(self, scope, receive, send):
        # El ciclo de vida ASGI no es una petición del navegador.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header = ""
        for name, value in scope.get("headers", []):
            if name.lower() == b"authorization":
                header = value.decode("latin-1")
                break
        if not self.authorized(header):
            response = Response(
                "Authentication required", status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="GraphWord", charset="UTF-8"',
                         "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        # Solo después de comprobar la contraseña se accede a S3/DynamoDB/SQS.
        await self.app(scope, receive, send)
