"""Offline safety and replay tests. No credentials or AWS calls required."""
import copy
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "landing.py"
spec = importlib.util.spec_from_file_location("landing", MODULE)
landing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(landing)
CONFIG = MODULE.parents[1] / "config/dev.json"


class FakeAWS:
    def __init__(self, config):
        self.account = config["aws"]["account_id"]
        self.region = config["aws"]["region"]
        self.bucket = config["s3_landing"]["bucket"]
        self.exists = False
        self.location = self.region
        self.policy = None
        self.state = {}
        self.markers = {}
        self.writes = []

    def call(self, service, operation):
        return {"Account": self.account}

    def s3(self, operation, **kwargs):
        kwargs.pop("missing", None)
        if operation == "get-bucket-location":
            return {"LocationConstraint": self.location} if self.exists else None
        if operation == "create-bucket":
            self.exists = True
        elif operation == "get-bucket-policy":
            return self.policy
        elif operation == "get-bucket-acl":
            return {"Owner": {"ID": "owner"}, "Grants": [{"Grantee": {
                "ID": "owner", "Type": "CanonicalUser"}, "Permission": "FULL_CONTROL"}]}
        elif operation == "head-object":
            return self.markers.get(kwargs["key"])
        elif operation == "put-object":
            assert kwargs["if_none_match"] == "*"
            self.markers[kwargs["key"]] = {"ContentLength": 0}
        elif operation.startswith("get-"):
            return copy.deepcopy(self.state.get(operation))
        else:
            mapping = {
                "put-public-access-block": ("get-public-access-block", "PublicAccessBlockConfiguration", "public_access_block_configuration"),
                "put-bucket-ownership-controls": ("get-bucket-ownership-controls", "OwnershipControls", "ownership_controls"),
                "put-bucket-encryption": ("get-bucket-encryption", "ServerSideEncryptionConfiguration", "server_side_encryption_configuration"),
                "put-bucket-versioning": ("get-bucket-versioning", None, "versioning_configuration"),
                "put-bucket-tagging": ("get-bucket-tagging", None, "tagging"),
            }
            get, key, parameter = mapping[operation]
            self.state[get] = copy.deepcopy({key: kwargs[parameter]} if key else kwargs[parameter])
        self.writes.append(operation)
        return {}


class LandingTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text())
        self.aws = FakeAWS(self.config)

    def test_apply_and_repeat_preserve_roots_and_versions(self):
        first = landing.reconcile(self.config, self.aws, True)
        self.assertIn("create_bucket", first["changes"])
        self.assertEqual(set(self.aws.markers), set(landing.PREFIXES))
        writes = list(self.aws.writes)
        self.assertEqual(landing.reconcile(self.config, self.aws, True)["changes"], [])
        self.assertEqual(self.aws.writes, writes)

    def test_wrong_account_and_region_fail_without_writes(self):
        self.aws.account = "000000000000"
        with self.assertRaisesRegex(ValueError, "account"):
            landing.reconcile(self.config, self.aws, True)
        self.assertEqual(self.aws.writes, [])
        self.aws.account = self.config["aws"]["account_id"]
        self.aws.exists = True
        self.aws.location = "us-west-2"
        with self.assertRaisesRegex(ValueError, "region"):
            landing.reconcile(self.config, self.aws, True)
        self.assertEqual(self.aws.writes, [])

    def test_validation_is_read_only_and_detects_drift(self):
        landing.reconcile(self.config, self.aws, True)
        self.aws.state["get-public-access-block"]["PublicAccessBlockConfiguration"]["BlockPublicPolicy"] = False
        self.aws.writes.clear()
        with self.assertRaisesRegex(ValueError, "public_access_block"):
            landing.reconcile(self.config, self.aws, False)
        self.assertEqual(self.aws.writes, [])
        self.assertEqual(landing.reconcile(self.config, self.aws, True)["changes"], ["public_access_block"])

    def test_existing_policy_rejected_without_replacement(self):
        self.aws.exists = True
        self.aws.policy = {"Policy": "existing"}
        with self.assertRaisesRegex(ValueError, "policy"):
            landing.reconcile(self.config, self.aws, True)
        self.assertEqual(self.aws.writes, [])

    def test_nonempty_marker_is_never_overwritten(self):
        landing.reconcile(self.config, self.aws, True)
        self.aws.markers["schemas/"] = {"ContentLength": 20}
        self.aws.writes.clear()
        with self.assertRaisesRegex(ValueError, "Nonempty"):
            landing.reconcile(self.config, self.aws, True)
        self.assertEqual(self.aws.writes, [])

    def test_environment_and_conflicting_overrides(self):
        with patch.dict(os.environ, {"PMDP_ENV": "prod"}, clear=True):
            with self.assertRaisesRegex(ValueError, "PMDP_ENV"):
                landing.load_config(CONFIG)
        for variable, value in [("AWS_REGION", "us-west-2"),
                                ("PMDP_AWS_REGION", "us-west-2"),
                                ("PMDP_S3_LANDING_BUCKET", "different")]:
            with patch.dict(os.environ, {"PMDP_ENV": "dev", variable: value}, clear=True):
                with self.assertRaisesRegex(ValueError, "Conflicting"):
                    landing.load_config(CONFIG)

    def test_existing_kms_encryption_is_not_downgraded(self):
        landing.reconcile(self.config, self.aws, True)
        self.aws.state["get-bucket-encryption"]["ServerSideEncryptionConfiguration"]["Rules"][0][
            "ApplyServerSideEncryptionByDefault"] = {"SSEAlgorithm": "aws:kms"}
        self.aws.writes.clear()
        with self.assertRaisesRegex(ValueError, "encryption"):
            landing.reconcile(self.config, self.aws, True)
        self.assertEqual(self.aws.writes, [])

    def test_cli_denied_is_not_missing_and_owner_is_pinned(self):
        client = landing.AWS(self.config)
        result = subprocess.CompletedProcess([], 254, "", "An error occurred (AccessDenied): sensitive detail")
        with patch.object(landing.subprocess, "run", return_value=result) as run:
            with self.assertRaisesRegex(RuntimeError, r"get-bucket-location failed: AccessDenied$"):
                client.s3("get-bucket-location", missing=("NoSuchBucket",))
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--expected-bucket-owner") + 1], client.account)
            self.assertEqual(command[command.index("--region") + 1], client.region)


if __name__ == "__main__":
    unittest.main()
