# KAN-33 development validation

Validated on 2026-10-08 using AWS_PROFILE=pmdp-dev and AWS_REGION=us-east-2.
STS verified account **430086246924** before provisioning. No credentials are included
in configuration, logs, reports or commits.

| Check | Observed result |
| --- | --- |
| Bucket | pmdp-dev-landing-us-east-2-430086246924 |
| Actual bucket region | us-east-2 |
| Public access block | All four bucket flags true |
| Ownership / ACL | BucketOwnerEnforced / owner-only FULL_CONTROL |
| Bucket policy | Absent |
| Default encryption | AES256 (SSE-S3) |
| Versioning | Enabled |
| Tags | Project=pmdp, Environment=dev, Role=landing, ManagedBy=pmdp-s3-provisioner |
| Roots | cdc/rmrg/, cdc/scc/, batch/scc/, schemas/, checkpoints/, replay/ |
| DMS bases in configuration | cdc/rmrg and cdc/scc; DMS appends namespace/table later |
| Repeated apply | Passed, changes=[] |
| Standalone read-only validation | Passed |
| Independent version inventory after repeat | Six zero-byte current versions, one per root; no delete markers or other objects |
| Offline safety suite | Eight tests passed |

First apply created the bucket, enabled versioning, added tags and created the six
root markers. AWS supplied conforming public block, ownership and encryption defaults,
which were explicitly verified. No DMS files, table folders, endpoints/tasks, IAM
roles/policies, Databricks or lakehouse resources were created.

Reproduce the provisioning, repeat apply and read-only validation with the commands
in the [runbook](README.md). Machine-readable evidence:

- [First apply](kan-33-first-apply.json)
- [Repeat apply](kan-33-repeat-apply.json)
- [Read-only validation](kan-33-validation.json)

The independent inventory used `aws s3api list-object-versions` with the configured
bucket, profile, region and expected owner; its projected output contained only
the six root keys, Size=0 and IsLatest=true. No extra object versions were generated
by repeat apply.

Offline tests cover zero-write repeat apply, wrong account/region, explicit environment
selection/conflicting overrides, read-only drift detection and repair, existing policy
rejection, nonempty marker protection, KMS downgrade prevention, and distinguishing
AccessDenied from missing resources while pinning expected owner/region.

No lifecycle/expiry policy is selected pending approved retention requirements.
Future DMS IAM/bucket policy work must deliberately extend the current absent-policy
validation contract. This is a bucket configuration check, not an account-wide IAM audit.
