"""
app.py — Skylark Drone Operations AI Agent
Powered by Google Gemini (free) + Google Sheets sync
"""

import streamlit as st
import pandas as pd
from agent import chat
from tools import detect_all_conflicts, flag_maintenance_issues
from sheets import read_sheet

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Skylark Ops Control",
    page_icon="🚁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family: 'Syne', sans-serif; }
.stApp { background: #070b14; color: #dce7f5; }

[data-testid="stSidebar"] {
    background: #0b1120 !important;
    border-right: 1px solid #162035;
}

.brand {
    font-size: 1.15rem; font-weight: 800; color: #4fa3e8;
    letter-spacing: 2px; text-transform: uppercase;
    font-family: 'IBM Plex Mono', monospace;
}
.brand-sub { font-size: 0.65rem; color: #3a5070; letter-spacing: 3px; margin-top: 2px; }

.stat-card {
    background: #0d1828; border: 1px solid #162035;
    border-radius: 8px; padding: 14px 16px; text-align: center;
    margin-bottom: 8px;
}
.stat-n { font-size: 1.8rem; font-weight: 800; line-height: 1; }
.stat-l { font-size: 0.62rem; color: #3a5070; text-transform: uppercase; letter-spacing: 2px; margin-top: 3px; }
.green { color: #2dd4a0; } .red { color: #f46060; } .yellow { color: #f5c242; } .blue { color: #4fa3e8; }

.msg-user {
    background: #0f2240; border: 1px solid #1a3560;
    border-radius: 14px 14px 4px 14px;
    padding: 12px 16px; margin: 10px 0; margin-left: 15%;
    font-size: 0.88rem; line-height: 1.6;
}
.msg-bot {
    background: #0b1424; border: 1px solid #162035;
    border-radius: 4px 14px 14px 14px;
    padding: 14px 18px; margin: 10px 0; margin-right: 10%;
    font-size: 0.88rem; line-height: 1.75;
    white-space: pre-wrap;
}

.conflict-Critical {
    background: #1f0808; border-left: 4px solid #ef4444;
    border-radius: 6px; padding: 10px 14px; margin: 5px 0; font-size: 0.83rem;
}
.conflict-High {
    background: #1f1008; border-left: 4px solid #f97316;
    border-radius: 6px; padding: 10px 14px; margin: 5px 0; font-size: 0.83rem;
}
.conflict-Medium {
    background: #1a1808; border-left: 4px solid #f5c242;
    border-radius: 6px; padding: 10px 14px; margin: 5px 0; font-size: 0.83rem;
}

.chip {
    display: inline-block; padding: 2px 10px; border-radius: 20px;
    font-size: 0.72rem; font-weight: 600; margin: 2px;
}
.chip-available { background: #063020; color: #2dd4a0; }
.chip-assigned { background: #0d1f3f; color: #60a5fa; }
.chip-leave { background: #2a2005; color: #f5c242; }
.chip-unavailable { background: #200808; color: #f46060; }
.chip-maintenance { background: #200808; color: #f46060; }
.chip-deployed { background: #0d1f3f; color: #60a5fa; }

.section-label {
    font-size: 0.62rem; text-transform: uppercase; letter-spacing: 3px;
    color: #2a3f5f; font-family: 'IBM Plex Mono', monospace; margin: 16px 0 8px 0;
}

.stTextInput input {
    background: #0b1424 !important; border: 1px solid #162035 !important;
    color: #dce7f5 !important; border-radius: 8px !important; font-family: 'Syne', sans-serif !important;
}
.stButton > button {
    background: #1a3a70 !important; color: #a0c4f0 !important;
    border: 1px solid #1e4080 !important; border-radius: 8px !important;
    font-family: 'Syne', sans-serif !important; font-weight: 600 !important;
    transition: all 0.15s !important;
}
.stButton > button:hover { background: #254d9a !important; color: #fff !important; }
.stTabs [data-baseweb="tab-list"] { background: #0b1120; border-radius: 8px; gap: 2px; }
.stTabs [data-baseweb="tab"] { color: #3a5070 !important; font-weight: 600; }
.stTabs [aria-selected="true"] { background: #0f2240 !important; color: #4fa3e8 !important; border-radius: 6px; }
hr { border-color: #162035 !important; }
[data-testid="stDataFrame"] { border: 1px solid #162035; border-radius: 8px; }
.stMarkdown p { color: #8aaac8; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []       # Gemini history
if "display" not in st.session_state:
    st.session_state.display = []        # (role, text) for UI

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="brand">🚁 SKYLARK</div><div class="brand-sub">OPERATIONS CONTROL</div>', unsafe_allow_html=True)
    st.markdown("---")

    # Live stats
    try:
        pdf = read_sheet("pilot_roster")
        ddf = read_sheet("drone_fleet")
        mdf = read_sheet("missions")

        avail_p = len(pdf[pdf["status"] == "Available"]) if not pdf.empty else 0
        avail_d = len(ddf[ddf["status"] == "Available"]) if not ddf.empty else 0
        maint_d = len(ddf[ddf["status"] == "Maintenance"]) if not ddf.empty else 0
        total_m = len(mdf) if not mdf.empty else 0

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f'<div class="stat-card"><div class="stat-n green">{avail_p}</div><div class="stat-l">Pilots Ready</div></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="stat-card"><div class="stat-n {"red" if maint_d else "green"}">{maint_d}</div><div class="stat-l">In Maint.</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="stat-card"><div class="stat-n green">{avail_d}</div><div class="stat-l">Drones Ready</div></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="stat-card"><div class="stat-n blue">{total_m}</div><div class="stat-l">Missions</div></div>', unsafe_allow_html=True)
    except:
        st.caption("Stats unavailable")

    st.markdown("---")
    st.markdown('<div class="section-label">Quick Actions</div>', unsafe_allow_html=True)

    quick = [
        ("⚠️", "Run full conflict scan"),
        ("🛠️", "Show maintenance alerts"),
        ("📋", "Show all missions and assignments"),
        ("👥", "List available pilots in Bangalore"),
        ("🌧️", "Which drones can fly in rainy weather?"),
        ("💰", "Match pilots to PRJ001"),
        ("🚁", "Match drones to PRJ002"),
        ("🔁", "Who is currently assigned to what?"),
    ]
    for icon, label in quick:
        if st.button(f"{icon} {label}", use_container_width=True, key=f"q_{label}"):
            st.session_state._pending = label

    st.markdown("---")
    if st.button("🗑️ Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.display = []
        st.rerun()

    st.markdown('<div style="font-size:0.65rem;color:#2a3f5f;text-align:center;margin-top:8px;">Powered by Gemini · Google Sheets Sync</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────
# MAIN AREA
# ─────────────────────────────────────────────
st.markdown("""
<div style="background:linear-gradient(135deg,#0b1628,#0f2040);border:1px solid #162035;
border-radius:12px;padding:18px 24px;margin-bottom:18px;">
<span style="font-size:1.5rem;font-weight:800;color:#4fa3e8;letter-spacing:-0.5px;">
🚁 Skylark Drone Operations — AI Coordinator</span><br>
<span style="font-size:0.72rem;color:#2a4060;font-family:'IBM Plex Mono',monospace;letter-spacing:2px;">
LIVE DATA · GEMINI-POWERED · GOOGLE SHEETS SYNC</span>
</div>
""", unsafe_allow_html=True)

tab_chat, tab_pilots, tab_drones, tab_missions, tab_conflicts = st.tabs([
    "💬 Chat", "👥 Pilots", "🚁 Drones", "📋 Missions", "⚠️ Conflicts"
])

# ── CHAT ──
with tab_chat:
    if not st.session_state.display:
        st.markdown("""
        <div style="text-align:center;padding:50px 20px;color:#2a4060;">
        <div style="font-size:2.5rem;">🚁</div>
        <div style="font-size:1rem;font-weight:700;color:#3a6090;margin-top:10px;">Skylark Operations AI</div>
        <div style="font-size:0.82rem;margin-top:6px;color:#2a3f5f;">
        Ask about pilots, drones, missions, or conflicts.<br>
        Try: <em style="color:#4fa3e8">"Run a full conflict scan"</em> or <em style="color:#4fa3e8">"Match pilots to PRJ001"</em>
        </div></div>
        """, unsafe_allow_html=True)

    for role, text in st.session_state.display:
        css = "msg-user" if role == "user" else "msg-bot"
        icon = "🧑‍✈️" if role == "user" else "🤖"
        st.markdown(f'<div class="{css}">{icon} {text}</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_i, col_s = st.columns([5, 1])
    with col_i:
        user_input = st.text_input("msg", placeholder="Ask anything about pilots, drones, missions...",
                                   label_visibility="collapsed", key="chat_input")
    with col_s:
        send = st.button("Send →", use_container_width=True)

    # Handle pending quick action
    if "_pending" in st.session_state:
        prompt = st.session_state._pending
        del st.session_state._pending
        with st.spinner("🤖 Thinking..."):
            resp, hist = chat(st.session_state.messages, prompt)
            st.session_state.messages = hist
            st.session_state.display.append(("user", prompt))
            st.session_state.display.append(("bot", resp))
        st.rerun()

    if send and user_input:
        with st.spinner("🤖 Thinking..."):
            resp, hist = chat(st.session_state.messages, user_input)
            st.session_state.messages = hist
            st.session_state.display.append(("user", user_input))
            st.session_state.display.append(("bot", resp))
        st.rerun()

# ── PILOTS ──
with tab_pilots:
    st.markdown('<div class="section-label">Pilot Roster — Live</div>', unsafe_allow_html=True)
    try:
        df = read_sheet("pilot_roster")
        if not df.empty:
            flt = st.selectbox("Status", ["All", "Available", "Assigned", "On Leave", "Unavailable"], key="p_flt")
            if flt != "All":
                df = df[df["status"] == flt]

            def _p_style(val):
                m = {"Available": "background:#063020;color:#2dd4a0",
                     "Assigned": "background:#0d1f3f;color:#60a5fa",
                     "On Leave": "background:#2a2005;color:#f5c242",
                     "Unavailable": "background:#200808;color:#f46060"}
                return m.get(str(val), "")

            cols = ["pilot_id","name","skills","certifications","location","status","current_assignment","available_from","daily_rate_inr"]
            show = [c for c in cols if c in df.columns]
            st.dataframe(df[show].style.applymap(_p_style, subset=["status"]),
                         use_container_width=True, hide_index=True)
            st.caption(f"{len(df)} pilots shown")
    except Exception as e:
        st.error(f"Error: {e}")

# ── DRONES ──
with tab_drones:
    st.markdown('<div class="section-label">Drone Fleet — Live</div>', unsafe_allow_html=True)
    try:
        df = read_sheet("drone_fleet")
        if not df.empty:
            flt = st.selectbox("Status", ["All", "Available", "Deployed", "Maintenance"], key="d_flt")
            if flt != "All":
                df = df[df["status"] == flt]

            def _d_style(val):
                m = {"Available": "background:#063020;color:#2dd4a0",
                     "Deployed": "background:#0d1f3f;color:#60a5fa",
                     "Maintenance": "background:#200808;color:#f46060"}
                return m.get(str(val), "")

            cols = ["drone_id","model","capabilities","weather_resistance","status","location","current_assignment","maintenance_due"]
            show = [c for c in cols if c in df.columns]
            st.dataframe(df[show].style.applymap(_d_style, subset=["status"]),
                         use_container_width=True, hide_index=True)
            st.caption(f"{len(df)} drones shown")

            # Maintenance alerts inline
            maint = flag_maintenance_issues()
            if maint["overdue"]:
                st.error(f"🔴 {maint['overdue_count']} drone(s) OVERDUE for maintenance!")
            if maint["upcoming_within_30_days"]:
                st.warning(f"🟡 {maint['upcoming_count']} drone(s) due for maintenance within 30 days")
    except Exception as e:
        st.error(f"Error: {e}")

# ── MISSIONS ──
with tab_missions:
    st.markdown('<div class="section-label">Mission Board — Live</div>', unsafe_allow_html=True)
    try:
        df = read_sheet("missions")
        if not df.empty:
            def _m_style(val):
                m = {"Urgent": "background:#1f0808;color:#f46060",
                     "High": "background:#1f1008;color:#f97316",
                     "Standard": "background:#0d1f3f;color:#60a5fa"}
                return m.get(str(val), "")

            cols = ["project_id","client","location","required_skills","required_certs",
                    "start_date","end_date","priority","mission_budget_inr",
                    "weather_forecast","assigned_pilot","assigned_drone","status"]
            show = [c for c in cols if c in df.columns]
            st.dataframe(df[show].style.applymap(_m_style, subset=["priority"]),
                         use_container_width=True, hide_index=True)
            st.caption(f"{len(df)} missions")
    except Exception as e:
        st.error(f"Error: {e}")

# ── CONFLICTS ──
with tab_conflicts:
    st.markdown('<div class="section-label">Conflict Scanner</div>', unsafe_allow_html=True)

    if st.button("🔄 Run Conflict Scan", type="primary"):
        with st.spinner("Scanning..."):
            st.session_state.conflicts = detect_all_conflicts()

    if "conflicts" not in st.session_state:
        with st.spinner("Running initial scan..."):
            st.session_state.conflicts = detect_all_conflicts()

    data = st.session_state.conflicts
    total = data.get("total_conflicts", 0)

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f'<div class="stat-card"><div class="stat-n red">{data.get("critical",0)}</div><div class="stat-l">Critical</div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="stat-card"><div class="stat-n yellow">{data.get("high",0)}</div><div class="stat-l">High</div></div>', unsafe_allow_html=True)
    with c3:
        med = sum(1 for c in data.get("conflicts",[]) if c["severity"]=="Medium")
        st.markdown(f'<div class="stat-card"><div class="stat-n blue">{med}</div><div class="stat-l">Medium</div></div>', unsafe_allow_html=True)
    with c4: st.markdown(f'<div class="stat-card"><div class="stat-n {"red" if total else "green"}">{total}</div><div class="stat-l">Total</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if not data.get("conflicts"):
        st.success("✅ No conflicts detected across all missions!")
    else:
        icons = {"Critical": "🔴", "High": "🟠", "Medium": "🟡"}
        for c in data["conflicts"]:
            sev = c["severity"]
            pilot_ref = f" · Pilot: **{c['pilot']}**" if "pilot" in c else ""
            drone_ref = f" · Drone: **{c['drone']}**" if "drone" in c else ""
            st.markdown(f"""
<div class="conflict-{sev}">
<strong>{icons.get(sev,'⚪')} {c['type'].replace('_',' ')}</strong>
<span style="color:#4a6080;font-size:0.78rem;font-family:'IBM Plex Mono',monospace;">
  [{sev}] Mission: {c.get('mission','')}{pilot_ref}{drone_ref}
</span><br>
<span style="color:#8aaac8;">{c['detail']}</span>
</div>
""", unsafe_allow_html=True)
