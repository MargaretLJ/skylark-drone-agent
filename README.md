# 🚁 Skylark Drone Operations AI Agent

AI-powered drone fleet coordinator using **Google Gemini (FREE)** + Streamlit + Google Sheets.

## Setup in 15 Minutes

### Step 1 — Install
```bash
git clone <your-repo>
cd skylark-drone-agent
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
mkdir .streamlit
cp .streamlit/secrets.toml.template .streamlit/secrets.toml
```

### Step 2 — Get Your FREE Gemini API Key
1. Go to **https://aistudio.google.com/app/apikey**
2. Sign in with Google → "Create API Key"
3. Copy the key → paste into `.streamlit/secrets.toml` as `gemini_api_key`
4. **No credit card needed. Free tier is sufficient.**

### Step 3 — Google Sheets Setup
1. Go to **https://console.cloud.google.com** → Create project (name: skylark)
2. Search "Google Sheets API" → Enable
3. Search "Google Drive API" → Enable
4. Go to Credentials → Create Credentials → Service Account → create → Download JSON
5. Create a Google Sheet with 3 tabs: `pilot_roster`, `drone_fleet`, `missions`
6. Paste your CSV data into each tab (headers must match exactly)
7. Open the JSON file → find `client_email` → share your Google Sheet with that email (Editor)
8. Copy the Sheet ID from the URL (the long string between `/d/` and `/edit`)
9. Fill in `secrets.toml`: `sheet_id` and all `[gcp_service_account]` fields from the JSON

### Step 4 — Run
```bash
streamlit run app.py
```
Visit `http://localhost:8501`

---

## Google Sheet Column Headers (must match exactly)

**pilot_roster tab:**
```
pilot_id, name, skills, certifications, location, status, current_assignment, available_from, daily_rate_inr
```

**drone_fleet tab:**
```
drone_id, model, capabilities, status, location, current_assignment, maintenance_due, weather_resistance
```

**missions tab:**
```
project_id, client, location, required_skills, required_certs, start_date, end_date, priority, mission_budget_inr, weather_forecast, assigned_pilot, assigned_drone, status
```

**Note:** Skills/certs use semicolons: `Mapping; Survey` | Weather resistance: `IP43 (Rain)` or `None (Clear Sky Only)`

---

## Deploy FREE on Streamlit Cloud

1. Push to GitHub (`.streamlit/secrets.toml` must be in `.gitignore`)
2. Go to **https://share.streamlit.io** → Connect GitHub repo
3. Set main file: `app.py`
4. Click **Advanced settings** → paste your entire `secrets.toml` content into "Secrets"
5. Click Deploy — live in ~2 minutes!

---

## Features

| Feature | Details |
|---|---|
| 💬 AI Chat | Natural language queries via Gemini 1.5 Flash |
| 👥 Roster | Query/filter pilots; update status → sync to Sheets |
| 🚁 Drones | Fleet inventory; maintenance alerts; weather filter |
| 📋 Missions | Live mission board with priority color coding |
| ⚠️ Conflicts | Auto-detects all 6 edge cases (see below) |

## Edge Cases Detected

1. 🔴 **Pilot double-booking** — same pilot assigned to overlapping mission dates
2. 🔴 **Cert mismatch** — pilot lacks required certifications for mission
3. 🟠 **Budget overrun** — `daily_rate × days > mission_budget`
4. 🔴 **Drone in maintenance** — deployed drone is in maintenance
5. 🔴 **Weather risk** — `None (Clear Sky Only)` drone assigned to Rainy mission
6. 🟠 **Location mismatch** — pilot and assigned drone in different cities

## Project Files

```
skylark-drone-agent/
├── app.py              ← Streamlit UI
├── agent.py            ← Gemini agent + agentic tool loop
├── tools.py            ← 14 tool functions + all edge case logic
├── sheets.py           ← Google Sheets read/write with CSV fallback
├── requirements.txt
├── pilot_roster.csv    ← Sample data (fallback when Sheets not configured)
├── drone_fleet.csv
├── missions.csv
├── .gitignore
└── .streamlit/
    └── secrets.toml.template
```
