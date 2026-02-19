"""
tools.py — Skylark Drone Ops Agent tools.
Schema matches exact user-provided CSV structure.
All 6 edge cases handled:
  1. Pilot double-booking (overlapping dates)
  2. Pilot missing required certification
  3. Pilot too expensive for mission budget
  4. Drone in maintenance
  5. Drone not weather-rated for mission forecast
  6. Pilot and drone in different locations
"""

import pandas as pd
from datetime import datetime
from sheets import read_sheet, update_cell, update_multiple_cells


# ────────────────────────────────────────────
# HELPERS
# ────────────────────────────────────────────

def _parse_date(d):
    if not d or (isinstance(d, float) and pd.isna(d)):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(d).strip(), fmt)
        except ValueError:
            continue
    return None

def _split(val, sep=";"):
    """Split a semicolon-separated string into a clean set of lowercase strings."""
    if not val or (isinstance(val, float) and pd.isna(val)):
        return set()
    return {s.strip().lower() for s in str(val).split(sep) if s.strip()}

def _skills_ok(required_str, pilot_str):
    req = _split(required_str, ";") | _split(required_str, ",")
    have = _split(pilot_str, ";") | _split(pilot_str, ",")
    missing = req - have
    return len(missing) == 0, missing

def _certs_ok(required_str, pilot_str):
    req = _split(required_str, ";") | _split(required_str, ",")
    have = _split(pilot_str, ";") | _split(pilot_str, ",")
    missing = req - have
    return len(missing) == 0, missing

def _dates_overlap(s1, e1, s2, e2):
    d1s, d1e = _parse_date(s1), _parse_date(e1)
    d2s, d2e = _parse_date(s2), _parse_date(e2)
    if not all([d1s, d1e, d2s, d2e]):
        return False
    return d1s <= d2e and d2s <= d1e

def _mission_duration_days(start, end):
    s, e = _parse_date(start), _parse_date(end)
    if s and e:
        return max((e - s).days + 1, 1)
    return 1

def _drone_weather_ok(weather_resistance: str, weather_forecast: str) -> bool:
    """
    IP43 (Rain) drones can fly in any weather.
    None (Clear Sky Only) drones cannot fly in Rainy conditions.
    Cloudy/Sunny/Clear are fine for all drones.
    """
    forecast = str(weather_forecast).strip().lower()
    resistance = str(weather_resistance).strip().lower()
    if forecast in ("sunny", "clear", "cloudy"):
        return True
    if forecast == "rainy":
        return "ip43" in resistance or "ip44" in resistance or "ip55" in resistance
    return True


# ────────────────────────────────────────────
# 1. ROSTER MANAGEMENT
# ────────────────────────────────────────────

def query_pilots(skill: str = None, certification: str = None,
                 location: str = None, status: str = None) -> dict:
    """Search pilot roster by skill, certification, location, or status."""
    df = read_sheet("pilot_roster")
    if df.empty:
        return {"error": "Could not load pilot roster"}

    res = df.copy()
    if skill:
        res = res[res["skills"].str.contains(skill, case=False, na=False)]
    if certification:
        res = res[res["certifications"].str.contains(certification, case=False, na=False)]
    if location:
        res = res[res["location"].str.contains(location, case=False, na=False)]
    if status:
        res = res[res["status"].str.lower() == status.lower()]

    return {"count": len(res), "pilots": res.to_dict(orient="records")}


def calculate_pilot_cost(pilot_id: str, mission_id: str) -> dict:
    """Calculate total pilot cost for a mission and check against budget."""
    pilots = read_sheet("pilot_roster")
    missions = read_sheet("missions")

    p_row = pilots[pilots["pilot_id"] == pilot_id]
    m_row = missions[missions["project_id"] == mission_id]

    if p_row.empty:
        return {"error": f"Pilot {pilot_id} not found"}
    if m_row.empty:
        return {"error": f"Mission {mission_id} not found"}

    pilot = p_row.iloc[0]
    mission = m_row.iloc[0]

    daily_rate = float(pilot["daily_rate_inr"])
    duration = _mission_duration_days(mission["start_date"], mission["end_date"])
    total_cost = daily_rate * duration
    budget = float(mission["mission_budget_inr"])

    return {
        "pilot_id": pilot_id,
        "pilot_name": pilot["name"],
        "mission_id": mission_id,
        "daily_rate_inr": daily_rate,
        "duration_days": duration,
        "total_cost_inr": total_cost,
        "mission_budget_inr": budget,
        "within_budget": total_cost <= budget,
        "surplus_or_deficit_inr": budget - total_cost,
        # EDGE CASE 3: flag if too expensive
        "budget_warning": None if total_cost <= budget else f"⚠️ Pilot cost ₹{total_cost} EXCEEDS mission budget ₹{budget} by ₹{total_cost - budget}"
    }


def get_pilot_assignments() -> dict:
    """View all currently assigned pilots and their missions."""
    pilots = read_sheet("pilot_roster")
    missions = read_sheet("missions")

    assigned = pilots[pilots["status"] == "Assigned"]
    result = []
    for _, p in assigned.iterrows():
        mission_info = {}
        proj = str(p.get("current_assignment", "")).strip()
        if proj:
            m = missions[missions["project_id"] == proj]
            if not m.empty:
                m = m.iloc[0]
                mission_info = {
                    "client": m["client"],
                    "location": m["location"],
                    "start_date": m["start_date"],
                    "end_date": m["end_date"],
                    "priority": m["priority"]
                }
        result.append({**p.to_dict(), "mission_details": mission_info})

    return {"assigned_count": len(result), "assignments": result}


def update_pilot_status(pilot_id: str, new_status: str, assignment: str = "") -> dict:
    """Update pilot status and sync to Google Sheets."""
    valid = ["Available", "Assigned", "On Leave", "Unavailable"]
    if new_status not in valid:
        return {"error": f"Invalid status. Choose from: {valid}"}

    updates = {"status": new_status, "current_assignment": assignment}
    return update_multiple_cells("pilot_roster", "pilot_id", pilot_id, updates)


# ────────────────────────────────────────────
# 2. ASSIGNMENT TRACKING
# ────────────────────────────────────────────

def match_pilots_to_mission(mission_id: str) -> dict:
    """
    Find pilots matching a mission's skill/cert requirements.
    Flags: skill mismatch, cert mismatch, budget overrun, location mismatch,
           unavailability, and date conflicts.
    """
    pilots = read_sheet("pilot_roster")
    missions = read_sheet("missions")

    m_row = missions[missions["project_id"] == mission_id]
    if m_row.empty:
        return {"error": f"Mission {mission_id} not found"}
    mission = m_row.iloc[0]

    # Pilots available on mission start date
    mission_start = _parse_date(mission["start_date"])
    mission_end = _parse_date(mission["end_date"])

    perfect, partial, ineligible = [], [], []

    for _, pilot in pilots.iterrows():
        issues = []
        warnings = []

        # Status check
        if pilot["status"] == "On Leave":
            issues.append("Pilot is on leave")
        elif pilot["status"] == "Unavailable":
            issues.append("Pilot is unavailable")

        # Availability date check
        avail_from = _parse_date(pilot.get("available_from"))
        if avail_from and mission_start and avail_from > mission_start:
            issues.append(f"Not available until {pilot['available_from']} (mission starts {mission['start_date']})")

        # EDGE CASE 1: Double-booking — check if already assigned to overlapping mission
        if pilot["status"] == "Assigned" and str(pilot.get("current_assignment", "")).strip():
            existing_proj = missions[missions["project_id"] == str(pilot["current_assignment"]).strip()]
            if not existing_proj.empty:
                ep = existing_proj.iloc[0]
                if _dates_overlap(mission["start_date"], mission["end_date"], ep["start_date"], ep["end_date"]):
                    issues.append(f"⚠️ DOUBLE-BOOKING: Already assigned to {pilot['current_assignment']} which overlaps these dates")

        # EDGE CASE 2: Cert mismatch
        certs_good, missing_certs = _certs_ok(mission["required_certs"], pilot["certifications"])
        if not certs_good:
            issues.append(f"⚠️ MISSING CERTIFICATIONS: {missing_certs}")

        # Skill mismatch
        skills_good, missing_skills = _skills_ok(mission["required_skills"], pilot["skills"])
        if not skills_good:
            issues.append(f"Missing skills: {missing_skills}")

        # EDGE CASE 3: Budget overrun
        cost_info = calculate_pilot_cost(pilot["pilot_id"], mission_id)
        if not cost_info.get("within_budget", True):
            warnings.append(cost_info.get("budget_warning", "Budget warning"))

        # Location mismatch (warning, not hard blocker)
        loc_match = pilot["location"].strip().lower() == str(mission["location"]).strip().lower()
        if not loc_match:
            warnings.append(f"Pilot in {pilot['location']}, mission in {mission['location']} — relocation needed")

        entry = {
            "pilot_id": pilot["pilot_id"],
            "name": pilot["name"],
            "status": pilot["status"],
            "location": pilot["location"],
            "location_matches_mission": loc_match,
            "skills": pilot["skills"],
            "certifications": pilot["certifications"],
            "daily_rate_inr": pilot["daily_rate_inr"],
            "estimated_total_cost_inr": cost_info.get("total_cost_inr", "N/A"),
            "within_budget": cost_info.get("within_budget", True),
            "issues": issues,
            "warnings": warnings
        }

        if not issues and not warnings:
            perfect.append(entry)
        elif not issues:
            # warnings only — still viable
            partial.append({**entry, "_note": "Viable with warnings"})
        else:
            ineligible.append(entry)

    return {
        "mission_id": mission_id,
        "mission_location": mission["location"],
        "required_skills": mission["required_skills"],
        "required_certs": mission["required_certs"],
        "budget_inr": mission["mission_budget_inr"],
        "weather_forecast": mission["weather_forecast"],
        "perfect_matches": perfect,
        "matches_with_warnings": partial,
        "ineligible": ineligible
    }


def match_drones_to_mission(mission_id: str) -> dict:
    """
    Find drones suitable for a mission based on capabilities and weather.
    Flags: maintenance status, weather incompatibility, location mismatch.
    """
    drones = read_sheet("drone_fleet")
    missions = read_sheet("missions")

    m_row = missions[missions["project_id"] == mission_id]
    if m_row.empty:
        return {"error": f"Mission {mission_id} not found"}
    mission = m_row.iloc[0]
    weather = str(mission["weather_forecast"]).strip()

    suitable, warnings_only, blocked = [], [], []

    for _, drone in drones.iterrows():
        issues = []
        warnings = []

        # EDGE CASE 4: Drone in maintenance
        if str(drone["status"]).strip() == "Maintenance":
            due = drone.get("maintenance_due", "unknown date")
            issues.append(f"⚠️ DRONE IN MAINTENANCE — unavailable until {due}")

        # EDGE CASE 5: Weather incompatibility
        weather_ok = _drone_weather_ok(drone["weather_resistance"], weather)
        if not weather_ok:
            issues.append(f"⚠️ WEATHER MISMATCH: Drone rated '{drone['weather_resistance']}' cannot fly in '{weather}' conditions")

        # Location mismatch (warning)
        loc_match = str(drone["location"]).strip().lower() == str(mission["location"]).strip().lower()
        if not loc_match:
            warnings.append(f"Drone in {drone['location']}, mission in {mission['location']} — needs transport")

        # Capability check (informational)
        req_skills = _split(mission["required_skills"], ";") | _split(mission["required_skills"], ",")
        drone_caps = _split(drone["capabilities"], ";") | _split(drone["capabilities"], ",")
        cap_overlap = req_skills & drone_caps
        cap_missing = req_skills - drone_caps

        entry = {
            "drone_id": drone["drone_id"],
            "model": drone["model"],
            "capabilities": drone["capabilities"],
            "weather_resistance": drone["weather_resistance"],
            "status": drone["status"],
            "location": drone["location"],
            "location_matches_mission": loc_match,
            "matching_capabilities": list(cap_overlap),
            "missing_capabilities": list(cap_missing),
            "weather_ok": weather_ok,
            "mission_weather": weather,
            "issues": issues,
            "warnings": warnings
        }

        if not issues and not warnings:
            suitable.append(entry)
        elif not issues:
            warnings_only.append(entry)
        else:
            blocked.append(entry)

    return {
        "mission_id": mission_id,
        "weather_forecast": weather,
        "suitable_drones": suitable,
        "drones_with_warnings": warnings_only,
        "blocked_drones": blocked
    }


def assign_pilot_to_mission(pilot_id: str, mission_id: str) -> dict:
    """Assign a pilot to a mission with conflict pre-check. Syncs to Google Sheets."""
    # Run conflict pre-check
    match = match_pilots_to_mission(mission_id)
    all_pilots = match.get("perfect_matches", []) + match.get("matches_with_warnings", []) + match.get("ineligible", [])
    pilot_entry = next((p for p in all_pilots if p["pilot_id"] == pilot_id), None)

    conflicts_found = []
    if pilot_entry and pilot_entry.get("issues"):
        conflicts_found = pilot_entry["issues"]

    # Update sheets regardless (coordinator may override), but flag conflicts
    p_result = update_multiple_cells("pilot_roster", "pilot_id", pilot_id,
                                      {"status": "Assigned", "current_assignment": mission_id})
    m_result = update_cell("missions", "project_id", mission_id, "assigned_pilot", pilot_id)

    return {
        "success": p_result["success"] and m_result["success"],
        "pilot_update": p_result,
        "mission_update": m_result,
        "conflicts_detected": conflicts_found,
        "warning": "⚠️ Assignment made despite conflicts — please review!" if conflicts_found else None
    }


def assign_drone_to_mission(drone_id: str, mission_id: str) -> dict:
    """Assign a drone to a mission with conflict pre-check. Syncs to Google Sheets."""
    match = match_drones_to_mission(mission_id)
    all_drones = match.get("suitable_drones", []) + match.get("drones_with_warnings", []) + match.get("blocked_drones", [])
    drone_entry = next((d for d in all_drones if d["drone_id"] == drone_id), None)

    conflicts_found = []
    if drone_entry and drone_entry.get("issues"):
        conflicts_found = drone_entry["issues"]

    missions = read_sheet("missions")
    m_row = missions[missions["project_id"] == mission_id]
    mission_loc = m_row.iloc[0]["location"] if not m_row.empty else ""

    d_result = update_multiple_cells("drone_fleet", "drone_id", drone_id,
                                      {"status": "Deployed", "current_assignment": mission_id,
                                       "location": mission_loc})
    m_result = update_cell("missions", "project_id", mission_id, "assigned_drone", drone_id)

    return {
        "success": d_result["success"] and m_result["success"],
        "drone_update": d_result,
        "mission_update": m_result,
        "conflicts_detected": conflicts_found,
        "warning": "⚠️ Assignment made despite conflicts — please review!" if conflicts_found else None
    }


def get_active_assignments() -> dict:
    """Get all missions that have been assigned pilots or drones."""
    missions = read_sheet("missions")
    has_assignment = missions[
        missions["assigned_pilot"].notna() & (missions["assigned_pilot"] != "") |
        missions["assigned_drone"].notna() & (missions["assigned_drone"] != "")
    ] if not missions.empty else missions

    return {"count": len(has_assignment), "missions": has_assignment.to_dict(orient="records")}


# ────────────────────────────────────────────
# 3. DRONE INVENTORY
# ────────────────────────────────────────────

def query_drones(capability: str = None, status: str = None,
                 location: str = None, weather_resistance: str = None) -> dict:
    """Search drone fleet by capability, status, location, or weather resistance."""
    df = read_sheet("drone_fleet")
    if df.empty:
        return {"error": "Could not load drone fleet"}

    res = df.copy()
    if capability:
        res = res[res["capabilities"].str.contains(capability, case=False, na=False)]
    if status:
        res = res[res["status"].str.lower() == status.lower()]
    if location:
        res = res[res["location"].str.contains(location, case=False, na=False)]
    if weather_resistance:
        res = res[res["weather_resistance"].str.contains(weather_resistance, case=False, na=False)]

    return {"count": len(res), "drones": res.to_dict(orient="records")}


def flag_maintenance_issues() -> dict:
    """Flag drones with overdue or upcoming maintenance (within 30 days)."""
    df = read_sheet("drone_fleet")
    today = datetime.today()
    overdue, upcoming = [], []

    for _, drone in df.iterrows():
        due = _parse_date(drone.get("maintenance_due"))
        if not due:
            continue
        days = (due - today).days
        entry = {
            "drone_id": drone["drone_id"],
            "model": drone["model"],
            "location": drone["location"],
            "status": drone["status"],
            "maintenance_due": str(drone["maintenance_due"]),
            "days_until_due": days
        }
        if days < 0:
            entry["flag"] = f"🔴 OVERDUE by {abs(days)} days"
            overdue.append(entry)
        elif days <= 30:
            entry["flag"] = f"🟡 Due in {days} days"
            upcoming.append(entry)

    return {
        "overdue_count": len(overdue),
        "upcoming_count": len(upcoming),
        "overdue": overdue,
        "upcoming_within_30_days": upcoming
    }


def update_drone_status(drone_id: str, new_status: str, location: str = None) -> dict:
    """Update drone status and sync to Google Sheets."""
    valid = ["Available", "Deployed", "Maintenance"]
    if new_status not in valid:
        return {"error": f"Invalid status. Choose from: {valid}"}

    updates = {"status": new_status}
    if new_status == "Available":
        updates["current_assignment"] = ""
    if location:
        updates["location"] = location

    return update_multiple_cells("drone_fleet", "drone_id", drone_id, updates)


# ────────────────────────────────────────────
# 4. CONFLICT DETECTION (all 6 edge cases)
# ────────────────────────────────────────────

def detect_all_conflicts() -> dict:
    """
    Full conflict scan across all missions.
    Detects all 6 required edge cases:
      1. Pilot double-booking (overlapping dates)
      2. Pilot cert mismatch
      3. Pilot too expensive (budget overrun)
      4. Drone in maintenance
      5. Drone not weather-rated
      6. Pilot and drone in different location
    """
    pilots = read_sheet("pilot_roster")
    drones = read_sheet("drone_fleet")
    missions = read_sheet("missions")

    conflicts = []

    for _, mission in missions.iterrows():
        mid = mission["project_id"]
        assigned_pilot = str(mission.get("assigned_pilot", "")).strip()
        assigned_drone = str(mission.get("assigned_drone", "")).strip()
        weather = str(mission.get("weather_forecast", "Sunny")).strip()

        # ── PILOT CHECKS ──
        if assigned_pilot:
            p_rows = pilots[pilots["pilot_id"] == assigned_pilot]
            if p_rows.empty:
                conflicts.append({
                    "type": "PILOT_NOT_FOUND",
                    "severity": "Critical",
                    "mission": mid,
                    "detail": f"Assigned pilot '{assigned_pilot}' does not exist in roster"
                })
            else:
                pilot = p_rows.iloc[0]

                # EDGE CASE 2: Cert mismatch
                certs_good, missing_certs = _certs_ok(mission["required_certs"], pilot["certifications"])
                if not certs_good:
                    conflicts.append({
                        "type": "CERT_MISMATCH",
                        "severity": "Critical",
                        "mission": mid,
                        "pilot": assigned_pilot,
                        "detail": f"Pilot '{pilot['name']}' lacks required certifications: {missing_certs}"
                    })

                # Skill mismatch
                skills_good, missing_skills = _skills_ok(mission["required_skills"], pilot["skills"])
                if not skills_good:
                    conflicts.append({
                        "type": "SKILL_MISMATCH",
                        "severity": "High",
                        "mission": mid,
                        "pilot": assigned_pilot,
                        "detail": f"Pilot '{pilot['name']}' lacks required skills: {missing_skills}"
                    })

                # EDGE CASE 3: Budget overrun
                cost = calculate_pilot_cost(assigned_pilot, mid)
                if not cost.get("within_budget", True):
                    conflicts.append({
                        "type": "BUDGET_OVERRUN",
                        "severity": "High",
                        "mission": mid,
                        "pilot": assigned_pilot,
                        "detail": cost.get("budget_warning", "Budget exceeded")
                    })

                # EDGE CASE 1: Double-booking — pilot in overlapping mission
                other_missions = missions[
                    (missions["assigned_pilot"] == assigned_pilot) &
                    (missions["project_id"] != mid)
                ]
                for _, other in other_missions.iterrows():
                    if _dates_overlap(mission["start_date"], mission["end_date"],
                                      other["start_date"], other["end_date"]):
                        conflicts.append({
                            "type": "PILOT_DOUBLE_BOOKING",
                            "severity": "Critical",
                            "mission": mid,
                            "pilot": assigned_pilot,
                            "detail": f"Pilot '{pilot['name']}' already assigned to {other['project_id']} "
                                      f"({other['start_date']} → {other['end_date']}) — dates overlap!"
                        })

                # EDGE CASE 6 (partial): Pilot-mission location mismatch
                if str(pilot["location"]).strip().lower() != str(mission["location"]).strip().lower():
                    conflicts.append({
                        "type": "PILOT_LOCATION_MISMATCH",
                        "severity": "Medium",
                        "mission": mid,
                        "pilot": assigned_pilot,
                        "detail": f"Pilot '{pilot['name']}' is in {pilot['location']} but mission is in {mission['location']}"
                    })

        # ── DRONE CHECKS ──
        if assigned_drone:
            d_rows = drones[drones["drone_id"] == assigned_drone]
            if d_rows.empty:
                conflicts.append({
                    "type": "DRONE_NOT_FOUND",
                    "severity": "Critical",
                    "mission": mid,
                    "detail": f"Assigned drone '{assigned_drone}' does not exist in fleet"
                })
            else:
                drone = d_rows.iloc[0]

                # EDGE CASE 4: Drone in maintenance
                if str(drone["status"]).strip() == "Maintenance":
                    conflicts.append({
                        "type": "DRONE_IN_MAINTENANCE",
                        "severity": "Critical",
                        "mission": mid,
                        "drone": assigned_drone,
                        "detail": f"Drone '{drone['model']}' ({assigned_drone}) is in maintenance until {drone.get('maintenance_due', '?')}"
                    })

                # EDGE CASE 5: Weather mismatch
                if not _drone_weather_ok(drone["weather_resistance"], weather):
                    conflicts.append({
                        "type": "WEATHER_RISK",
                        "severity": "Critical",
                        "mission": mid,
                        "drone": assigned_drone,
                        "detail": f"Drone '{drone['model']}' rated '{drone['weather_resistance']}' "
                                  f"cannot fly in '{weather}' forecast for {mid}"
                    })

                # EDGE CASE 6 (partial): Drone-mission location mismatch
                if str(drone["location"]).strip().lower() != str(mission["location"]).strip().lower():
                    conflicts.append({
                        "type": "DRONE_LOCATION_MISMATCH",
                        "severity": "Medium",
                        "mission": mid,
                        "drone": assigned_drone,
                        "detail": f"Drone is in {drone['location']} but mission is in {mission['location']}"
                    })

        # ── EDGE CASE 6 (combined): Pilot and drone in DIFFERENT locations from each other ──
        if assigned_pilot and assigned_drone:
            p_rows = pilots[pilots["pilot_id"] == assigned_pilot]
            d_rows = drones[drones["drone_id"] == assigned_drone]
            if not p_rows.empty and not d_rows.empty:
                pilot_loc = str(p_rows.iloc[0]["location"]).strip().lower()
                drone_loc = str(d_rows.iloc[0]["location"]).strip().lower()
                if pilot_loc != drone_loc:
                    conflicts.append({
                        "type": "PILOT_DRONE_LOCATION_MISMATCH",
                        "severity": "High",
                        "mission": mid,
                        "pilot": assigned_pilot,
                        "drone": assigned_drone,
                        "detail": f"Pilot ({p_rows.iloc[0]['location']}) and Drone ({d_rows.iloc[0]['location']}) "
                                  f"are in different locations — cannot operate together"
                    })

    # Sort by severity
    order = {"Critical": 0, "High": 1, "Medium": 2}
    conflicts.sort(key=lambda x: order.get(x["severity"], 9))

    return {
        "total_conflicts": len(conflicts),
        "critical": sum(1 for c in conflicts if c["severity"] == "Critical"),
        "high": sum(1 for c in conflicts if c["severity"] == "High"),
        "medium": sum(1 for c in conflicts if c["severity"] == "Medium"),
        "conflicts": conflicts
    }


def check_mission_conflicts(mission_id: str) -> dict:
    """Check conflicts for one specific mission."""
    all_c = detect_all_conflicts()
    mine = [c for c in all_c["conflicts"] if c.get("mission") == mission_id]
    return {"mission_id": mission_id, "conflict_count": len(mine), "conflicts": mine}
