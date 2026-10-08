# Dev S3 raw landing — KAN-33

The dev configuration persists the verified account `430086246924`, selected region
`us-east-2`, and bucket `pmdp-dev-landing-us-east-2-430086246924` in
[dev.json](../config/dev.json). Existing Kafka configuration is preserved.
The Python 3.11+ provisioner uses AWS CLI v2, with no additional Python dependencies.
It provisions only the dev landing bucket, its security/settings/tags, and six empty
root markers. It does not provision DMS, IAM, Databricks, or lakehouse resources.

## Run

Authenticate locally with the existing AWS CLI profile (for SSO, refresh with
`aws sso login --profile pmdp-dev`). Credentials stay in the standard CLI credential
chain; do not put them in config, command arguments, reports, or version control.
From the repository root:

```sh
export PMDP_ENV=dev
export AWS_PROFILE=pmdp-dev
export AWS_REGION=us-east-2
aws sts get-caller-identity

# Create missing resources and reconcile settings, then independently read back.
python3 infrastructure/s3/landing.py --config infrastructure/config/dev.json --apply

# Read-only validation. A missing bucket or any drift fails with exit code 1.
python3 infrastructure/s3/landing.py --config infrastructure/config/dev.json

# Repeat apply must report "changes": [] when configuration already conforms.
python3 infrastructure/s3/landing.py --config infrastructure/config/dev.json --apply

# Offline safety tests; no authentication or AWS access required.
python3 -m unittest discover -s infrastructure/s3/tests -v
```

Optional `--report <path>` writes the same structured JSON evidence atomically.
Successful validation exits zero. Any failure exits one; CLI failures report the
operation and error code without echoing raw stderr or identity ARNs. Authentication,
permissions, and network failures are never interpreted as a missing bucket.

The authenticated STS account must match config before any mutation. Every S3 call
uses the configured region and (except bucket creation, whose API does not support it)
the expected bucket owner. Existing bucket location must match. `PMDP_ENV` is required;
test/prod configuration is rejected. `AWS_REGION`, `AWS_DEFAULT_REGION`,
`PMDP_AWS_REGION`, and `PMDP_S3_LANDING_BUCKET`, when set, must agree with config;
conflicting targets fail rather than silently selecting another account or region.
The bucket name must match the approved template exactly. Name collisions or a bucket
owned by another account fail; the tool never invents a suffix or substitutes a target.

## Storage and security decisions

| Setting | Required state |
| --- | --- |
| Block Public Access | All four bucket settings true |
| Object Ownership | BucketOwnerEnforced; ACLs disabled |
| Bucket ACL | Owner-only FULL_CONTROL |
| Bucket policy | Absent; preexisting policies require review, never replaced |
| Default encryption | SSE-S3 / AES256 |
| Versioning | Enabled |
| Tags | Project=pmdp, Environment=dev, Role=landing, ManagedBy=pmdp-s3-provisioner |

Explicit checks retain [AWS's private bucket defaults](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-ownership-new-bucket.html)
and enforce [all four public access blocks](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html).
SSE-S3 provides default encryption without creating a KMS key or key policy outside
KAN-33. Existing different encryption fails for review rather than being downgraded.
Versioning preserves overwritten/deleted source object versions for recovery/replay;
no expiration/lifecycle rule is introduced before retention requirements are agreed.
Tags outside the managed set are retained. No IAM roles/policies or public grants are
created. Future DMS access policy work must update this validation contract deliberately.

## Logical roots and future DMS paths

Exactly these zero-byte root markers are created:

```text
cdc/rmrg/
cdc/scc/
batch/scc/
schemas/
checkpoints/
replay/
```

S3 prefixes are logical key names, not directories. Markers make the roots visible
without fabricating source files. Future DMS `BucketFolder` bases are `cdc/rmrg`
and `cdc/scc`, as recorded under `cdc_base_prefixes`. DMS appends the approved source
namespace and table, yielding `cdc/rmrg/rmrg/<table>/` and `cdc/scc/scc/<table>/`.
Do not add an extra namespace to those bases. No endpoints/tasks/table folders are
created here, and no CDC output format is selected.

## Repeatability and limits

Apply reads existing state, changes only missing/nonconforming managed settings,
and validates again with read-only calls. Existing root markers are never overwritten;
conditional `If-None-Match: *` creation prevents duplicate marker versions during races.
Nonempty objects at the exact root keys fail rather than being replaced. Existing
business objects under roots are neither modified nor deleted. Run one provisioner
per bucket at a time; partial AWS failures can be retried safely after their cause is
resolved. There is no delete or rollback operation.

Validation confirms account, actual bucket location, owner, ACL, absence of bucket
policy, public blocks, default encryption, versioning, tags, markers, and CDC config.
It does not audit account-wide IAM permissions, SCPs, access points, or object payloads.
The live [validation record](kan-33-validation.md) and JSON reports capture first apply
and the zero-change repeat apply.
