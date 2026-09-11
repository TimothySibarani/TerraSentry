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

Never use root credentials for code. Use IAM Identity Center (SSO) for people and IAM
roles for workloads; a long-lived access key is the fallback for a single hackathon
account, and it should be scoped and rotated.

The app only needs to invoke the two configured models, so do **not** attach
`AmazonBedrockFullAccess`. Create a policy from this template, replacing
`<account-id>`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeConfiguredModels",
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:*:<account-id>:inference-profile/*"
      ]
    },
    {
      "Sid": "DiscoverModels",
      "Effect": "Allow",
      "Action": [
        "bedrock:ListFoundationModels",
        "bedrock:GetFoundationModel",
        "bedrock:ListInferenceProfiles",
        "bedrock:GetInferenceProfile"
      ],
      "Resource": "*"
    }
  ]
}
```

Narrow `InvokeConfiguredModels` to the exact model/profile ARNs once you have picked
them. Cross-region profiles are allowed for all regions here because the profile may
route to a foundation model outside your home region.

1. **IAM → Policies → Create policy** with the JSON above.
2. **IAM → Users → Create user** → name `terrasentry-dev` → no console access →
   attach only that policy.
3. **Create access key → CLI**, download the CSV, and store it in the team password
   manager. Rotate it before the demo and delete it afterwards. (If your account can
   use IAM Identity Center, run `aws configure sso` instead and skip the key.)
4. Install the AWS CLI v2 and configure it:

```bash
aws configure            # or: aws configure sso
# region: us-east-1
# output: json

aws sts get-caller-identity        # should return the user/role ARN
```

Enable **CloudTrail** (management events are free) so every Bedrock call is auditable.

Use `AWS_PROFILE=terrasentry` if you keep multiple profiles; `.env` has an
`AWS_PROFILE=` slot for this.

## 4. Bedrock model access (the M3 blocker)

Pick the model you want for each agent role, request access to both, and set the ids in
`.env`; nothing in the repo hardcodes a model.

1. Set the region deliberately (cross-region inference profiles are available in a subset
   of regions; pick one and stay there).
2. **Bedrock → Model catalog** → choose the model for orchestration and verification, then
   choose the model for high-volume extraction. Open each one and submit the use-case
   details if prompted; access is usually granted immediately after submission.
3. Put the exact ids (or inference-profile ids) in `.env`:

```text
BEDROCK_MODEL_ORCHESTRATOR=<your orchestration/verification model or profile id>
BEDROCK_MODEL_EXTRACTION=<your extraction model or profile id>
```

A `global.` (or other cross-region) inference profile keeps the demo working if one region
is throttled; use the console's "Inference profile" ids when available. The app fails with a
clear `MissingModelError` if either variable is unset.

4. Verify with the repo preflight: it builds both roles exactly like the agent runtime
   (adaptive retries, timeouts) and pings each model with a 16-token output cap:

```bash
uv run python -m terrasentry_core.agents.preflight
```

   Exit code 0 means the live path is ready. If it fails, the raw Converse call is a
   useful layer-1 connectivity check:

```bash
aws bedrock-runtime converse \
  --region us-east-1 \
  --model-id "$BEDROCK_MODEL_EXTRACTION" \
  --inference-config '{"maxTokens": 16}' \
  --messages '[{"role":"user","content":[{"text":"reply with the single word ok"}]}]'
```

   Discover the exact ids when the console is unclear:

```bash
aws bedrock list-foundation-models --query "modelSummaries[].modelId" --output text
aws bedrock list-inference-profiles --query "inferenceProfileSummaries[].inferenceProfileId" --output text
```

Common failures:

| Error | Cause | Fix |
| --- | --- | --- |
| `AccessDeniedException` mentioning use case | Provider use-case form not submitted | Open the model in the Bedrock console and submit the form |
| `AccessDeniedException` without use case | IAM policy missing invoke actions | Attach the policy from section 3 |
| `ValidationException: invalid model identifier` | Wrong region or model id | Use the region you enabled and the exact id/profile from the console |
| `ValidationException: ... on-demand throughput isn't supported` | Model requires an inference profile | Use the `us.`/`eu.`/`global.` profile id from `list-inference-profiles` |
| `ThrottlingException` | Account-level quota or spike | Adaptive retries are already on; lower concurrency, switch to a cross-region profile, or request a quota increase |
| `UnrecognizedClientException` | Bad/expired access key | Recreate or rotate the IAM access key |

## 5. What this costs

Bedrock is pay-per-token; there is no free model tier, but the credits cover the demo
comfortably.

- Cost depends on the models you choose; check Bedrock pricing for the current
  per-million-token rates before the batch rehearsal.
- A 50-record batch with retrieval + verification is on the order of a few hundred
  thousand tokens, so the batch costs a few dollars at most — and far less if the
  deterministic reference pipeline (which makes no model calls) is used for volume.
- Prefer the cheaper model for extraction, the stronger model for supervision/verification,
  and cache every external response so rehearsal runs cost nothing.
- `AGENT_MAX_TOKENS` is set explicitly on purpose: Bedrock reserves
  `input + max_tokens` quota per request, so an unset max defaults to the model maximum
  and can throttle the batch many times earlier. Right-size it with CloudWatch
  `OutputTokenCount` once the 50-record rehearsal has run.
- Prompt caching stays off (`BEDROCK_PROMPT_CACHE=off`) because the agents' static
  prefixes are below the model minimums (Sonnet 4.5: 1,024 tokens; Haiku 4.5: 4,096),
  where cache points are silently ignored. Flip it to `auto` (or `anthropic` for opaque
  ARN profile ids) only if prompts grow past the minimum and are reused; cache writes
  cost 25% more, cache reads 90% less.
- The Bedrock `flex` service tier is the batch-cost lever for M6 if wall-clock allows
  it; the demo path stays on the default tier.

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

**Model invocation logging:** off by default. If you enable it, CloudWatch Logs/S3
capture full prompts and responses — fine for the synthetic seed data, but for real
supplier documents encrypt the destination with KMS, restrict access, or leave it off.

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
