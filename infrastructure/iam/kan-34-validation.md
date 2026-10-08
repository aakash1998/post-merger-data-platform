# KAN-34 dev validation

Validated 2026-10-08 with the existing browser-login AWS_PROFILE=pmdp-dev and
AWS_REGION=us-east-2. STS verified account **430086246924** before IAM changes.
The live role is `arn:aws:iam::430086246924:role/pmdp-dev-enterprise-dms-s3`.
Its sole inline policy is `pmdp-dev-enterprise-dms-s3-write`; no standalone policy
resource/ARN is necessary. The resolved role ARN and policy name are in dev.json.

| Check | Result |
| --- | --- |
| Config / STS / bucket region and owner | Match; us-east-2, existing KAN-33 landing bucket |
| Role ownership | Project=pmdp, Environment=dev, Role=dms-s3-target, ManagedBy=pmdp-dms-iam-provisioner |
| Trust | Only dms.amazonaws.com with matching SourceAccount and regional/account DMS SourceArn |
| Policy readback | Exact intended inline document; no attached managed policies or extra inline grants |
| Access Analyzer | Zero findings for trust and permission documents |
| Live principal simulation | 50 cases pass: 12 allowed, 38 denied |
| Allowed operations | Write/delete/tag CDC objects and list company CDC prefixes only |
| Negative operations | Other landing roots, sibling prefix, other bucket, unprefixed listing, reads, ACL changes, version deletion, bucket deletion and IAM administration denied |
| Repeated apply | changes=[] |
| Unrelated IAM state | Before/after authorization fingerprints identical |
| Offline tests | 11 IAM safety tests and 8 existing S3 tests pass |

The initial attempt created the role and inline policy, then failed simulation because
aws:RequestedRegion was absent from the simulated context and the organization's
region restriction denied the request. Supplying the intended region produced
AllowedByOrganizations=true without changing the IAM policy. The regression test
requires region context for every case. Organization policy listing is not permitted
to the dev operator; no organization policies were changed.

The [first successful apply report](kan-34-first-apply.json) is the recovery run;
it correctly records changes=[] because the role/policy already existed from the
initial attempt. The [repeat apply](kan-34-repeat-apply.json) and
[final read-only report](kan-34-validation.json) retain the exact live policies,
per-case decisions and unrelated IAM fingerprints. These reports contain only
nonsecret resource identities and validation evidence; raw IAM inventory and
credentials are not saved.

Scope: one IAM role and its inline policy. KAN-33 bucket settings, all other IAM
resources, Aiven databases and Databricks resources were not modified. No DMS
runtime, endpoints, replication tasks, access keys or users were created.

Live DMS assumption/connection testing remains for the runtime/endpoint ticket.
Access Analyzer and exact trust readback validate policy structure and conditions;
they do not impersonate the DMS service. Validate prefix-restricted ListBucket,
ACL-disabled SSE-S3 endpoint settings, and the versioned bucket's retention/lifecycle
tradeoff before running CDC. See the [runbook](README.md) for the precise validation
boundaries and AWS references.
