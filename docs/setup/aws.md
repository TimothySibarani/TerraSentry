# AWS Setup — Students, Free Tier, and Credits

TerraSentry uses AWS for exactly two things right now: **Bedrock model access** (M3) and,
later, **deployment** (M8). M1 runs entirely on your laptop. This guide gets the account,
credentials, model access, and cost guardrails in place without paying for anything.

> Prices, credit amounts, and plan rules change. Verify against the links at the bottom
> before relying on a number; the mechanics below are what matter.

## 1. Which account option fits

| Option | What you get | Limits that matter | Verdict |
| --- | --- | --- | --- |
| **AWS Free Tier (Free plan)** | $100 credit on sign-up + up to $100 more by completing activities; 30+ Always Free services; 6 months | Free plan sees a subset of services, no promo credits beyond Free Tier; account closes after 6 months or when credits run out | **Recommended.** Bedrock is available and the Bedrock playground activity earns credits |
| **AWS Free Tier (Paid plan)** | Full service catalog + the same up to $200 credits; pay-as-you-go after | You can be billed if you exceed credits; not available to accounts older than 6 months | Use if you need a service the Free plan hides (e.g. some deployment tooling) |
| **Builder Center Student Rewards** | Verified students: 12 months of Skill Builder premium, $10 at 7 badges, $20 at 14 badges ($30 total), plus a certification voucher | Requires student verification (SheerID) and badge grinding; stocks are limited | Stack it on top of Free Tier for extra credits |
| **AWS Educate** | Free courses, labs, a Starter Account | Starter Account has **no IAM, no Bedrock**, us-east-1 only | Good for learning, **not usable** for this project |
| **AWS Academy** | Instructor-provisioned labs and vouchers if your school is a member | Needs a course | Ask your department; useful if offered |
| **Organizer/hackathon credits** | Promotional credits applied to your account | Requires a Paid plan account (Free plan is ineligible for promo credits) | If the hackathon gives a code, upgrade to Paid first |

**Recommended path:** create one shared team account on the Free plan, earn the Bedrock
activity credit, and have one teammate complete Student Rewards separately if more runway
is needed. Do not build the product on an AWS Educate Starter Account.

## 2. Create and secure the account

1. Go to <https://aws.amazon.com/free/> and choose **Create free account**. Pick the
   **Free plan** unless you already know you need a paid-only service.
2. Sign in as the **root user** and enable MFA:
   **Security credentials → Assign MFA device**.
3. In **Billing and Cost Management → Budgets**, create two zero-spend budgets:
   - `terrasentry-alerts` — $1 threshold, email on actual and forecasted spend
   - `terrasentry-critical` — $20 threshold, email on actual spend
4. On the Console Home, open the **Explore AWS** widget, filter by *Earn AWS credits*, and
   complete the five activities. The **Amazon Bedrock** activity (submit a prompt in the
   text playground) is one of them and is worth ~$20 by itself.
5. Keep the account email in a shared password manager. Trial credits live with the
   account, not with a person.

## 3. Create a CLI identity

Never use root credentials for code.

1. **IAM → Users → Create user** → name `terrasentry-dev` → no console access.
2. Attach `AmazonBedrockFullAccess` for now. Deployment will use narrower task roles in
   M8; revisit then.
3. **Create access key → CLI**, download the CSV, and store it in the team password
   manager.
4. Install the AWS CLI v2 and configure it:

```bash
aws configure
# Access key / secret from the CSV
# region: us-east-1
# output: json

aws sts get-caller-identity        # should return the IAM user ARN
```

Use `AWS_PROFILE=terrasentry` if you keep multiple profiles; `.env` has an
`AWS_PROFILE=` slot for this.

## 4. Bedrock model access (the M3 blocker)

Anthropic models require a one-time use-case form per account (or per AWS Organization).

1. Set the region to **us-east-1** (Claude availability and cross-region profiles are
   best there; all regions are improving, but be deliberate).
2. **Bedrock → Model catalog → Anthropic → Claude Sonnet 4.5** → submit the use-case
   details when prompted. Access is granted immediately after submission.
3. Do the same for **Claude Haiku 4.5**.
4. Confirm the model IDs match `.env.example`:

```text
BEDROCK_MODEL_ORCHESTRATOR=global.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_MODEL_EXTRACTION=global.anthropic.claude-haiku-4-5-20251001-v1:0
```

The `global.` prefix is a cross-region inference profile, which keeps the demo working if
one region is throttled.

5. Smoke-test from the CLI (this is the exact call Strands will make under the hood):

```bash
aws bedrock-runtime converse \
  --region us-east-1 \
  --model-id global.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --messages '[{"role":"user","content":[{"text":"reply with the single word ok"}]}]'
```

Common failures:

| Error | Cause | Fix |
| --- | --- | --- |
| `AccessDeniedException` mentioning use case | Anthropic form not submitted | Open an Anthropic model in the Bedrock console and submit the form |
| `ValidationException: invalid model identifier` | Wrong region or model ID | Use us-east-1 and the IDs above |
| `ThrottlingException` | Account-level quota or spike | Retry, lower concurrency, or switch the `global.` profile |
| `UnrecognizedClientException` | Bad/expired access key | Recreate the IAM access key |

## 5. What this costs

Bedrock is pay-per-token; there is no free model tier, but the credits cover the demo
comfortably.

- Claude Sonnet 4.5: roughly **$3 per million input tokens / $15 per million output**
- Claude Haiku 4.5: roughly **$1 / $5** per million tokens
- A 50-record batch with retrieval + verification is on the order of a few hundred
  thousand tokens, so the batch costs a few dollars at most — and far less if the
  deterministic reference pipeline (which makes no model calls) is used for volume.
- Prefer Haiku for extraction, Sonnet for supervision/verification, and cache every
  external response so rehearsal runs cost nothing.

## 6. Guardrails for later milestones (M4/M8)

| Service | Free situation | Guidance |
| --- | --- | --- |
| **S3** | 5 GB Always Free, 12-month extras | Artifacts, raw payloads, DDS files. Set lifecycle expiry on scratch prefixes. |
| **CloudFront** | 1 TB egress + 10M requests Always Free | Front the web app in M8. |
| **RDS PostgreSQL** | Free-tier offers vary; Aurora Serverless v2 is **not** free | Prefer Neon free tier for dev; for the demo either a small `db.t4g.micro` with a hard stop or a container-scoped Postgres. Delete the instance after the demo. |
| **ECS Fargate / ALB** | No free tier; ALB bills hourly | Costliest part of M8. Keep one service at desired-count 1 and tear it down the same day. App Runner is an alternative but also bills. |
| **ElastiCache Redis** | No free tier | Use local Redis + `--appendonly yes` for the demo, or Upstash Redis (free tier ~500K commands/month). |
| **NAT Gateway** | Billed hourly + per GB | Avoid it in VPC designs; use VPC endpoints or public subnets for the demo. |
| **CloudWatch Logs** | 5 GB ingest free tier (verify) | Set 7-day retention; never log full payloads. |

**Teardown checklist after any cloud demo:** delete ALB, ECS services/clusters, RDS,
NAT gateways, ECR images, and any idle CloudWatch alarms. Check **Billing → Cost Explorer**
the next day for stragglers.

## 7. Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Free plan hides a service you need | Upgrade to Paid plan (credits carry over) |
| Credits not visible | Billing → Credits page; activity credits post after completion |
| Everything is `AccessDenied` | You are on an Educate Starter Account or a restricted IAM policy |
| Bills appeared despite credits | Usage outside credit-eligible services (support plans, marketplace) |
| Wrong region resources | Always run `aws configure get region` before debugging code |

## Links

- AWS Free Tier: <https://aws.amazon.com/free/>
- Earning additional credits: <https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier.html>
- Builder Center Student Rewards: <https://builder.aws.com/>
- Bedrock model access: <https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html>
- Bedrock pricing: <https://aws.amazon.com/bedrock/pricing/>
- AWS CLI install: <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html>
