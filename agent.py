"""
agent.py — Skylark Drone Ops Agent using Groq (free, fast, no credit card).
Model: llama-3.3-70b-versatile — supports tool/function calling.
"""

import json
import os
import streamlit as st
from groq import Groq
from tools import (
    query_pilots, calculate_pilot_cost, get_pilot_assignments, update_pilot_status,
    match_pilots_to_mission, match_drones_to_mission, assign_pilot_to_mission,
    assign_drone_to_mission, get_active_assignments,
    query_drones, flag_maintenance_issues, update_drone_status,
    detect_all_conflicts, check_mission_conflicts
)

TOOL_FUNCTIONS = {
    "query_pilots": query_pilots,
    "calculate_pilot_cost": calculate_pilot_cost,
    "get_pilot_assignments": get_pilot_assignments,
    "update_pilot_status": update_pilot_status,
    "match_pilots_to_mission": match_pilots_to_mission,
    "match_drones_to_mission": match_drones_to_mission,
    "assign_pilot_to_mission": assign_pilot_to_mission,
    "assign_drone_to_mission": assign_drone_to_mission,
    "get_active_assignments": get_active_assignments,
    "query_drones": query_drones,
    "flag_maintenance_issues": flag_maintenance_issues,
    "update_drone_status": update_drone_status,
    "detect_all_conflicts": detect_all_conflicts,
    "check_mission_conflicts": check_mission_conflicts,
}

TOOLS = [
    {"type":"function","function":{"name":"query_pilots","description":"Search pilot roster by skill, certification, location, or status.","parameters":{"type":"object","properties":{"skill":{"type":"string"},"certification":{"type":"string"},"location":{"type":"string"},"status":{"type":"string"}}}}},
    {"type":"function","function":{"name":"calculate_pilot_cost","description":"Calculate total cost of a pilot for a mission and check against budget.","parameters":{"type":"object","properties":{"pilot_id":{"type":"string"},"mission_id":{"type":"string"}},"required":["pilot_id","mission_id"]}}},
    {"type":"function","function":{"name":"get_pilot_assignments","description":"View all currently assigned pilots and their missions.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"update_pilot_status","description":"Update pilot status and sync to Google Sheets.","parameters":{"type":"object","properties":{"pilot_id":{"type":"string"},"new_status":{"type":"string"},"assignment":{"type":"string"}},"required":["pilot_id","new_status"]}}},
    {"type":"function","function":{"name":"match_pilots_to_mission","description":"Find pilots matching a mission. Flags cert mismatch, budget overrun, double-booking, location mismatch.","parameters":{"type":"object","properties":{"mission_id":{"type":"string"}},"required":["mission_id"]}}},
    {"type":"function","function":{"name":"match_drones_to_mission","description":"Find drones for a mission. Flags maintenance, weather incompatibility, location mismatch.","parameters":{"type":"object","properties":{"mission_id":{"type":"string"}},"required":["mission_id"]}}},
    {"type":"function","function":{"name":"assign_pilot_to_mission","description":"Assign a pilot to a mission with conflict pre-check. Syncs to Google Sheets.","parameters":{"type":"object","properties":{"pilot_id":{"type":"string"},"mission_id":{"type":"string"}},"required":["pilot_id","mission_id"]}}},
    {"type":"function","function":{"name":"assign_drone_to_mission","description":"Assign a drone to a mission with conflict pre-check. Syncs to Google Sheets.","parameters":{"type":"object","properties":{"drone_id":{"type":"string"},"mission_id":{"type":"string"}},"required":["drone_id","mission_id"]}}},
    {"type":"function","function":{"name":"get_active_assignments","description":"Get all missions with assigned pilots or drones.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"query_drones","description":"Search drone fleet by capability, status, location, or weather resistance.","parameters":{"type":"object","properties":{"capability":{"type":"string"},"status":{"type":"string"},"location":{"type":"string"},"weather_resistance":{"type":"string"}}}}},
    {"type":"function","function":{"name":"flag_maintenance_issues","description":"Flag drones with overdue or upcoming maintenance within 30 days.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"update_drone_status","description":"Update drone status and sync to Google Sheets.","parameters":{"type":"object","properties":{"drone_id":{"type":"string"},"new_status":{"type":"string"},"location":{"type":"string"}},"required":["drone_id","new_status"]}}},
    {"type":"function","function":{"name":"detect_all_conflicts","description":"Full conflict scan: double-booking, cert mismatch, budget overrun, maintenance, weather risk, location mismatch.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"check_mission_conflicts","description":"Check all conflicts for one specific mission.","parameters":{"type":"object","properties":{"mission_id":{"type":"string"}},"required":["mission_id"]}}}
]

SYSTEM_PROMPT = """You are Skylark Operations Control — an AI coordinator for Skylark Drones.

You manage pilots, drones, and missions. Always use tools to fetch live data.

DATA SCHEMA:
- Skills/certs are semicolon-separated: "Mapping; Survey", "DGCA; Night Ops"
- Weather resistance: "IP43 (Rain)" = flies in rain | "None (Clear Sky Only)" = clear weather only
- Pilot cost = daily_rate_inr x mission duration days
- Mission IDs: PRJ001, PRJ002, PRJ003
- Pilot IDs: P001, P002, P003, P004
- Drone IDs: D001, D002, D003, D004

EDGE CASES TO DETECT:
1. Pilot double-booking (overlapping mission dates)
2. Cert mismatch (pilot lacks required certs)
3. Budget overrun (pilot cost > mission budget)
4. Drone in maintenance
5. Weather risk (non-IP rated drone in rainy mission)
6. Pilot and drone in different locations

Be concise, use bullet points, flag issues with emojis. Use INR for currency."""


def _get_api_key():
    try:
        if hasattr(st, 'secrets') and 'groq_api_key' in st.secrets:
            return st.secrets["groq_api_key"]
    except:
        pass
    return os.environ.get("GROQ_API_KEY", "")


def run_tool(name: str, args: dict) -> str:
    if name not in TOOL_FUNCTIONS:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = TOOL_FUNCTIONS[name](**args)
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def chat(history: list, user_message: str) -> tuple[str, list]:
    api_key = _get_api_key()
    if not api_key:
        return ("⚠️ Groq API key not set.\n\n"
                "Run in PowerShell: $env:GROQ_API_KEY = 'your_key_here'\n"
                "Get a FREE key at: https://console.groq.com"), history

    client = Groq(api_key=api_key)
    history = history + [{"role": "user", "content": user_message}]

    # Step 1: Let model decide which tool to call
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        tools=TOOLS,
        tool_choice="auto",
        max_tokens=4096
    )

    msg = response.choices[0].message

    # If no tool call needed, return answer directly
    if not msg.tool_calls:
        history = history + [{"role": "assistant", "content": msg.content or ""}]
        return msg.content or "Done.", history

    # Step 2: Execute all tool calls
    assistant_msg = {
        "role": "assistant",
        "content": msg.content or "",
        "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    }
    history = history + [assistant_msg]

    for tc in msg.tool_calls:
        try:
            args = json.loads(tc.function.arguments)
        except:
            args = {}
        result = run_tool(tc.function.name, args)
        history = history + [{"role": "tool", "tool_call_id": tc.id, "content": result}]

    # Step 3: Get final answer with tool_choice="none" so it MUST respond with text
    final = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        tools=TOOLS,
        tool_choice="none",
        max_tokens=4096
    )

    final_text = final.choices[0].message.content or "Done."
    history = history + [{"role": "assistant", "content": final_text}]
    return final_text, history