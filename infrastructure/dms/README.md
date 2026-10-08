# DMS dev runtime — KAN-35 (blocked at preflight)

**No runtime has been provisioned. KAN-35 is incomplete.** The active dev principal
cannot call either `dms:DescribeOrderableReplicationInstances` or
`dms:DescribeReplicationInstances` in `us-east-2`. AWS explicitly attributes both
denials to organization service control policy **p-h35xigb5**. Reading that policy
is also denied. An AWS Organizations administrator must review that policy's DMS
restriction; do not bypass it, change credentials, upgrade the Free plan, or infer
that a larger instance/serverless option would solve it.

The branch contains a read-only preflight collector and its tests, not an unvalidated
runtime provisioner. There is deliberately no apply mode. The collector uses a strict
API allowlist, the existing browser-login credential chain and KAN-33/KAN-34 safety
checks. It rejects a mismatched STS account before discovery, independently records
API failures, and never interprets AccessDenied as an absent resource. No credentials
or raw AWS error messages are saved.

## Reproduce the access check

```sh
export PMDP_ENV=dev
export AWS_PROFILE=pmdp-dev
export AWS_REGION=us-east-2
aws sts get-caller-identity
python3 infrastructure/dms/preflight.py --config infrastructure/config/dev.json --report infrastructure/dms/kan-35-preflight.json
python3 -m unittest discover -s infrastructure/dms/tests -v
```

Exit 2 means blocked checks, exit 1 means invalid configuration or a fatal error,
and exit 0 means inventory collected. Even exit 0 does not mean a runtime is available
or that source connectivity has been tested. Review the report before implementation.
Refresh an expired browser session with `aws login --profile pmdp-dev`.

## Observed on 2026-10-08

| Check | Observed result |
| --- | --- |
| STS / configuration | Account 430086246924, region us-east-2 |
| Account plan | FREE, ACTIVE; $100 remaining credits; expiry 2027-04-08 |
| KAN-33 landing bucket | Configured bucket exists; owner, region and security checks pass |
| KAN-34 target IAM | Configured role exists; trust and inline permission documents match |
| DMS options / runtime inventory | Both denied by SCP; class/engine availability and runtime state unknown |
| Default VPC | vpc-0ccea02b5b46d6586, available, DNS support and hostnames enabled |
| Existing subnets | Three available default public subnets in us-east-2a/b/c, each with 4091 free IPs |
| Routing | Main route table rtb-03b6891bd69309edd has active 0.0.0.0/0 route to attached igw-0fb26d18ecfa13a73 |
| NACL | Default ACL permits IPv4 inbound/outbound, including return traffic |
| Security groups | Only the existing default group; no dedicated DMS group created |
| dms-vpc-role | Absent; prerequisite for later provisioned-runtime creation |
| NAT gateways / VPC endpoints | None observed in region |
| AWS mutations | None |
| Offline validation | Four preflight safety tests pass |

[Machine-readable preflight evidence](kan-35-preflight.json) records the discovery
results. Network identifiers here are observations, not hardcoded provisioning
inputs. No resolved runtime identifiers are added to dev.json because no runtime
exists from this work. Existing configuration is unchanged. Runtime availability,
source connectivity and repeated-apply idempotency have **not** been validated.

## Proposed smallest-runtime design, pending successful discovery

Use one single-AZ `dms.t3.micro`, 50 GiB included storage, a supported engine version
resolved from DMS, and the existing default VPC. Confirm its orderable options and
storage bounds before implementing creation. Do not silently choose a bigger class.
The public IPv4 route is needed to reach public Aiven database services without NAT.
Use a DMS replication subnet group spanning at least two existing AZ subnets; the
group's multiple AZs do not imply a Multi-AZ replication instance.

Create only a dedicated no-ingress security group, the DMS subnet group, required
`dms-vpc-role` with its documented network management policy, and the one runtime.
The exact IAM name is an AWS requirement; other proposed names follow
`pmdp-dev-enterprise-dms`, `pmdp-dev-enterprise-dms-subnets`, and
`pmdp-dev-enterprise-dms-sg`. Tag supported resources with Project=pmdp,
Environment=dev, Role=dms-runtime and ManagedBy=pmdp-dms-runtime-provisioner.
Reuse existing routes/IGW/NACLs; no new VPC, subnets, NAT, load balancer, interface
endpoint or custom KMS key is planned. Use the AWS-managed default encryption key.

Before setting egress rules, resolve the actual nonsecret Aiven hosts and assigned
ports from operator configuration; do not assume standard PostgreSQL/MySQL ports.
Validate DNS and Aiven IP allowlists against the eventual DMS public IP. Allow source
connections and HTTPS for S3; review dynamic Aiven addressing rather than persisting
an incidental DNS answer as a permanent firewall rule. Public DMS needs no inbound
source rule because it initiates connections. The existing public route supports the
S3 path without requiring a paid endpoint. Later endpoint testing must verify TLS,
credentials, CDC grants, actual network reachability and KAN-34 prefix permissions.

The eventual provisioner must fail before mutation on incompatible identity, cost
settings or network prerequisites; refuse adoption of unowned/conflicting resources;
read before writes; resume partial creation safely; wait for available with a bounded
timeout; persist only verified identifiers; and prove a second apply makes zero
changes. Implement and live-test that path only after authorized DMS access is restored.
Source/target endpoints, tasks, Aiven changes and Databricks remain outside this ticket.

## Cost assessment

The published Ohio on-demand catalog lists single-AZ t3.micro at **$0.018/hour**.
One public IPv4 address adds **$0.005/hour**, giving a baseline **$0.023/hour**, or
**$16.79 for 730 hours** ($13.14 compute + $3.65 IPv4). T3 includes 50 GiB storage.
Runtime compute is charged while provisioned even without replication tasks; budget
its lifetime and arrange deliberate cleanup when it is no longer needed.

T3 uses unlimited CPU credits: sustained above-baseline CPU can add **$0.075 per
vCPU-hour**. The estimate excludes surplus CPU, additional storage, S3 requests/storage,
other traffic and taxes. These costs can consume Free-plan credits; this is not an
assumption of legacy 750 free instance hours. The observed $100 balance is a snapshot,
not a budget reservation. Monitor billing/credits; never upgrade the plan automatically.

The same regional catalog lists single-AZ serverless at **$0.086509046 per hour for
1 DCU** (about $63.15 per 730 continuously billed hours before other costs). It is
more expensive for this small continuously provisioned workload and adds configuration
complexity. The public catalog establishes price, not account-level eligibility.
No compute or network resources were created during this preflight, so no new runtime
or supporting-network credit consumption was introduced.

Sources, checked 2026-10-08:

- [Ohio DMS price catalog, published 2026-09-11](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSDatabaseMigrationSvc/current/us-east-2/index.json): t3.micro Single SKU MHGANBXXXXWBFGJ9; 1 DCU Single SKU 5NS6QV6438TX7SSH.
- [AWS DMS pricing and Free-plan/CPU/storage terms](https://aws.amazon.com/dms/pricing/).
- [Amazon VPC public IPv4 pricing](https://aws.amazon.com/vpc/pricing/).
- [DMS replication instance networking](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_ReplicationInstance.VPC.html).
- [DMS IAM prerequisites and required role names](https://docs.aws.amazon.com/dms/latest/userguide/security-iam.html).
