import io
import json
import unittest
import zipfile

try:
    from scripts.deploy_aws import build_release, compute_template, ROOT
except ImportError:
    build_release = None


@unittest.skipIf(build_release is None, "install .[aws]")
class DeploymentTests(unittest.TestCase):
    def test_release_is_deterministic_readable_and_allowlisted(self):
        content = build_release({"Bucket": "test"})
        self.assertEqual(content, build_release({"Bucket": "test"}))
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for item in archive.infolist():
                self.assertEqual(0o644, (item.external_attr >> 16) & 0o777)
                self.assertTrue(item.filename.startswith(("graphword/", "scripts/")) or
                                item.filename in ("pyproject.toml", "deployment.json"))
                self.assertNotIn(".env", item.filename)
                self.assertNotIn(".aws", item.filename)

    def test_compute_has_two_nodes_no_ingress_and_imdsv2(self):
        template = compute_template("vpc-test", "subnet-test", "ami-test", "bucket", "releases/a.zip", "LabInstanceProfile")
        resources = template["Resources"]
        self.assertNotIn("SecurityGroupIngress", resources["SecurityGroup"]["Properties"])
        nodes = [item["Properties"] for item in resources.values() if item["Type"] == "AWS::EC2::Instance"]
        self.assertEqual(2, len(nodes))
        self.assertTrue(all(item["MetadataOptions"]["HttpTokens"] == "required" for item in nodes))

    def test_new_artifact_replaces_nodes_but_same_artifact_does_not(self):
        args = ("vpc", "subnet", "ami", "bucket")
        first = compute_template(*args, "a.zip", "LabInstanceProfile")
        self.assertEqual(first, compute_template(*args, "a.zip", "LabInstanceProfile"))
        second = compute_template(*args, "b.zip", "LabInstanceProfile")
        self.assertNotEqual(first["Outputs"], second["Outputs"])

    def test_durable_storage_is_retained_and_private(self):
        resources = json.loads((ROOT / "infra/storage.json").read_text())["Resources"]
        self.assertEqual("Retain", resources["Objects"]["DeletionPolicy"])
        self.assertEqual("Retain", resources["Jobs"]["DeletionPolicy"])
        self.assertTrue(all(resources["Objects"]["Properties"]["PublicAccessBlockConfiguration"].values()))
