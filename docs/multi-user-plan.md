# Plan: Multi-User Access Infrastructure

## Context

The bot is personal today — no authentication, no rate limiting, no user tracking. Before selling access to neighbors, we need: user management, invite-code onboarding, per-user rate limits, admin commands, and per-user building preference. All within AWS free tier.

---

## DynamoDB Single-Table Design

**Table: `stvg-helper`** — provisioned mode (25 RCU/25 WCU = free forever)

| PK | SK | Key attributes | Purpose |
|---|---|---|---|
| `USER#<telegram_id>` | `PROFILE` | `name`, `telegram_username`, `tier`, `building`, `status`, `created_at` | User profile |
| `USER#<telegram_id>` | `USAGE#<YYYY-MM-DD>` | `parking_count`, `claude_count`, `ttl` | Daily usage (auto-deleted via TTL) |
| `INVITE#<code>` | `INVITE` | `tier`, `created_at` | Single-use invite code |

- **TTL** on `USAGE#` items (today + 48h) → auto-cleanup, no cron needed
- **No GSI** — `Scan` is fine for <100 users

**User statuses:** `active` | `blocked`
**Tiers and limits:**

| Tier | Parking checks/day | Claude messages/day |
|---|---|---|
| `standard` | 5 | 20 |
| `premium` | 20 | 50 |
| `admin` | unlimited | unlimited |

---

## Onboarding: Invite Codes

1. Admin sends `/invite` (or `/invite premium`) → bot generates a random 8-char code, stores `INVITE#<code>` in DynamoDB, replies with the code
2. Admin shares the code with a neighbor
3. Neighbor sends `/start <CODE>` → bot validates code, creates `USER#` with `status=active` and the code's tier, deletes the invite item, shows the main menu
4. `/start` without a code from an unknown user → "This bot requires an invite code."
5. `/start` from an existing active user → normal greeting with menu

---

## Files to Change

### 1. New file: `terraform/dynamodb.tf`

```hcl
resource "aws_dynamodb_table" "bot" {
  name           = "stvg-helper"
  billing_mode   = "PROVISIONED"
  read_capacity  = 25
  write_capacity = 25
  hash_key       = "PK"
  range_key      = "SK"

  attribute { name = "PK"; type = "S" }
  attribute { name = "SK"; type = "S" }

  ttl { attribute_name = "ttl"; enabled = true }
}
```

### 2. `terraform/ssm.tf` — add admin Telegram ID parameter

```hcl
resource "aws_ssm_parameter" "admin_telegram_id" {
  name  = "/stvg-helper/admin-telegram-id"
  type  = "SecureString"
  value = "PLACEHOLDER"
  lifecycle { ignore_changes = [value] }
}
```

### 3. `terraform/iam.tf` — add DynamoDB + new SSM to policy

Add to `data.aws_iam_policy_document.lambda_permissions`:

```hcl
statement {
  sid     = "DynamoDB"
  actions = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Scan"]
  resources = [aws_dynamodb_table.bot.arn]
}
```

Add `aws_ssm_parameter.admin_telegram_id.arn` to the existing SSM statement's `resources` list.

### 4. `terraform/lambda.tf` — add env vars

Add to the `environment.variables` block:

```hcl
DYNAMODB_TABLE     = aws_dynamodb_table.bot.name
SSM_ADMIN_ID_PARAM = aws_ssm_parameter.admin_telegram_id.name
```

### 5. New file: `bot/users.py` (~200 lines)

Core module for all user operations:

- **`User` dataclass** — `telegram_id`, `name`, `telegram_username`, `tier`, `building`, `status`, `created_at`
- **`TIER_LIMITS`** dict — maps tier name → `{"parking": N, "claude": N}`
- **`get_admin_id()`** — LRU-cached SSM fetch
- **`get_user(telegram_id) -> User | None`** — DynamoDB GetItem
- **`create_user(telegram_id, name, username, tier) -> User`** — DynamoDB PutItem with `status=active`
- **`update_user(telegram_id, **fields)`** — DynamoDB UpdateItem
- **`check_rate_limit(telegram_id, action, tier) -> (allowed, count, limit)`** — atomic `ADD` on `USAGE#<today>` item, returns whether under limit
- **`create_invite(tier) -> str`** — generates random 8-char code, stores `INVITE#<code>`
- **`redeem_invite(code) -> str | None`** — GetItem + DeleteItem, returns tier if valid
- **`require_auth` decorator** — wraps handlers, checks user exists and is `active`, injects `User` into `context.user_data["db_user"]`. Caches user lookups in-memory for 60s to avoid DynamoDB on every message. Unknown users get "invite code required" reply.
- **Admin command handlers** (all verify `from_user.id == get_admin_id()`):
  - `admin_invite(update, context)` — `/invite [tier]` → generate code, reply with it
  - `admin_block(update, context)` — `/block <user_id>` → set status=blocked
  - `admin_users(update, context)` — `/users` → Scan all profiles, list them
  - `admin_set_tier(update, context)` — `/set_tier <user_id> <tier>`
  - `admin_usage(update, context)` — `/usage [user_id]` → show today's counts
- **`set_building_handler(update, context)`** — `/set_building` → presents keyboard with building names from `PARKING_CAMERAS`, saves choice to DynamoDB

### 6. `bot/handler.py` — integrate auth + register commands

- Import `require_auth`, admin handlers, `set_building_handler`, `get_user`, `create_user`, `redeem_invite` from `users`
- **`start_command`** — handle `/start <CODE>` invite flow:
  - No args + unknown user → "This bot requires an invite code"
  - Has code arg → `redeem_invite(code)` → if valid, `create_user(...)` with redeemed tier → show menu
  - Existing active user → show menu as before
  - Existing blocked user → silent ignore
- **`menu_button_handler`** — wrap with `@require_auth`
- **`claude_handler`** — wrap with `@require_auth`, add rate limit check (`check_rate_limit(user_id, "claude", tier)`)
- **`build_application()`** — register new command handlers:
  - `/invite`, `/block`, `/users`, `/set_tier`, `/usage` (admin)
  - `/set_building` (all users)

### 7. `bot/parking.py` — rate limit + building priority

- Import `check_rate_limit` from `users`
- At top of `parking_handler`: extract `db_user` from `context.user_data`, call `check_rate_limit(user_id, "parking", tier)` → if not allowed, reply with limit message and return
- If `user.building` is set, reorder `PARKING_CAMERAS` to search that building first (simple sort: user's building gets priority 0, rest keep original order)

### 8. New file: `tests/test_users.py`

Mock `boto3.resource("dynamodb")` throughout. Key test cases:

- `TestGetUser`: found, not found
- `TestCreateUser`: correct defaults
- `TestCheckRateLimit`: under limit → allowed, at limit → blocked, different day → fresh counter
- `TestRedeemInvite`: valid code → returns tier + deletes, invalid → returns None
- `TestRequireAuth`: active user → handler called, blocked → silent, unknown → invite message, cached user → no DynamoDB call
- `TestAdminCommands`: non-admin → ignored, invite generates code, block sets status

---

## Deployment Sequence

1. `terraform apply` — creates DynamoDB table + new SSM param + updated IAM
2. `aws ssm put-parameter --name "/stvg-helper/admin-telegram-id" --value "YOUR_TELEGRAM_ID" --type SecureString --overwrite`
3. `make release` — deploy updated code

## Verification

1. `make lint` — black, isort, mypy clean
2. `make test` — all tests pass (existing + new `test_users.py`)
3. Manual test after deploy:
   - Message the bot from a non-registered account → "invite code required"
   - Send `/invite` from admin → get code
   - Send `/start <CODE>` from test account → activated, menu shown
   - Press "Parking" 6 times → 6th time shows limit message
   - `/block <id>` from admin → user gets no response
   - `/users` from admin → lists all users
   - `/set_building` → pick a building → parking searches that building first