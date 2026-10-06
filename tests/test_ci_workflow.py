"""Comprobar la separación de permisos entre pruebas y despliegue privado."""
from pathlib import Path
from unittest import TestCase


class WorkflowConfigurationTests(TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.test_job, self.deploy_job = self.workflow.split("\n  deploy:", 1)

    def test_tests_do_not_reference_aws_secrets(self):
        # Las pruebas simulan AWS: no necesitan las claves reales del laboratorio.
        self.assertNotIn("secrets.AWS_", self.workflow)
        self.assertNotIn("self-hosted", self.test_job)
        self.assertNotIn("AWS_ACCOUNT_ID:", self.test_job)
        self.assertNotIn("configure-aws-credentials", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)

    def test_both_python_versions_are_tested(self):
        # El despliegue espera a que las dos versiones aprueben las pruebas.
        self.assertIn("python-version: ['3.11', '3.12']", self.workflow)
        self.assertIn('python -m pip install -e ".[test,aws,aws-test,public]"', self.workflow)

    def test_test_output_keeps_failure_status_and_artifacts(self):
        # Guardar la salida con tee no debe ocultar el fallo de las pruebas.
        self.assertIn("set -o pipefail", self.workflow)
        self.assertIn("tee test-results/unittest.txt", self.workflow)
        self.assertIn("if: always()", self.workflow)
        self.assertIn("path: test-results/", self.workflow)

    def test_deployment_requires_private_repository_and_successful_ci(self):
        # Un cambio de visibilidad no debe activar un despliegue público.
        self.assertIn("needs: test", self.deploy_job)
        self.assertIn("needs.test.result == 'success'", self.deploy_job)
        self.assertIn("github.event.repository.private == true", self.deploy_job)
        self.assertIn("github.repository == 'guillecubas/GraphWord'", self.deploy_job)
        self.assertIn("github.ref == 'refs/heads/refactor/python-distributed'", self.deploy_job)
        self.assertIn("vars.ENABLE_LAB_CD == 'true'", self.deploy_job)

    def test_pull_requests_never_deploy_and_manual_deployment_is_explicit(self):
        # Solo admitir push autorizado o una petición manual marcada deploy.
        self.assertIn("github.event_name == 'push'", self.deploy_job)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.deploy", self.deploy_job)
        self.assertNotIn("github.event_name == 'pull_request'", self.deploy_job)
        self.assertIn("default: false", self.test_job)

    def test_runner_uses_exact_tested_revision_role_and_stop_verification(self):
        self.assertIn("ref: ${{ github.sha }}", self.deploy_job)
        self.assertIn("persist-credentials: false", self.deploy_job)
        self.assertIn("AWS_SHARED_CREDENTIALS_FILE: /dev/null", self.deploy_job)
        self.assertIn("AWS_CONFIG_FILE: /dev/null", self.deploy_job)
        self.assertIn("runs-on: [self-hosted, linux, x64, graphword-lab]", self.deploy_job)
        self.assertIn("--stopped-metadata var/aws-deployment.json", self.deploy_job)
        self.assertIn("cancel-in-progress: false", self.test_job)

    def test_public_password_is_only_in_deployment_step(self):
        self.assertNotIn("GRAPHWORD_DEMO_PASSWORD", self.test_job)
        self.assertIn("secrets.GRAPHWORD_DEMO_PASSWORD", self.deploy_job)
        root = Path(__file__).resolve().parents[1]
        public = (root / ".github/workflows/public-api.yml").read_text()
        self.assertIn("needs: test", public)
        self.assertIn("github.event.repository.private == true", public)
        self.assertIn("github.ref == 'refs/heads/refactor/python-distributed'", public)
        self.assertIn("options: [deploy, pause]", public)
        self.assertIn("group: graphword-ci-cd", public)
