# AWS (optional): only if the API has to leave your laptop

**TerraSentry does not use AWS today.** Models come from SAP AI Core, the Joule proxy runs on the
committee's SAP BTP Cloud Foundry space, and everything else runs locally. This page exists for one
case: you want a public deployment of the API and cockpit and the committee's environment cannot
give you a database for it.

> Prices, credit amounts and plan rules change. Verify against the links at the bottom before
> relying on a number; the mechanics below are what matter.

## Do you need it?

| Question | If yes |
| --- | --- |
| Is the demo fine with the API on a laptop behind a tunnel (`docs/sap-hackathon-resources.md` §5)? | You do not need AWS. This is the default. |
| Does the BTP marketplace in the committee's subaccount offer Postgres and Redis you can bind? | Host the API on Cloud Foundry too. Ask the mentors; the committee's instructions do not mention one. |
| Neither works, and judges must reach the API without your laptop? | Use AWS as below, or a free Postgres such as Neon plus any container host. |

## Account and safety

1. Create a free account at <https://aws.amazon.com/free/> and pick the **Free plan** unless you
   know you need a paid-only service. It gives sign-up credits and a subset of services, and closes
   after 6 months or when credits run out.
2. Sign in as root once and enable **MFA** (Security credentials, Assign MFA device).
3. In **Billing and Cost Management, Budgets**, create two budgets: `terrasentry-alerts` at $1
   (actual and forecasted) and `terrasentry-critical` at $20 (actual), both emailing the team.
4. Never use root credentials for code. Use IAM Identity Center (SSO) for people and IAM roles for
   workloads; a scoped, rotated access key is the fallback for a single hackathon account.
5. Keep the account email in a shared password manager; credits live with the account.

## What to deploy and what it costs

| Service | Free situation | Guidance |
| --- | --- | --- |
| **RDS PostgreSQL** | Free-tier offers vary; Aurora Serverless v2 is **not** free | A small `db.t4g.micro` with a hard stop, or Neon's free tier. Delete the instance after the demo. |
| **ECS Fargate / ALB** | No free tier; the ALB bills hourly | The costliest part. One service at desired-count 1; tear it down the same day. App Runner is an alternative but also bills. |
| **ElastiCache Redis** | No free tier | Use `CACHE_BACKEND=memory`, a Redis container beside the API, or Upstash's free tier. |
| **S3 / CloudFront** | 5 GB and 1 TB egress in the Always Free tier | Only if you add object storage or front the web app. Neither is built. |
| **NAT Gateway** | Billed hourly plus per GB | Avoid it; use public subnets or VPC endpoints for the demo. |
| **CloudWatch Logs** | 5 GB ingest free tier (verify) | Set 7-day retention; never log full payloads. |

`infra/cdk` is an empty CDK app shell (`cdk synth` works and emits nothing). A real stack would grow
there, one per concern (network, data, api, web). Nothing in it is claimed as built.

**Teardown checklist after any cloud demo:** delete the ALB, ECS services and clusters, RDS, NAT
gateways, ECR images and idle CloudWatch alarms. Check **Billing, Cost Explorer** the next day.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| The Free plan hides a service you need | Upgrade to the Paid plan (credits carry over) |
| Credits not visible | Billing, Credits page; activity credits post after completion |
| Everything is `AccessDenied` | A restricted IAM policy, or an Educate Starter Account (no IAM) |
| Bills despite credits | Usage outside credit-eligible services (support plans, marketplace) |
| Wrong-region resources | Run `aws configure get region` before debugging code |

## Links

- AWS Free Tier: <https://aws.amazon.com/free/>
- Earning credits: <https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html>
- AWS CLI install: <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>
