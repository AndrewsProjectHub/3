# MD-102 Daily Study Email Webhook

A FastAPI webhook that queries 5 Notion databases and generates a formatted daily study email for MD-102 exam prep. Designed to be called by Zapier on a schedule.

## Architecture

```
┌─────────────┐      POST /webhook       ┌──────────────────┐
│   Zapier    │  ────────────────────▶   │   This Webhook   │
│  (Scheduler)│                          │    (FastAPI)     │
└─────────────┘                          └────────┬─────────┘
      ▲                                           │
      │                                           ▼
      │                                  ┌──────────────────┐
      │    {should_send, subject, body}  │  Notion API      │
      └────────────────────────────────  │  (5 Databases)   │
                                         └──────────────────┘
```

## Quick Start

### 1. Environment Variables

Create a `.env` file (or set in your hosting platform):

```bash
# Notion Integration Token (from https://www.notion.so/my-integrations)
NOTION_TOKEN=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Your shared secret for webhook auth
AUTH_TOKEN=your-secure-random-secret-here

# Notion Database IDs (32-character hex, no dashes)
PLAN_DB_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OBJECTIVES_DB_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
RESOURCES_DB_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PRACTICE_DB_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
MISTAKES_DB_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 2. Get Your Notion Database IDs

1. Open each database in Notion as a full page
2. Copy the URL: `https://notion.so/workspace/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx?v=...`
3. The 32-character hex string before `?v=` is your database ID
4. Remove dashes if present

### 3. Share Databases with Integration

In Notion, for **each** of the 5 databases:
1. Click `•••` → `Connections` → Add your integration

---

## Deployment: Render (Recommended)

### Step-by-Step

1. **Push to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   gh repo create md102-study-webhook --private --push
   ```

2. **Create Render Account**
   - Go to [render.com](https://render.com) and sign up

3. **New Web Service**
   - Click "New +" → "Web Service"
   - Connect your GitHub repo
   - Configure:
     - **Name**: `md102-study-webhook`
     - **Runtime**: Python 3
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

4. **Add Environment Variables**
   In Render dashboard → Environment:
   ```
   NOTION_TOKEN = secret_xxx...
   AUTH_TOKEN = your-secret-here
   PLAN_DB_ID = xxx...
   OBJECTIVES_DB_ID = xxx...
   RESOURCES_DB_ID = xxx...
   PRACTICE_DB_ID = xxx...
   MISTAKES_DB_ID = xxx...
   ```

5. **Deploy**
   - Click "Create Web Service"
   - Wait for build (2-3 min)
   - Your URL: `https://md102-study-webhook.onrender.com`

### Render Free Tier Notes
- Spins down after 15 min of inactivity
- First request after sleep takes ~30 seconds (cold start)
- For reliable daily emails, consider Render paid tier ($7/mo) or use Zapier's retry feature

---

## Alternative: Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and init
railway login
railway init

# Deploy
railway up

# Set env vars
railway variables set NOTION_TOKEN=secret_xxx
railway variables set AUTH_TOKEN=your-secret
railway variables set PLAN_DB_ID=xxx
# ... etc
```

---

## Alternative: Fly.io

1. **Create `fly.toml`**:
```toml
app = "md102-study-webhook"
primary_region = "iad"

[build]
  builder = "paketobuildpacks/builder:base"

[env]
  PORT = "8080"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
```

2. **Deploy**:
```bash
fly launch
fly secrets set NOTION_TOKEN=secret_xxx AUTH_TOKEN=your-secret ...
fly deploy
```

---

## Testing with cURL

### Health Check
```bash
curl https://your-webhook-url.onrender.com/
# Expected: {"status":"healthy","service":"md102-study-webhook"}
```

### Test Webhook (Missing Auth)
```bash
curl -X POST https://your-webhook-url.onrender.com/webhook \
  -H "Content-Type: application/json" \
  -d '{"run_date": "2025-01-02"}'

# Expected: 401 {"error":"Unauthorized: Invalid or missing X-AUTH-TOKEN"}
```

### Test Webhook (Valid Auth)
```bash
curl -X POST https://your-webhook-url.onrender.com/webhook \
  -H "Content-Type: application/json" \
  -H "X-AUTH-TOKEN: your-secret-here" \
  -d '{"run_date": "2025-01-02", "timezone": "America/New_York"}'

# Expected on success:
# {
#   "should_send": true,
#   "subject": "MD-102 — Daily Study Brief (🔥 CRITICAL)",
#   "body": "MD-102 DAILY STUDY BRIEF\nDate: 2025-01-02\n...",
#   "reason": "ok",
#   "debug": {
#     "date": "2025-01-02",
#     "objectives_count": 3,
#     "resources_count": 5,
#     "practice_test_found": false,
#     "mistakes_found": 2
#   }
# }

# Expected if no plan for date:
# {"should_send": false, "subject": "", "body": "", "reason": "no_plan", ...}

# Expected if sessions completed:
# {"should_send": false, "subject": "", "body": "", "reason": "completed", ...}
```

### Local Testing
```bash
# Set env vars
export NOTION_TOKEN=secret_xxx
export AUTH_TOKEN=test123
export PLAN_DB_ID=xxx
# ... etc

# Run locally
pip install -r requirements.txt
python main.py

# Test against localhost
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-AUTH-TOKEN: test123" \
  -d '{"run_date": "2025-01-02"}'
```

---

## Zapier Setup

### Step 1: Create Schedule Trigger
1. New Zap → Trigger: **Schedule by Zapier**
2. Choose "Every Day"
3. Set time (e.g., 6:00 AM)
4. Timezone: America/New_York

### Step 2: Add Formatter (Get Today's Date)
1. Action: **Formatter by Zapier**
2. Event: **Date/Time**
3. Transform: **Format**
4. Input: `{{zap_meta_human_now}}`
5. To Format: `YYYY-MM-DD`
6. To Timezone: `America/New_York`

### Step 3: Add Webhook POST
1. Action: **Webhooks by Zapier**
2. Event: **POST**
3. URL: `https://your-webhook-url.onrender.com/webhook`
4. Payload Type: `json`
5. Data:
   - `run_date`: (use output from Step 2)
   - `timezone`: `America/New_York`
6. Headers:
   - `X-AUTH-TOKEN`: `your-secret-here`

### Step 4: Add Filter
1. Action: **Filter by Zapier**
2. Only continue if:
   - Field: `should_send` from Step 3
   - Condition: `(Boolean) Is true`

### Step 5: Send Email
1. Action: **Email by Zapier** (or Gmail, Outlook, etc.)
2. To: your email
3. Subject: `{{subject}}` from Step 3
4. Body: `{{body}}` from Step 3

### Complete Zap Flow
```
[Schedule] → [Format Date] → [Webhook POST] → [Filter should_send] → [Send Email]
```

---

## Notion Database Schema

### A) MD-102 60-Day Plan
| Property | Type | Example |
|----------|------|---------|
| Date | Date | 2025-01-02 |
| Phase | Text | Phase 2: Deep Dive |
| Focus Priority | Select | 🔥 CRITICAL |
| Session 1 (1 hr) – Learn | Text | Study Intune enrollment... |
| Session 1 Resources (IDs/URLs) | Text | R04, R51 |
| Session 1 Done | Checkbox | ☐ |
| Session 2 (1 hr) – Lab/Practice | Text | Configure autopilot... |
| Session 2 Resources (IDs/URLs) | Text | R08, R12 |
| Session 2 Done | Checkbox | ☐ |
| Focus objectives (IDs) | Text | P-ENTRA-01, P-ENTRA-02 |

### B) MD-102 Objectives
| Property | Type | Example |
|----------|------|---------|
| Objective ID | Title/Text | P-ENTRA-01 |
| Objective | Text | Configure Entra ID join |
| Exam Area | Select | Deploy Windows |
| Skill Group | Select | Plan deployment |
| Priority | Select | High |
| Primary Resources (IDs) | Text | R01, R04 |

### C) MD-102 Resources
| Property | Type | Example |
|----------|------|---------|
| Resource ID | Title/Text | R04 |
| Name | Text | Microsoft Learn: Intune |
| Type | Select | Documentation |
| URL | URL | https://learn.microsoft.com/... |
| Why it matters | Text | Official source for... |

### D) MD-102 Practice Tests
| Property | Type | Example |
|----------|------|---------|
| Date | Date | 2025-01-02 |
| Provider | Select | MeasureUp |
| Test | Text | Practice Test 1 |
| Primary Focus | Text | Deployment methods |
| Notes | Text | Focus on Autopilot |

### E) Mistake Bank
| Property | Type | Example |
|----------|------|---------|
| Resolved | Checkbox | ☐ |
| Objective ID | Text | P-ENTRA-01 |
| Mistake Summary | Text | Confused hybrid vs cloud |
| Correct Rule | Text | Hybrid requires on-prem AD |
| Recognition Tip | Text | Look for "on-premises" |

---

## Response Reference

### Success (should send)
```json
{
  "should_send": true,
  "subject": "MD-102 — Daily Study Brief (🔥 CRITICAL)",
  "body": "MD-102 DAILY STUDY BRIEF\nDate: 2025-01-02\n...",
  "reason": "ok",
  "debug": {
    "date": "2025-01-02",
    "objectives_count": 3,
    "resources_count": 5,
    "practice_test_found": true,
    "mistakes_found": 2
  }
}
```

### No Plan Found
```json
{
  "should_send": false,
  "subject": "",
  "body": "",
  "reason": "no_plan",
  "debug": {"date": "2025-01-02", ...}
}
```

### Already Completed
```json
{
  "should_send": false,
  "subject": "",
  "body": "",
  "reason": "completed",
  "debug": {"date": "2025-01-02", ...}
}
```

### Auth Error (401)
```json
{
  "error": "Unauthorized: Invalid or missing X-AUTH-TOKEN"
}
```

---

## Troubleshooting

### "Notion API error: 400"
- Check database IDs are correct (32 hex chars, no dashes)
- Verify property names match exactly (case-sensitive)
- Ensure integration has access to all databases

### "no_plan" but plan exists
- Verify Date property format matches `YYYY-MM-DD`
- Check the date in Notion matches exactly

### Cold start timeouts
- Render free tier sleeps after 15 min
- Set Zapier timeout to 60 seconds
- Or upgrade to Render paid tier

### Objectives not found
- Check "Objective ID" property name exact match
- Verify IDs in plan match IDs in objectives DB

---

## Security Notes

1. **Never commit secrets** - Use environment variables
2. **Generate strong AUTH_TOKEN** - Use `openssl rand -hex 32`
3. **Notion token scope** - Only grant access to needed databases
4. **HTTPS only** - All hosting options enforce HTTPS

---

## License

MIT - Use freely for your exam prep!
