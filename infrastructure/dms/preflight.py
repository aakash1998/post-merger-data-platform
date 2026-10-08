"""Read-only KAN-35 preflight. Never provisions infrastructure or upgrades a plan."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

SPEC = importlib.util.spec_from_file_location("dms_iam", Path(__file__).parents[1] / "iam/dms_s3.py")
assert SPEC and SPEC.loader
IAM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IAM)
require = IAM.require

# Enforce the read-only boundary even if a future caller passes an unsafe operation.
READS = {
    "sts": {"get-caller-identity"},
    "freetier": {"get-account-plan-state"},
    "dms": {"describe-orderable-replication-instances", "describe-replication-instances"},
    "ec2": {"describe-vpcs", "describe-subnets", "describe-route-tables", "describe-network-acls",
            "describe-vpc-attribute", "describe-internet-gateways", "describe-security-groups",
            "describe-nat-gateways", "describe-vpc-endpoints"},
    "iam": {"get-role", "get-role-policy", "list-role-policies", "list-attached-role-policies"},
    "s3api": {"get-bucket-location", "get-bucket-policy", "get-public-access-block",
              "get-bucket-ownership-controls", "get-bucket-encryption", "get-bucket-versioning",
              "get-bucket-tagging", "get-bucket-acl", "head-object"},
}


class ReadOnlyAWS(IAM.landing.AWS):
    def call(self, service: str, operation: str, **parameters: Any) -> dict[str, Any] | None:
        require(operation in READS.get(service, set()), f"Read-only preflight rejects {service}.{operation}")
        return super().call(service, operation, **parameters)


def collect(config: dict[str, Any], aws: ReadOnlyAWS) -> dict[str, Any]:
    identity = aws.call("sts", "get-caller-identity")
    require(identity["Account"] == config["aws"]["account_id"], "STS account mismatch")
    require(identity["Arn"].split(":")[1] == "aws", "Unexpected AWS partition")
    report: dict[str, Any] = {
        "ticket": "KAN-35", "observed_at": datetime.now(timezone.utc).isoformat(),
        "environment": config["environment"], "account_id": identity["Account"],
        "region": aws.region, "aws_mutations": [], "checks": {}, "blockers": [],
        "runtime_provisioned": False,
        "validation": "incomplete",
    }

    def check(label: str, service: str, operation: str, **parameters: Any) -> dict[str, Any] | None:
        try:
            result = aws.call(service, operation, **parameters)
            report["checks"][label] = {"status": "read_succeeded", "result": result}
            return result
        except (RuntimeError, IAM.landing.subprocess.TimeoutExpired) as error:
            # The shared CLI wrapper removes raw stderr, principal ARNs and credentials.
            detail = str(error) if isinstance(error, RuntimeError) else "AWS CLI timeout"
            report["checks"][label] = {"status": "failed", "error": detail}
            report["blockers"].append(label)
            return None

    plan = check("account_plan", "freetier", "get-account-plan-state")
    if plan and (plan.get("accountPlanType") != "FREE" or plan.get("accountPlanStatus") != "ACTIVE"):
        report["blockers"].append("active_free_plan_not_confirmed")
    try:
        bucket = IAM.landing.reconcile(config, aws, False)
        report["checks"]["landing_bucket"] = {"status": "passed", "result": bucket}
        resolved = config["dms_s3_iam"]
        arn = f"arn:aws:iam::{identity['Account']}:role/{IAM.ROLE}"
        require(resolved == {"role_name": IAM.ROLE, "role_arn": arn, "inline_policy_name": IAM.POLICY},
                "Persisted target role differs from KAN-34 contract")
        role = IAM.inspect_role(aws, arn)
        require(role is not None, "KAN-34 target role missing")
        trust, permission = IAM.documents(config)
        require(role["AssumeRolePolicyDocument"] == trust, "KAN-34 trust drift")
        policy = aws.call("iam", "get-role-policy", role_name=IAM.ROLE, policy_name=IAM.POLICY)
        require(policy["PolicyDocument"] == permission, "KAN-34 permission drift")
        report["checks"]["target_role"] = {"status": "passed", "role_arn": arn}
    except (ValueError, RuntimeError, KeyError, IAM.landing.subprocess.TimeoutExpired) as error:
        report["checks"]["landing_and_target_iam"] = {"status": "failed", "error": type(error).__name__}
        report["blockers"].append("landing_and_target_iam")

    options = check("dms_options", "dms", "describe-orderable-replication-instances")
    if options:
        report["checks"]["dms_options"]["result"] = {
            "micro_options": [o for o in options.get("OrderableReplicationInstances", [])
                              if o["ReplicationInstanceClass"] == "dms.t3.micro"]}
        if not report["checks"]["dms_options"]["result"]["micro_options"]:
            report["blockers"].append("dms_t3_micro_unavailable")
    check("dms_inventory", "dms", "describe-replication-instances")
    check("vpc_role", "iam", "get-role", role_name="dms-vpc-role", missing=("NoSuchEntity",))
    vpcs = check("default_vpc", "ec2", "describe-vpcs", filters=[{"Name": "is-default", "Values": ["true"]}])
    if vpcs and len(vpcs["Vpcs"]) == 1:
        vpc_id = vpcs["Vpcs"][0]["VpcId"]
        filters = [{"Name": "vpc-id", "Values": [vpc_id]}]
        for label, operation in (("subnets", "describe-subnets"), ("routes", "describe-route-tables"),
                                 ("network_acls", "describe-network-acls"), ("security_groups", "describe-security-groups")):
            check(label, "ec2", operation, filters=filters)
        check("internet_gateways", "ec2", "describe-internet-gateways",
              filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}])
        for attribute in ("enableDnsSupport", "enableDnsHostnames"):
            check(attribute, "ec2", "describe-vpc-attribute", vpc_id=vpc_id, attribute=attribute)
    elif vpcs:
        report["blockers"].append("unique_default_vpc_not_found")
    check("nat_inventory", "ec2", "describe-nat-gateways")
    check("vpc_endpoint_inventory", "ec2", "describe-vpc-endpoints")
    report["validation"] = "blocked" if report["blockers"] else "inventory_collected"
    report["limitations"] = [
        "Read-only inventory, not a runtime provisioner or connectivity test.",
        "Actual instance class/engine availability requires successful DMS discovery.",
        "Route/NACL/SG suitability, source host/port and Aiven allowlists need review before provisioning.",
        "No runtime identifier is persisted until a runtime is successfully provisioned and verified.",
    ]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = IAM.load_config(args.config)
        report = collect(config, ReadOnlyAWS(config))
        temporary = args.report.with_suffix(args.report.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.replace(args.report)
        print(json.dumps({"ticket": "KAN-35", "validation": report["validation"],
                          "blockers": report["blockers"], "aws_mutations": [], "report": str(args.report)}))
        return 2 if report["blockers"] else 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, IAM.landing.subprocess.TimeoutExpired) as error:
        print(json.dumps({"ticket": "KAN-35", "validation": "failed", "error": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
