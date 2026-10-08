"""Offline IAM safety tests; no AWS credentials required."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "dms_s3.py"
spec = importlib.util.spec_from_file_location("dms_s3", MODULE)
iam = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iam)
CONFIG = MODULE.parents[1] / "config/dev.json"


class FakeAWS:
    def __init__(self, config):
        self.account = config["aws"]["account_id"]
        self.region = config["aws"]["region"]
        self.bucket = config["s3_landing"]["bucket"]
        self.role = None
        self.policy = None
        self.attached = []
        self.extra_inline = []
        self.writes = []
        self.other = []
        self.findings = []

    def call(self, service, operation, **kwargs):
        if operation == "get-caller-identity":
            return {"Account": self.account, "Arn": f"arn:aws:iam::{self.account}:role/operator"}
        if operation == "validate-policy":
            return {"findings": self.findings}
        if operation == "get-account-authorization-details":
            return {"RoleDetailList": ([self.role] if self.role else []) + self.other}
        if operation == "get-role":
            return {"Role": copy.deepcopy(self.role)} if self.role else None
        if operation == "list-attached-role-policies":
            return {"AttachedPolicies": self.attached}
        if operation == "list-role-policies":
            return {"PolicyNames": ([iam.POLICY] if self.policy else []) + self.extra_inline}
        if operation == "get-role-policy":
            return {"PolicyDocument": copy.deepcopy(self.policy)} if self.policy else None
        self.writes.append(operation)
        if operation == "create-role":
            self.role = {"RoleName": iam.ROLE, "Path": "/", "Tags": kwargs["tags"],
                         "Arn": f"arn:aws:iam::{self.account}:role/{iam.ROLE}",
                         "AssumeRolePolicyDocument": copy.deepcopy(kwargs["assume_role_policy_document"])}
        elif operation == "put-role-policy":
            self.policy = copy.deepcopy(kwargs["policy_document"])
        elif operation == "update-assume-role-policy":
            self.role["AssumeRolePolicyDocument"] = copy.deepcopy(kwargs["policy_document"])
        else:
            raise AssertionError(operation)
        return {}


class IAMTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(CONFIG.read_text())
        self.config.pop("dms_s3_iam", None)
        self.aws = FakeAWS(self.config)
        self.bucket_check = patch.object(iam.landing, "reconcile", return_value={})
        self.simulator = patch.object(iam, "simulate", return_value=[])
        self.bucket_check.start()
        self.simulator.start()
        self.addCleanup(self.bucket_check.stop)
        self.addCleanup(self.simulator.stop)

    def apply(self):
        return iam.reconcile(self.config, self.aws, True)

    def test_create_then_repeat_does_not_mutate(self):
        self.assertEqual(self.apply()["changes"], ["create_role", "inline_policy"])
        self.aws.writes.clear()
        self.assertEqual(self.apply()["changes"], [])
        self.assertEqual(self.aws.writes, [])
        self.assertEqual(iam.reconcile(self.config, self.aws, False)["changes"], [])

    def test_account_mismatch_prevents_all_writes(self):
        self.aws.account = "000000000000"
        with self.assertRaisesRegex(ValueError, "STS account mismatch"):
            self.apply()
        self.assertEqual(self.aws.writes, [])
        iam.landing.reconcile.assert_not_called()

    def test_profile_region_environment_are_explicit(self):
        env = {"AWS_PROFILE": "pmdp-dev", "AWS_REGION": "us-east-2", "PMDP_ENV": "dev"}
        for key, wrong in (("AWS_PROFILE", "default"), ("AWS_REGION", "us-west-2"), ("PMDP_ENV", "prod")):
            with self.subTest(key=key), patch.dict(os.environ, {**env, key: wrong}, clear=True):
                with self.assertRaises(ValueError):
                    iam.load_config(CONFIG)
        with patch.dict(os.environ, env, clear=True):
            iam.load_config(CONFIG)

    def test_bucket_validation_failure_prevents_iam_writes(self):
        iam.landing.reconcile.side_effect = ValueError("region or bucket safety failure")
        with self.assertRaisesRegex(ValueError, "bucket safety"):
            self.apply()
        self.assertEqual(self.aws.writes, [])

    def test_read_only_drift_and_apply_repair(self):
        self.apply()
        self.aws.role["AssumeRolePolicyDocument"] = {}
        self.aws.writes.clear()
        with self.assertRaisesRegex(ValueError, "Trust policy drift"):
            iam.reconcile(self.config, self.aws, False)
        self.assertEqual(self.aws.writes, [])
        self.assertEqual(self.apply()["changes"], ["trust_policy"])

    def test_unowned_role_or_extra_grants_are_never_adopted(self):
        for change in ("tag", "attached", "inline", "boundary"):
            with self.subTest(change=change):
                self.aws = FakeAWS(self.config)
                self.apply()
                if change == "tag":
                    self.aws.role["Tags"] = []
                elif change == "attached":
                    self.aws.attached = [{"PolicyArn": "arn:aws:iam::aws:policy/AdministratorAccess"}]
                elif change == "inline":
                    self.aws.extra_inline = ["unrelated"]
                else:
                    self.aws.role["PermissionsBoundary"] = {"PermissionsBoundaryArn": "unexpected"}
                self.aws.writes.clear()
                with self.assertRaises(ValueError):
                    self.apply()
                self.assertEqual(self.aws.writes, [])

    def test_analyzer_findings_block_creation(self):
        self.aws.findings = [{"findingType": "SECURITY_WARNING"}]
        with self.assertRaisesRegex(ValueError, "Access Analyzer findings"):
            self.apply()
        self.assertEqual(self.aws.writes, [])

    def test_unrelated_iam_change_is_detected(self):
        self.apply()
        def concurrent_change(*args):
            self.aws.other.append({"RoleName": "unrelated", "AssumeRolePolicyDocument": {}})
            return []
        iam.simulate.side_effect = concurrent_change
        with self.assertRaisesRegex(ValueError, "Unrelated IAM"):
            self.apply()

    def test_resolved_config_mismatch_blocks_writes(self):
        self.config["dms_s3_iam"] = {"role_arn": "wrong"}
        with self.assertRaisesRegex(ValueError, "persisted IAM"):
            self.apply()
        self.assertEqual(self.aws.writes, [])

    def test_simulator_supplies_region_context_and_checks_all_cases(self):
        self.simulator.stop()
        responses = [{"EvaluationResults": [{"EvalDecision": decision}]} for decision in
                     ["allowed"] * 12 + ["explicitDeny"] * 38]
        with patch.object(self.aws, "call", side_effect=responses) as call:
            results = iam.simulate(self.aws, self.config, "fixture-role-arn")
        self.assertEqual(len(results), 50)
        for invocation in call.call_args_list:
            context = invocation.kwargs["context_entries"]
            self.assertIn({"ContextKeyName": "aws:RequestedRegion", "ContextKeyValues": ["us-east-2"],
                           "ContextKeyType": "string"}, context)
        with patch.object(self.aws, "call", return_value={"EvaluationResults": [{"EvalDecision": "explicitDeny"}]}):
            with self.assertRaisesRegex(ValueError, "Simulation mismatch"):
                iam.simulate(self.aws, self.config, "fixture-role-arn")

    def test_policy_uses_config_and_no_broad_actions(self):
        config = copy.deepcopy(self.config)
        config["aws"]["account_id"] = "123456789012"
        config["s3_landing"]["bucket"] = "fixture-bucket"
        trust, policy = iam.documents(config)
        statement = trust["Statement"][0]
        self.assertEqual(statement["Principal"], {"Service": "dms.amazonaws.com"})
        self.assertEqual(statement["Condition"]["StringEquals"], {"aws:SourceAccount": "123456789012"})
        self.assertEqual(statement["Condition"]["ArnLike"]["aws:SourceArn"], "arn:aws:dms:us-east-2:123456789012:*")
        self.assertEqual(policy["Statement"][0]["Resource"], [
            "arn:aws:s3:::fixture-bucket/cdc/rmrg/*", "arn:aws:s3:::fixture-bucket/cdc/scc/*"])
        for item in policy["Statement"]:
            self.assertNotIn("*", item["Action"])
            self.assertNotEqual(item["Resource"], "*")


if __name__ == "__main__":
    unittest.main()
