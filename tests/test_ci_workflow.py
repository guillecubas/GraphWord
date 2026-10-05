"""Comprobar la configuración esperada de CI/CD, sin conectarse a GitHub o AWS."""
from pathlib import Path
from unittest import TestCase


class WorkflowConfigurationTests(TestCase):
    def setUp(self):
        # Separar los trabajos según su nombre en el archivo del workflow.
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.tests_job, self.deploy_job = workflow.split("\n  deploy:", 1)

    def test_tests_job_does_not_reference_aws_secrets(self):
        # Las pruebas simulan AWS: no necesitan las claves reales del laboratorio.
        self.assertNotIn("secrets.AWS_", self.tests_job)
        self.assertIn("python -m unittest discover -s tests -v", self.tests_job)

    def test_deploy_requires_tests_and_authorized_branch(self):
        # No desplegar código de una pull request ni de otro repositorio o rama.
        self.assertIn("needs: test", self.deploy_job)
        self.assertIn("github.repository == 'guillecubas/GraphWord'", self.deploy_job)
        self.assertIn("github.ref == 'refs/heads/refactor/python-distributed'", self.deploy_job)
        self.assertIn("github.event_name != 'pull_request'", self.deploy_job)
        self.assertIn("vars.ENABLE_AWS_DEPLOY == 'true'", self.deploy_job)
        self.assertIn("vars.AWS_ACCOUNT_ID != ''", self.deploy_job)

    def test_deploy_uses_all_three_temporary_secrets_without_oidc(self):
        # Las tres referencias deben existir; los valores no pertenecen al código.
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
            self.assertIn("secrets." + name, self.deploy_job)
        self.assertIn("allowed-account-ids: ${{ vars.AWS_ACCOUNT_ID }}", self.deploy_job)
        self.assertIn("force-skip-oidc: true", self.deploy_job)
        self.assertNotIn("role-to-assume:", self.deploy_job)
        self.assertNotIn("id-token: write", self.deploy_job)

    def test_missing_secrets_are_checked_before_authentication_and_deployment(self):
        check = self.deploy_job.index("name: Check temporary lab secrets")
        authenticate = self.deploy_job.index("name: Authenticate with temporary lab credentials")
        deploy = self.deploy_job.index("python scripts/despliegue/ci_deploy.py")
        self.assertLess(check, authenticate)
        self.assertLess(authenticate, deploy)
        self.assertIn('echo "::error::Configura los tres Secrets temporales', self.deploy_job)
        self.assertIn("exit 1", self.deploy_job)
        # Los artefactos contienen evidencias, no archivos de credenciales.
        self.assertIn("path: var/aws-*.json", self.deploy_job)
