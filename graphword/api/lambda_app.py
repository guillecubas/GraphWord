"""La misma API AWS, adaptada a las peticiones HTTPS de Lambda."""
import os

from mangum import Mangum
from graphword.api.public_security import PasswordProtectedAPI

# Validar primero la protección; la ausencia de parámetros impide arrancar.
salt = os.environ["GRAPHWORD_PASSWORD_SALT"]
expected_hash = os.environ["GRAPHWORD_PASSWORD_HASH"]
username = os.environ["GRAPHWORD_DEMO_USER"]

from graphword.api.aws_app import app

protected_app = PasswordProtectedAPI(app, username, salt, expected_hash)
handler = Mangum(protected_app, lifespan="off")
