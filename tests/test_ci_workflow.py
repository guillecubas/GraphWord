"""Comprobar que el CI público solo ejecuta pruebas y no tiene acceso a AWS."""
from pathlib import Path
from unittest import TestCase


class WorkflowConfigurationTests(TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    def test_tests_do_not_reference_aws_secrets(self):
        # Las pruebas simulan AWS: no necesitan las claves reales del laboratorio.
        self.assertNotIn("secrets.AWS_", self.workflow)
        self.assertNotIn("configure-aws-credentials", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)

    def test_both_python_versions_are_tested(self):
        # El controlador privado exige los resultados de estas dos versiones.
        self.assertIn("python-version: ['3.11', '3.12']", self.workflow)
        self.assertIn('python -m pip install -e ".[test,aws,aws-test]"', self.workflow)

    def test_test_output_keeps_failure_status_and_artifacts(self):
        # Guardar la salida con tee no debe ocultar el fallo de las pruebas.
        self.assertIn("set -o pipefail", self.workflow)
        self.assertIn("tee test-results/unittest.txt", self.workflow)
        self.assertIn("if: always()", self.workflow)
        self.assertIn("path: test-results/", self.workflow)

    def test_public_repository_never_runs_the_aws_deployment(self):
        # Mantener el runner y el despliegue fuera del alcance de las pull requests.
        self.assertNotIn("runs-on: [self-hosted", self.workflow)
        self.assertNotIn("\n  deploy:", self.workflow)
        self.assertNotIn("python scripts/despliegue/ci_deploy.py", self.workflow)
        self.assertIn("runs-on: ubuntu-22.04", self.workflow)
