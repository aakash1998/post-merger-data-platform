# DMS S3 target IAM — KAN-34

Creates only `pmdp-dev-enterprise-dms-s3`, with inline policy
`pmdp-dev-enterprise-dms-s3-write`. One shared role serves the two approved company
CDC roots; separate per-company roles can be introduced if endpoint ownership later
requires isolation. Dev account, region, bucket and CDC roots come from
[dev.json](../config/dev.json), verified against STS and the live KAN-33 bucket.
The role ARN and inline policy name are persisted under `dms_s3_iam` after validation.
Inline policies have no independent ARN; later endpoints use `role_arn` as
`ServiceAccessRoleArn`.

## Run

Requires Python 3.11+ and AWS CLI v2, with the existing browser-login profile.
If its cached session has expired, use `aws login --profile pmdp-dev` and complete
the browser flow. No access keys, users, credentials files or secrets are created.

```sh
export PMDP_ENV=dev
export AWS_PROFILE=pmdp-dev
export AWS_REGION=us-east-2
aws sts get-caller-identity
python3 infrastructure/iam/dms_s3.py --config infrastructure/config/dev.json --apply --report infrastructure/iam/kan-34-first-apply.json
python3 infrastructure/iam/dms_s3.py --config infrastructure/config/dev.json --apply --report infrastructure/iam/kan-34-repeat-apply.json
python3 infrastructure/iam/dms_s3.py --config infrastructure/config/dev.json --report infrastructure/iam/kan-34-validation.json
python3 -m unittest discover -s infrastructure/iam/tests -v
python3 -m unittest discover -s infrastructure/s3/tests -v
```

Use one provisioner at a time. Default mode is read-only; missing resources or drift
fail. Apply creates missing resources or updates the owned role's trust/inline policy
only when documents differ. Conflicting ownership tags, extra policies, unexpected
permissions boundaries or conflicting persisted ARNs fail for review. Unrelated tags
are retained. Partial failures do not roll back created resources; rerunning safely
reads existing state. Resolved configuration and reports are written atomically after
successful validation. A first attempt may therefore create resources without writing
a success report if a subsequent check fails.

## Permission and trust contract

| Permission | Scope / reason |
| --- | --- |
| s3:PutObject, s3:DeleteObject | Only objects under configured cdc/rmrg/ and cdc/scc/; DMS target requirements |
| s3:PutObjectTagging | Same object scope; documented DMS target prerequisite |
| s3:ListBucket | Only the configured landing bucket, with s3:prefix matching the two CDC bases or descendants |
| sts:AssumeRole trust | Only dms.amazonaws.com, with SourceAccount matching STS/config and SourceArn restricted to DMS in the configured region/account |

The base-prefix list patterns include exact `cdc/rmrg` and `cdc/scc` requests plus
slash-delimited descendants. Bucket-root listing and similarly named siblings are
denied. No object reads, ACL changes, deletion of historical versions, bucket changes,
KMS, Glue, Secrets Manager or IAM administration permissions are granted. The existing
bucket uses SSE-S3 and BucketOwnerEnforced, so there is no KMS key policy or ACL grant.
Keep later endpoints on SSE-S3 with no canned ACL setting. AWS documents ACL permissions
for ACL-based configurations; this implementation deliberately omits PutObjectAcl for
the ACL-disabled bucket. Endpoint tests must confirm this setting combination.

No bucket policy is needed for same-account role access. KAN-33's absent-policy check
continues unchanged. The service role has no iam:PassRole grant: the future endpoint
operator needs that separately, restricted to this role and iam:PassedToService=dms.amazonaws.com.
No dms-vpc-role, logging role or service-linked role is created here; those depend on
the runtime and logging choice in later tickets. Aiven database passwords/replication
grants are separate from this AWS IAM target role.

## Validation and boundaries

Each run verifies STS before writes and runs KAN-33's read-only owner/region/security
checks. IAM trust and permissions documents are validated by Access Analyzer with
zero findings required, then read back from AWS. IAM principal simulation tests 50
allowed/denied cases, including both CDC roots, prefix siblings, other landing roots,
another bucket, reads, ACLs, version deletion and administration. Every case supplies
aws:RequestedRegion so organization region restrictions are evaluated in the intended
context. Explicit or implicit denial both satisfy negative cases; any denial of an
intended operation fails. Reports include organization decision details.

The full IAM authorization inventory is hashed before and after, excluding only the
managed role and volatile RoleLastUsed fields. Equal hashes prove no unrelated
principal/policy authorization state changed during that run; raw inventory is never
saved. Concurrent IAM changes cause validation to fail rather than being attributed
to this provisioner. This inventory does not cover every IAM/account setting or
CloudTrail activity. The code's only mutation APIs are create-role,
update-assume-role-policy and put-role-policy, all pinned to the single role.

Trust validation proves the configured DMS service principal and account/region
conditions, not an actual service session. A live DMS AssumeRole/endpoint connection
cannot be exercised without creating the runtime/endpoints excluded from this ticket.
SCP/session/network behavior must also be confirmed by that future live test. Narrow
SourceArn to actual resource ARNs once they exist. DMS-generated suffixes, CdcPath,
transaction order and format remain future endpoint/task decisions; all paths must
stay within the configured company CDC root. If DMS issues an unprefixed ListBucket,
review the observed request before changing the policy.

AWS warns that versioned S3 targets can cause DMS listing timeouts and recommends
lifecycle management when versioning is required. KAN-33 enabled versioning to retain
replay history; KAN-34 preserves it. Agree retention/lifecycle policy before running
CDC rather than granting DeleteObjectVersion or silently changing storage settings.

References: [AWS DMS S3 target prerequisites and limitations](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_Target.S3.html),
[DMS confused deputy protection](https://docs.aws.amazon.com/dms/latest/userguide/cross-service-confused-deputy-prevention.html),
[IAM simulator behavior](https://docs.aws.amazon.com/IAM/latest/APIReference/API_SimulatePrincipalPolicy.html).
See [live evidence](kan-34-validation.md).
