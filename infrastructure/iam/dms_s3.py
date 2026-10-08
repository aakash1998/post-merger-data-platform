"""KAN-34: provision only the dev DMS S3 target service role and inline policy."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

# Reuse KAN-33 configuration, CLI credential handling and read-only bucket validation.
SPEC = importlib.util.spec_from_file_location("landing", Path(__file__).parents[1] / "s3/landing.py")
assert SPEC and SPEC.loader
landing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(landing)
require = landing.require
ROLE = "pmdp-dev-enterprise-dms-s3"
POLICY = "pmdp-dev-enterprise-dms-s3-write"
TAGS = {"Project": "pmdp", "Environment": "dev", "Role": "dms-s3-target",
        "ManagedBy": "pmdp-dms-iam-provisioner"}


def load_config(path: Path) -> dict[str, Any]:
    config = landing.load_config(path)
    require(os.environ.get("AWS_PROFILE") == "pmdp-dev", "AWS_PROFILE must be pmdp-dev")
    require(os.environ.get("AWS_REGION") == config["aws"]["region"] == "us-east-2",
            "AWS_REGION and configuration must be us-east-2")
    return config


def documents(config: dict[str, Any], partition: str = "aws") -> tuple[dict, dict]:
    account, region = config["aws"]["account_id"], config["aws"]["region"]
    bucket = f"arn:{partition}:s3:::{config['s3_landing']['bucket']}"
    roots = [base + "/" for base in config["s3_landing"]["cdc_base_prefixes"].values()]
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "dms.amazonaws.com"},
        "Action": "sts:AssumeRole", "Condition": {
            "StringEquals": {"aws:SourceAccount": account},
            "ArnLike": {"aws:SourceArn": f"arn:{partition}:dms:{region}:{account}:*"}}}]}
    policy = {"Version": "2012-10-17", "Statement": [
        {"Sid": "WriteCDCObjects", "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:DeleteObject", "s3:PutObjectTagging"],
         "Resource": [bucket + "/" + root + "*" for root in roots]},
        {"Sid": "ListCDCPrefixes", "Effect": "Allow", "Action": "s3:ListBucket",
         "Resource": bucket, "Condition": {"StringLike": {
             "s3:prefix": [pattern for root in roots for pattern in (root.rstrip("/"), root + "*")]}}}
    ]}
    return trust, policy


def fingerprint(aws: Any) -> str:
    """Hash full IAM authorization state except this role; never persist raw principals."""
    state = aws.call("iam", "get-account-authorization-details")
    require(not state.get("IsTruncated"), "IAM authorization inventory unexpectedly truncated")
    state.pop("ResponseMetadata", None)
    state["RoleDetailList"] = [r for r in state.get("RoleDetailList", []) if r["RoleName"] != ROLE]
    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items() if k != "RoleLastUsed"}
        if isinstance(value, list):
            return sorted((normalize(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
        return value
    return hashlib.sha256(json.dumps(normalize(state), sort_keys=True).encode()).hexdigest()


def inspect_role(aws: Any, arn: str) -> dict | None:
    response = aws.call("iam", "get-role", role_name=ROLE, missing=("NoSuchEntity",))
    if response is None:
        return None
    role = response["Role"]
    tags = {tag["Key"]: tag["Value"] for tag in role.get("Tags", [])}
    require(all(tags.get(k) == v for k, v in TAGS.items()), "Existing role has conflicting ownership tags; refusing adoption")
    require(role["Arn"] == arn and role["Path"] == "/", "Unexpected role ARN/path")
    require(not role.get("PermissionsBoundary"), "Unexpected permissions boundary requires review")
    attached = aws.call("iam", "list-attached-role-policies", role_name=ROLE)
    inline = aws.call("iam", "list-role-policies", role_name=ROLE)
    require(not attached["AttachedPolicies"], "Unexpected managed policies; refusing to modify role")
    require(set(inline["PolicyNames"]) <= {POLICY}, "Unexpected inline policies; refusing to modify role")
    return role


def validate_documents(aws: Any, trust: dict, policy: dict) -> dict:
    results = {}
    for label, document, policy_type in (("trust", trust, "RESOURCE_POLICY"), ("permissions", policy, "IDENTITY_POLICY")):
        params = {"policy_document": document, "policy_type": policy_type}
        if label == "trust":
            params["validate_policy_resource_type"] = "AWS::IAM::AssumeRolePolicyDocument"
        result = aws.call("accessanalyzer", "validate-policy", **params)
        require(not result.get("nextToken"), "Truncated policy validation")
        findings = result.get("findings", [])
        require(not findings, f"{label} policy has Access Analyzer findings: " + json.dumps(findings))
        results[label] = "no findings"
    return results


def simulate(aws: Any, config: dict, arn: str) -> list[dict]:
    bucket = f"arn:aws:s3:::{config['s3_landing']['bucket']}"
    cases = []
    for root in (base + "/" for base in config["s3_landing"]["cdc_base_prefixes"].values()):
        for action in ("s3:PutObject", "s3:DeleteObject", "s3:PutObjectTagging"):
            cases.append((action, bucket + "/" + root + "namespace/table/probe.csv", None, "allowed"))
        for prefix in (root.rstrip("/"), root, root + "namespace/table/"):
            cases.append(("s3:ListBucket", bucket, prefix, "allowed"))
    for prefix in ("", "cdc/", "cdc/rmrg-escape/", "batch/scc/", "schemas/", "checkpoints/", "replay/"):
        cases.append(("s3:ListBucket", bucket, prefix, "implicitDeny"))
        for action in ("s3:PutObject", "s3:DeleteObject", "s3:PutObjectTagging"):
            cases.append((action, bucket + "/" + prefix + "probe.csv", None, "implicitDeny"))
    for action in ("s3:GetObject", "s3:PutObjectAcl", "s3:DeleteObjectVersion"):
        cases.append((action, bucket + "/cdc/rmrg/probe.csv", None, "implicitDeny"))
    for action in ("s3:PutObject", "s3:DeleteObject", "s3:PutObjectTagging"):
        cases.append((action, bucket + "-other/cdc/rmrg/probe.csv", None, "implicitDeny"))
    cases.extend([("s3:ListBucket", bucket + "-other", "cdc/rmrg/", "implicitDeny"),
                  ("s3:ListBucket", bucket, None, "implicitDeny"),
                  ("s3:DeleteBucket", bucket, None, "implicitDeny"),
                  ("iam:CreateUser", "*", None, "implicitDeny")])
    results = []
    for action, resource, prefix, expected in cases:
        params = {"policy_source_arn": arn, "action_names": [action], "resource_arns": [resource],
                  "context_entries": [{"ContextKeyName": "aws:RequestedRegion",
                                       "ContextKeyValues": [aws.region], "ContextKeyType": "string"}]}
        if prefix is not None:
            params["context_entries"].append({"ContextKeyName": "s3:prefix", "ContextKeyValues": [prefix],
                                               "ContextKeyType": "string"})
        response = aws.call("iam", "simulate-principal-policy", **params)
        evaluation = response["EvaluationResults"]
        require(len(evaluation) == 1 and not response.get("IsTruncated"), "Unexpected simulator response")
        actual = evaluation[0]["EvalDecision"]
        require(actual == expected or (expected == "implicitDeny" and actual == "explicitDeny"), f"Simulation mismatch for {action} {resource} prefix={prefix}: {actual}")
        results.append({"action": action, "resource": resource, "prefix": prefix, "decision": actual,
                        "organizations": evaluation[0].get("OrganizationsDecisionDetail", {})})
    return results


def reconcile(config: dict, aws: Any, apply: bool) -> dict:
    identity = aws.call("sts", "get-caller-identity")
    require(identity["Account"] == config["aws"]["account_id"], "STS account mismatch; no changes made")
    partition = identity["Arn"].split(":")[1]
    require(partition == "aws", "Unexpected AWS partition")
    # KAN-33 validation is strictly read-only, including bucket policy and encryption.
    landing.reconcile(config, aws, False)
    arn = f"arn:{partition}:iam::{identity['Account']}:role/{ROLE}"
    resolved = {"role_name": ROLE, "role_arn": arn, "inline_policy_name": POLICY}
    require(config.get("dms_s3_iam", resolved) == resolved, "Conflicting persisted IAM configuration")
    trust, policy = documents(config, partition)
    analysis = validate_documents(aws, trust, policy)
    before = fingerprint(aws)
    role = inspect_role(aws, arn)
    changes = []
    if role is None:
        require(apply, "DMS S3 role is missing")
        aws.call("iam", "create-role", role_name=ROLE, assume_role_policy_document=trust,
                 description="PMDP dev DMS target access to configured CDC landing prefixes only",
                 tags=[{"Key": k, "Value": v} for k, v in TAGS.items()])
        changes.append("create_role")
    elif role["AssumeRolePolicyDocument"] != trust:
        require(apply, "Trust policy drift")
        aws.call("iam", "update-assume-role-policy", role_name=ROLE, policy_document=trust)
        changes.append("trust_policy")
    current = aws.call("iam", "get-role-policy", role_name=ROLE, policy_name=POLICY, missing=("NoSuchEntity",))
    if current is None or current["PolicyDocument"] != policy:
        require(apply, "Inline policy missing or drifted")
        aws.call("iam", "put-role-policy", role_name=ROLE, policy_name=POLICY, policy_document=policy)
        changes.append("inline_policy")
    # IAM eventual consistency: bounded retries only after a mutation.
    for attempt in range(6):
        try:
            role = inspect_role(aws, arn)
            require(role is not None and role["AssumeRolePolicyDocument"] == trust, "Trust readback mismatch")
            actual = aws.call("iam", "get-role-policy", role_name=ROLE, policy_name=POLICY)
            require(actual["PolicyDocument"] == policy, "Permission policy readback mismatch")
            simulations = simulate(aws, config, arn)
            break
        except (ValueError, RuntimeError):
            if not changes or attempt == 5:
                raise
            time.sleep(5)
    after = fingerprint(aws)
    require(before == after, "Unrelated IAM authorization state changed during this run; investigate concurrent activity")
    return {"ticket": "KAN-34", "validated_at": datetime.now(timezone.utc).isoformat(),
            "environment": config["environment"], "account_id": identity["Account"],
            "region": aws.region, "bucket": aws.bucket, "resolved": resolved,
            "trust_policy": trust, "permission_policy": policy, "tags": TAGS,
            "access_analyzer": analysis, "simulations": simulations,
            "unrelated_iam_before_sha256": before, "unrelated_iam_after_sha256": after,
            "changes": changes, "validation": "passed",
            "limitations": ["Trust validated structurally and by Access Analyzer; live DMS assumption/endpoint test deferred until runtime exists.",
                            "Simulator does not prove SCP/session policy/network behavior; bucket configuration independently validated."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        report = reconcile(config, landing.AWS(config), args.apply)
        if args.apply and config.get("dms_s3_iam") != report["resolved"]:
            config["dms_s3_iam"] = report["resolved"]
            temporary = args.config.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(config, indent=2) + "\n")
            temporary.replace(args.config)
        if not args.apply:
            require(config.get("dms_s3_iam") == report["resolved"], "Resolved IAM config is not persisted; run apply")
        output = json.dumps(report, indent=2) + "\n"
        if args.report:
            temporary = args.report.with_suffix(args.report.suffix + ".tmp")
            temporary.write_text(output)
            temporary.replace(args.report)
        print(output, end="")
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, landing.subprocess.TimeoutExpired) as error:
        print(json.dumps({"ticket": "KAN-34", "validation": "failed", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
