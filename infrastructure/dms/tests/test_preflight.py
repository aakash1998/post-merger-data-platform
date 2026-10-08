"""Preflight safety tests; no AWS calls or credentials."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "preflight.py"
SPEC = importlib.util.spec_from_file_location("preflight", MODULE)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)
CONFIG = MODULE.parents[1] / "config/dev.json"


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text())
        self.aws = preflight.ReadOnlyAWS(self.config)

    def test_mutations_cannot_reach_cli(self):
        with patch.object(preflight.IAM.landing.subprocess, "run") as run:
            for service, operation in (("dms", "create-replication-instance"),
                                       ("ec2", "create-nat-gateway"), ("freetier", "upgrade-account-plan"),
                                       ("iam", "create-role"), ("s3api", "put-object")):
                with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "Read-only"):
                    self.aws.call(service, operation)
            run.assert_not_called()

    def test_wrong_account_stops_before_discovery(self):
        with patch.object(self.aws, "call", return_value={"Account": "000000000000"}) as call:
            with self.assertRaisesRegex(ValueError, "STS account mismatch"):
                preflight.collect(self.config, self.aws)
            self.assertEqual(call.call_count, 1)

    def test_denial_is_reported_and_independent_reads_continue(self):
        account = self.config["aws"]["account_id"]
        trust, policy = preflight.IAM.documents(self.config)
        def response(service, operation, **kwargs):
            if service == "sts":
                return {"Account": account, "Arn": f"arn:aws:iam::{account}:role/operator"}
            if service == "dms":
                raise RuntimeError(f"dms.{operation} failed: AccessDeniedException")
            if service == "freetier":
                return {"accountPlanType": "FREE", "accountPlanStatus": "ACTIVE"}
            if operation == "get-role-policy":
                return {"PolicyDocument": policy}
            if operation == "get-role":
                return None
            if operation == "describe-vpcs":
                return {"Vpcs": []}
            return {}
        with patch.object(self.aws, "call", side_effect=response) as call, \
             patch.object(preflight.IAM.landing, "reconcile", return_value={}), \
             patch.object(preflight.IAM, "inspect_role", return_value={"AssumeRolePolicyDocument": trust}):
            report = preflight.collect(self.config, self.aws)
        self.assertEqual(report["validation"], "blocked")
        self.assertIn("dms_options", report["blockers"])
        self.assertIn("dms_inventory", report["blockers"])
        self.assertEqual(report["aws_mutations"], [])
        self.assertIn("vpc_endpoint_inventory", report["checks"])
        self.assertFalse(any(op.args[1].startswith("create-") for op in call.call_args_list))

    def test_aws_access_denied_is_not_treated_as_missing(self):
        result = subprocess.CompletedProcess([], 254, "", "An error occurred (AccessDeniedException): private principal details")
        with patch.object(preflight.IAM.landing.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "failed: AccessDeniedException$"):
                self.aws.call("iam", "get-role", role_name="dms-vpc-role", missing=("NoSuchEntity",))


if __name__ == "__main__":
    unittest.main()
