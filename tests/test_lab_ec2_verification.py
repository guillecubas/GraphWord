"""Pruebas de las comprobaciones EC2, sin consultar ni cambiar AWS real."""
import json
from pathlib import Path
import subprocess
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts.despliegue import verify_lab_ec2


def instance(instance_id, stack):
    return {
        "InstanceId": instance_id,
        "Tags": [{"Key": "aws:cloudformation:stack-name", "Value": stack}],
    }


def reservations(instances):
    return {"Reservations": [{"Instances": instances}]}


class EC2VerificationTests(TestCase):
    def setUp(self):
        self.identity = {
            "Account": "123",
            "Arn": "arn:aws:sts::123:assumed-role/LabRole/i-runner",
        }
        self.runner = reservations([instance("i-runner", "graphword-cd-runner")])
        self.nodes = reservations([
            instance("i-api", "graphword-compute"),
            instance("i-worker", "graphword-compute"),
        ])
        self.config = {
            "account": "123", "region": "us-east-1",
            "ApiNode": "i-api", "WorkerNode": "i-worker",
        }

    def run_main(self, responses, config=None, environment=None):
        # Simular AWS y el fichero de resultados; nunca ejecutar comandos reales.
        arguments = ["verify_lab_ec2.py"]
        if config is not None:
            arguments.extend(["--stopped-metadata", "metadata.json"])
        variables = {"AWS_ACCOUNT_ID": "123"}
        if environment:
            variables.update(environment)
        with patch.dict(verify_lab_ec2.os.environ, variables, clear=True):
            with patch("sys.argv", arguments):
                with patch.object(Path, "read_text", return_value=json.dumps(config)):
                    with patch.object(verify_lab_ec2, "aws", side_effect=responses) as aws:
                        verify_lab_ec2.main()
        return aws

    def test_ec2_labrole_is_accepted(self):
        verify_lab_ec2.verify_identity(self.identity, "123")

    def test_wrong_account_and_non_ec2_roles_are_rejected(self):
        with self.assertRaises(RuntimeError):
            verify_lab_ec2.verify_identity(self.identity, "other")
        for arn in (
            "arn:aws:sts::123:assumed-role/voclabs/user",
            "arn:aws:iam::123:user/test",
            "arn:aws:sts::123:assumed-role/LabRole/not-an-instance",
        ):
            with self.subTest(arn=arn):
                with self.assertRaises(RuntimeError):
                    verify_lab_ec2.verify_identity({"Account": "123", "Arn": arn}, "123")

    def test_aws_command_parses_json_and_keeps_arguments_separate(self):
        result = Mock(stdout='{"Account":"123"}')
        with patch.object(verify_lab_ec2.subprocess, "run", return_value=result) as run:
            self.assertEqual({"Account": "123"}, verify_lab_ec2.aws("sts", "get-caller-identity"))
        run.assert_called_once_with(
            ["aws", "sts", "get-caller-identity", "--region", "us-east-1", "--output", "json"],
            check=True, capture_output=True, text=True,
        )

    def test_external_credentials_are_rejected_before_aws_queries(self):
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN", "AWS_WEB_IDENTITY_TOKEN_FILE"):
            with self.subTest(variable=name):
                with self.assertRaises(RuntimeError):
                    self.run_main([], environment={name: "not-a-real-credential"})

    def test_foreign_runner_stack_is_rejected(self):
        runner = reservations([instance("i-runner", "unrelated-stack")])
        with self.assertRaises(RuntimeError):
            self.run_main([self.identity, runner])

    def test_identity_check_does_not_wait_for_application_nodes(self):
        aws = self.run_main([self.identity, self.runner])
        self.assertEqual(2, aws.call_count)

    def test_both_owned_nodes_are_waited_until_stopped(self):
        aws = self.run_main([self.identity, self.runner, self.nodes, None], self.config)
        aws.assert_called_with("ec2", "wait", "instance-stopped", "--instance-ids", "i-api", "i-worker")

    def test_wrong_account_region_duplicate_nodes_or_runner_target_is_rejected(self):
        changes = (
            {"account": "other"}, {"region": "us-west-2"},
            {"ApiNode": "i-worker"}, {"ApiNode": "i-runner"},
        )
        for change in changes:
            config = self.config.copy()
            config.update(change)
            with self.subTest(change=change):
                with self.assertRaises(RuntimeError):
                    self.run_main([self.identity, self.runner], config)

    def test_foreign_or_incomplete_application_nodes_are_rejected(self):
        responses = (
            reservations([instance("i-api", "another-stack"), instance("i-worker", "graphword-compute")]),
            reservations([instance("i-api", "graphword-compute")]),
        )
        for nodes in responses:
            with self.subTest(nodes=nodes):
                with self.assertRaises(RuntimeError):
                    self.run_main([self.identity, self.runner, nodes], self.config)

    def test_failed_stop_waiter_is_not_reported_as_success(self):
        failure = subprocess.CalledProcessError(255, ["aws", "ec2", "wait"])
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_main([self.identity, self.runner, self.nodes, failure], self.config)
