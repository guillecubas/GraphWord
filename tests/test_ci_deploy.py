# Pruebas del despliegue con servicios simulados; no crean recursos AWS.
import json
from unittest import TestCase, skipIf
from unittest.mock import Mock, call, patch

try:
    from scripts.despliegue import ci_deploy
except ImportError:
    ci_deploy = None


@skipIf(ci_deploy is None, "install .[aws]")
class PipelineTests(TestCase):
    def test_reused_metadata_is_rejected(self):
        with patch.object(ci_deploy.Path, "exists", return_value=True), patch.object(ci_deploy, "run") as run:
            with self.assertRaises(RuntimeError):
                ci_deploy.main()
            run.assert_not_called()

    def test_ready_pipeline_smokes_then_stops(self):
        config = {"region": "us-east-1", "ApiNode": "a", "WorkerNode": "b"}
        ssm = Mock()
        # Simular que los dos nodos ya están preparados en SSM.
        instances = []
        for node in ("a", "b"):
            instances.append({"InstanceId": node, "PingStatus": "Online"})
        ssm.describe_instance_information.return_value = {"InstanceInformationList": instances}
        with (
            patch.object(ci_deploy.Path, "exists", side_effect=[False, True]),
            patch.object(ci_deploy.Path, "read_text", return_value=json.dumps(config)),
            patch.object(ci_deploy.boto3, "client", return_value=ssm),
            patch.object(ci_deploy, "run") as run,
        ):
            ci_deploy.main()
        self.assertEqual([call("despliegue/deploy_aws.py"), call("operaciones/aws_operations.py", "start"),
                          call("operaciones/aws_operations.py", "status"), call("operaciones/aws_operations.py", "smoke"),
                          call("operaciones/aws_operations.py", "stop")], run.call_args_list)

    def test_start_failure_still_requests_stop(self):
        with (
            patch.object(ci_deploy.Path, "exists", side_effect=[False, True]),
            patch.object(ci_deploy, "run", side_effect=[None, RuntimeError("start failed"), None]) as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "start failed"):
                ci_deploy.main()
        self.assertEqual(call("operaciones/aws_operations.py", "stop"), run.call_args)

    def test_failed_deploy_without_metadata_does_not_guess_nodes(self):
        with (
            patch.object(ci_deploy.Path, "exists", side_effect=[False, False]),
            patch.object(ci_deploy, "run", side_effect=RuntimeError("deploy failed")) as run,
        ):
            with self.assertRaises(RuntimeError):
                ci_deploy.main()
        run.assert_called_once_with("despliegue/deploy_aws.py")
