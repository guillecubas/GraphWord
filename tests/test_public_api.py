"""Seguridad de la entrada HTTPS sin credenciales ni llamadas a AWS real."""
import base64
from unittest import TestCase
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from mangum import Mangum
from graphword.api.public_security import PasswordProtectedAPI, password_hash
from scripts.despliegue.public_api import template, smoke, build_package


class PublicSecurityTests(TestCase):
    def setUp(self):
        self.password = "test-password-only-123456"
        self.salt = "ab" * 32
        app = FastAPI()

        @app.get("/health")
        def health():
            return {"status": "ok"}

        self.app = PasswordProtectedAPI(app, "graphword", self.salt,
                                        password_hash(self.password, self.salt))
        self.client = TestClient(self.app)

    def test_every_path_requires_password_including_swagger(self):
        for path in ("/health", "/docs", "/openapi.json", "/unknown"):
            response = self.client.get(path)
            self.assertEqual(401, response.status_code)
            self.assertIn("Basic", response.headers["WWW-Authenticate"])

    def test_valid_password_allows_health_and_swagger(self):
        for path in ("/health", "/docs", "/openapi.json"):
            response = self.client.get(path, auth=("graphword", self.password))
            self.assertEqual(200, response.status_code)

    def test_wrong_user_or_password_denied(self):
        for credentials in (("other", self.password), ("graphword", "wrong")):
            self.assertEqual(401, self.client.get("/health", auth=credentials).status_code)

    def test_malformed_headers_denied(self):
        for header in ("Bearer anything", "Basic !!!", "Basic /w==", "Basic YQ==", "x" * 3000):
            response = self.client.get("/health", headers={"Authorization": header})
            self.assertEqual(401, response.status_code)

    def test_missing_credentials_fail_closed(self):
        for username, salt, digest in (("", self.salt, "ab" * 32),
                                        ("graphword", "", "ab" * 32),
                                        ("graphword", self.salt, "")):
            with self.assertRaises(ValueError):
                PasswordProtectedAPI(FastAPI(), username, salt, digest)

    def test_hash_depends_on_salt(self):
        self.assertNotEqual(password_hash(self.password, self.salt),
                            password_hash(self.password, "cd" * 32))

    def test_lambda_url_event_preserves_authentication(self):
        # El adaptador traduce el evento Lambda al mismo protocolo de FastAPI.
        event = {
            "version": "2.0", "rawPath": "/health", "rawQueryString": "",
            "headers": {"host": "example.lambda-url.us-east-1.on.aws"},
            "requestContext": {"http": {"method": "GET", "path": "/health",
                                        "sourceIp": "127.0.0.1", "protocol": "HTTP/1.1"}},
            "isBase64Encoded": False,
        }
        adapter = Mangum(self.app, lifespan="off")
        self.assertEqual(401, adapter(event, None)["statusCode"])
        encoded = base64.b64encode(("graphword:" + self.password).encode()).decode()
        event["headers"]["authorization"] = "Basic " + encoded
        self.assertEqual(200, adapter(event, None)["statusCode"])


class PublicDeploymentTests(TestCase):
    def test_template_reuses_role_and_has_no_public_ec2_or_plain_password(self):
        config = {"Bucket": "bucket", "Table": "table", "QueueUrl": "queue",
                  "DictionaryCatalogKey": "catalog"}
        value = template(config, "release.zip", "existing-lab-role")
        properties = value["Resources"]["API"]["Properties"]
        self.assertEqual("existing-lab-role", properties["Role"])
        self.assertEqual(2, properties["ReservedConcurrentExecutions"])
        self.assertNotIn("VpcConfig", properties)
        self.assertTrue(value["Parameters"]["PasswordHash"]["NoEcho"])
        self.assertTrue(value["Resources"]["InvokePermission"]["Properties"]["InvokedViaFunctionUrl"])
        for resource in value["Resources"].values():
            self.assertNotIn(resource["Type"], ("AWS::IAM::Role", "AWS::EC2::SecurityGroup"))

    def test_smoke_rejects_an_unprotected_endpoint(self):
        with patch("scripts.despliegue.public_api.request", return_value=(200, b"{}")):
            with self.assertRaisesRegex(RuntimeError, "Unauthenticated"):
                smoke("https://example/", "test-only-password")

    def test_windows_package_is_rejected_before_install(self):
        with patch("scripts.despliegue.public_api.sys.platform", "win32"):
            with self.assertRaisesRegex(RuntimeError, "Linux"):
                build_package("unused.zip")
