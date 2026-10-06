"""Sesiones cortas firmadas; el navegador no guarda la contraseña."""
import hashlib
import hmac
from http.cookies import CookieError, SimpleCookie
import time

COOKIE_NAME = "__Host-graphword-session"
SESSION_SECONDS = 7200


def create_session(signing_key):
    expires = str(int(time.time()) + SESSION_SECONDS)
    signature = hmac.new(signing_key, expires.encode(), hashlib.sha256).hexdigest()
    return expires + "." + signature


def valid_session(cookie_header, signing_key):
    if len(cookie_header) > 4096:
        return False
    try:
        cookies = SimpleCookie()
        cookies.load(cookie_header)
        if COOKIE_NAME not in cookies:
            return False
        expires, signature = cookies[COOKIE_NAME].value.split(".", 1)
        remaining = int(expires) - int(time.time())
        if remaining <= 0 or remaining > SESSION_SECONDS:
            return False
    except (ValueError, CookieError):
        return False
    expected = hmac.new(signing_key, expires.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.encode(), expected.encode())
