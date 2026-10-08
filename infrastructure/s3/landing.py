"""KAN-33: reconcile and verify only the configured dev raw landing bucket."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

PREFIXES = ["cdc/rmrg/", "cdc/scc/", "batch/scc/", "schemas/", "checkpoints/", "replay/"]
PUBLIC_BLOCK = dict.fromkeys(
    ["BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"], True
)
OWNERSHIP = {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}
ENCRYPTION = {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text())
    require(os.environ.get("PMDP_ENV") == config["environment"] == "dev",
            "KAN-33 requires PMDP_ENV=dev and dev configuration")
    aws, landing = config["aws"], config["s3_landing"]
    require(bool(re.fullmatch(r"[0-9]{12}", aws["account_id"])), "Invalid account ID")
    require(bool(re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]+", aws["region"])), "Invalid region")
    bucket = f"pmdp-dev-landing-{aws['region']}-{aws['account_id']}"
    require(landing["bucket"] == bucket and len(bucket) <= 63, "Bucket violates naming standard")
    for variable in ("AWS_REGION", "AWS_DEFAULT_REGION", "PMDP_AWS_REGION"):
        require(os.environ.get(variable, aws["region"]) == aws["region"], f"Conflicting {variable}")
    require(os.environ.get("PMDP_S3_LANDING_BUCKET", bucket) == bucket, "Conflicting landing bucket")
    require(landing["prefixes"] == PREFIXES, "Unexpected landing roots")
    require(landing["cdc_base_prefixes"] == {"rmrg": "cdc/rmrg", "scc": "cdc/scc"},
            "CDC bases must let DMS append the source namespace/table")
    require(landing["tags"].get("Project") == "pmdp" and
            landing["tags"].get("Environment") == "dev" and
            landing["tags"].get("Role") == "landing", "Invalid project/environment/role tags")
    return config


class AWS:
    """Use the CLI credential chain without reading, storing or logging credentials."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.region = config["aws"]["region"]
        self.account = config["aws"]["account_id"]
        self.bucket = config["s3_landing"]["bucket"]

    def call(self, service: str, operation: str, *, missing: tuple[str, ...] = (),
             **parameters: Any) -> dict[str, Any] | None:
        command = ["aws", service, operation, "--region", self.region,
                   "--output", "json", "--no-cli-pager", "--cli-connect-timeout", "10",
                   "--cli-read-timeout", "30"]
        if service == "s3api":
            parameters = {"bucket": self.bucket, **parameters}
            if operation != "create-bucket":
                parameters["expected_bucket_owner"] = self.account
        for key, value in parameters.items():
            command.extend(["--" + key.replace("_", "-"),
                            json.dumps(value) if isinstance(value, (dict, list)) else str(value)])
        result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
        if result.returncode:
            match = re.search(r"An error occurred \(([^)]+)\)", result.stderr)
            code = match.group(1) if match else "CLI/network failure"
            if code in missing:
                return None
            # Do not echo raw CLI stderr, arguments, credential values or identity ARNs.
            raise RuntimeError(f"{service}.{operation} failed: {code}")
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def s3(self, operation: str, **parameters: Any) -> dict[str, Any] | None:
        return self.call("s3api", operation, **parameters)


def reconcile(config: dict[str, Any], aws: AWS, apply: bool) -> dict[str, Any]:
    changes: list[str] = []
    identity = aws.call("sts", "get-caller-identity")
    require(identity is not None and identity["Account"] == config["aws"]["account_id"],
            "Authenticated AWS account differs from configured account; no changes made")
    location = aws.s3("get-bucket-location", missing=("NoSuchBucket",))
    if location is None:
        require(apply, "Landing bucket does not exist")
        args: dict[str, Any] = {"object_ownership": "BucketOwnerEnforced"}
        if aws.region != "us-east-1":
            args["create_bucket_configuration"] = {"LocationConstraint": aws.region}
        aws.s3("create-bucket", **args)
        changes.append("create_bucket")
    else:
        actual_region = location.get("LocationConstraint") or "us-east-1"
        require(actual_region == aws.region, "Existing bucket is in a different region")

    # Refuse to replace/adopt any bucket policy. DMS policies belong to later tickets.
    policy = aws.s3("get-bucket-policy", missing=("NoSuchBucketPolicy",))
    require(policy is None, "Existing bucket policy requires review; no policy is changed")

    settings = [
        ("public_access_block", "get-public-access-block", "NoSuchPublicAccessBlockConfiguration",
         "PublicAccessBlockConfiguration", PUBLIC_BLOCK, "put-public-access-block", "public_access_block_configuration"),
        ("ownership", "get-bucket-ownership-controls", "OwnershipControlsNotFoundError",
         "OwnershipControls", OWNERSHIP, "put-bucket-ownership-controls", "ownership_controls"),
        ("encryption", "get-bucket-encryption", "ServerSideEncryptionConfigurationNotFoundError",
         "ServerSideEncryptionConfiguration", ENCRYPTION, "put-bucket-encryption", "server_side_encryption_configuration"),
    ]
    for label, get, absent, key, desired, put, parameter in settings:
        response = aws.s3(get, missing=(absent,)) or {}
        actual = response.get(key)
        if label == "encryption" and actual:
            # AWS can return extra defaults; only enforce the selected AES256 rule.
            matches = len(actual.get("Rules", [])) == 1 and actual["Rules"][0].get(
                "ApplyServerSideEncryptionByDefault") == ENCRYPTION["Rules"][0]["ApplyServerSideEncryptionByDefault"]
            require(matches, "Existing encryption differs from SSE-S3; review before changing encryption")
        else:
            matches = actual == desired
        if not matches:
            require(apply, f"Nonconforming {label}")
            aws.s3(put, **{parameter: desired})
            changes.append(label)

    versioning = aws.s3("get-bucket-versioning") or {}
    if versioning.get("Status") != "Enabled":
        require(apply, "Versioning is not Enabled")
        aws.s3("put-bucket-versioning", versioning_configuration={"Status": "Enabled"})
        changes.append("versioning")
    tags = aws.s3("get-bucket-tagging", missing=("NoSuchTagSet",)) or {}
    current_tags = {tag["Key"]: tag["Value"] for tag in tags.get("TagSet", [])}
    desired_tags = config["s3_landing"]["tags"]
    if any(current_tags.get(key) != value for key, value in desired_tags.items()):
        require(apply, "Missing or conflicting project tags")
        merged = {**current_tags, **desired_tags}
        aws.s3("put-bucket-tagging", tagging={"TagSet": [{"Key": k, "Value": v} for k, v in sorted(merged.items())]})
        changes.append("tags")

    acl = aws.s3("get-bucket-acl") or {}
    owner = acl.get("Owner", {}).get("ID")
    require(bool(owner) and acl.get("Grants") == [
        {"Grantee": {"ID": owner, "Type": "CanonicalUser"}, "Permission": "FULL_CONTROL"}
    ], "Bucket ACL is not owner-only")
    for prefix in PREFIXES:
        marker = aws.s3("head-object", key=prefix, missing=("404", "NoSuchKey", "NotFound"))
        if marker is None:
            require(apply, f"Missing logical root {prefix}")
            # Conditional creation prevents concurrent runs from adding marker versions.
            aws.s3("put-object", key=prefix, content_length=0, if_none_match="*", missing=("PreconditionFailed",))
            changes.append(f"root:{prefix}")
        else:
            require(marker.get("ContentLength") == 0, f"Nonempty root marker {prefix}; refusing overwrite")

    if apply:
        # Independent readback of every requirement; this call cannot mutate AWS.
        report = reconcile(config, aws, False)
        report["changes"] = changes
        return report
    return {
        "ticket": "KAN-33", "validated_at": datetime.now(timezone.utc).isoformat(),
        "environment": "dev", "account_id": aws.account, "region": aws.region,
        "bucket": aws.bucket, "private": True, "bucket_policy": "absent",
        "public_access_block": PUBLIC_BLOCK, "object_ownership": "BucketOwnerEnforced",
        "encryption": "AES256", "versioning": "Enabled", "tags": current_tags,
        "prefixes": PREFIXES, "cdc_base_prefixes": config["s3_landing"]["cdc_base_prefixes"],
        "changes": [], "validation": "passed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Reconcile then validate; default is read-only")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        report = reconcile(config, AWS(config), args.apply)
        output = json.dumps(report, indent=2) + "\n"
        if args.report:
            temporary = args.report.with_suffix(args.report.suffix + ".tmp")
            temporary.write_text(output)
            temporary.replace(args.report)
        print(output, end="")
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"ticket": "KAN-33", "validation": "failed", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
