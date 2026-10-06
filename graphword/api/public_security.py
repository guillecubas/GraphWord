"""Contraseña de demostración para toda la API pública, incluido Swagger."""
import base64
import binascii
import hashlib
import hmac
from pathlib import Path
from urllib.parse import parse_qs

from starlette.responses import HTMLResponse, RedirectResponse, Response
from graphword.api.browser_sessions import COOKIE_NAME, SESSION_SECONDS, create_session, valid_session

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
        self.signing_key = bytes.fromhex(expected_hash)
        self.login_html = Path(__file__).with_name("public_login.html").read_text(encoding="utf-8")

    def login_page(self, status=200, message=""):
        # El mensaje es fijo: nunca insertar usuario ni contraseña en el HTML.
        return HTMLResponse(self.login_html.replace("{{message}}", message), status_code=status,
                            headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                                     "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"})

    async def login(self, scope, receive, send):
        # Limitar el formulario antes de leer o verificar la contraseña.
        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body.extend(event.get("body", b""))
            if len(body) > 8192:
                await Response("Form too large", status_code=413)(scope, receive, send)
                return
            if not event.get("more_body", False):
                break
        try:
            fields = parse_qs(body.decode("utf-8"), max_num_fields=4)
            username = fields.get("username", [""])[0]
            password = fields.get("password", [""])[0]
            header = "Basic " + base64.b64encode((username + ":" + password).encode()).decode()
            matches = self.authorized(header)
        except (ValueError, UnicodeError):
            matches = False
        if not matches:
            response = self.login_page(401, "Usuario o contraseña incorrectos.")
        else:
            response = RedirectResponse("/docs", status_code=303, headers={"Cache-Control": "no-store"})
            # Cookie firmada, solo HTTPS, no accesible a JavaScript ni otros sitios.
            response.set_cookie(COOKIE_NAME, create_session(self.signing_key),
                                max_age=SESSION_SECONDS, secure=True, httponly=True,
                                samesite="strict", path="/")
        await response(scope, receive, send)

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
        cookie = ""
        for name, value in scope.get("headers", []):
            if name.lower() == b"authorization":
                header = value.decode("latin-1")
            if name.lower() == b"cookie":
                cookie = value.decode("latin-1")
        if scope["path"] == "/login" and scope["method"] == "POST":
            await self.login(scope, receive, send)
            return
        if scope["path"] in ("/", "/login") and scope["method"] == "GET":
            await self.login_page()(scope, receive, send)
            return
        if not self.authorized(header) and not valid_session(cookie, self.signing_key):
            if scope["path"] == "/docs" and scope["method"] == "GET":
                # AWS remapea WWW-Authenticate: mostrar un formulario propio.
                response = self.login_page(401)
            else:
                response = Response("Authentication required", status_code=401,
                                    headers={"Cache-Control": "no-store"})
            response.headers["WWW-Authenticate"] = 'Basic realm="GraphWord", charset="UTF-8"'
            await response(scope, receive, send)
            return
        # Solo después de comprobar la contraseña se accede a S3/DynamoDB/SQS.
        await self.app(scope, receive, send)
