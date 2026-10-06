"""Comprobar la plantilla del runner sin crear recursos en AWS."""
import base64
from unittest import TestCase
from unittest.mock import Mock

from scripts.despliegue import setup_lab_runner


class LabRunnerTests(TestCase):
    def test_separate_runner_has_lab_profile_no_ingress_and_encryption(self):
        template = setup_lab_runner.runner_template("vpc", "subnet", "ami", "/dev/sda1")
        resources = template["Resources"]
        self.assertEqual({"SecurityGroup", "Runner"}, set(resources))
        self.assertNotIn("SecurityGroupIngress", resources["SecurityGroup"]["Properties"])
        runner = resources["Runner"]["Properties"]
        self.assertEqual("t3.micro", runner["InstanceType"])
        self.assertEqual("LabInstanceProfile", runner["IamInstanceProfile"])
        self.assertEqual("required", runner["MetadataOptions"]["HttpTokens"])
        self.assertTrue(runner["BlockDeviceMappings"][0]["Ebs"]["Encrypted"])
        self.assertEqual(12, runner["BlockDeviceMappings"][0]["Ebs"]["VolumeSize"])

    def test_bootstrap_verifies_official_download_without_tokens(self):
        template = setup_lab_runner.runner_template("vpc", "subnet", "ami", "/dev/sda1")
        script = base64.b64decode(template["Resources"]["Runner"]["Properties"]["UserData"]).decode()
        self.assertIn(setup_lab_runner.RUNNER_URL, script)
        self.assertIn(setup_lab_runner.RUNNER_SHA256, script)
        self.assertIn("sha256sum --check", script)
        self.assertNotIn("--token", script)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", script)
        self.assertNotIn("config.sh --url", script)

    def test_subnet_requires_active_internet_gateway_not_nat_or_blackhole(self):
        for gateway, state, expected in (("igw-123", "active", True),
                                          ("nat-123", "active", False),
                                          ("igw-123", "blackhole", False)):
            ec2 = Mock()
            ec2.describe_route_tables.return_value = {"RouteTables": [{"Routes": [{
                "DestinationCidrBlock": "0.0.0.0/0", "GatewayId": gateway, "State": state,
            }]}]}
            with self.subTest(gateway=gateway, state=state):
                self.assertEqual(expected, setup_lab_runner.subnet_is_public(ec2, "vpc", "subnet"))

    def test_existing_runner_stack_is_not_updated_or_replaced(self):
        cf = Mock()
        cf.describe_stacks.return_value = {"Stacks": [{
            "StackStatus": "CREATE_COMPLETE", "Tags": [{"Key": "Project", "Value": "GraphWord"}],
            "Outputs": [{"OutputKey": "RunnerNode", "OutputValue": "i-runner"}],
        }]}
        self.assertEqual("i-runner", setup_lab_runner.create_runner(cf, {}))
        cf.create_stack.assert_not_called()
        cf.update_stack.assert_not_called()

    def test_existing_foreign_stack_is_rejected(self):
        cf = Mock()
        cf.describe_stacks.return_value = {"Stacks": [{"Tags": [], "StackStatus": "CREATE_COMPLETE"}]}
        with self.assertRaises(RuntimeError):
            setup_lab_runner.create_runner(cf, {})
        cf.create_stack.assert_not_called()

    def test_wrong_account_stops_before_resource_queries(self):
        session = Mock()
        session.client.return_value.get_caller_identity.return_value = {"Account": "other"}
        with self.assertRaises(RuntimeError):
            setup_lab_runner.check_environment(session, "123")
        session.client.assert_called_once_with("sts")
