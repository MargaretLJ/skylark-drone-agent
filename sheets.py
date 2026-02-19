import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st
import os

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_sheets_client():
    try:
        if hasattr(st, 'secrets') and 'gcp_service_account' in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        else:
            creds_path = os.environ.get("GOOGLE_CREDS_PATH", "credentials.json")
            creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        return None

def get_sheet_id():
    try:
        if hasattr(st, 'secrets') and 'sheet_id' in st.secrets:
            return st.secrets["sheet_id"]
    except:
        pass
    return os.environ.get("SHEET_ID", "")

def read_sheet(tab_name: str) -> pd.DataFrame:
    """Read a Google Sheets tab. Falls back to local CSV if sheets not configured."""
    client = get_sheets_client()
    sheet_id = get_sheet_id()

    csv_map = {
        "pilot_roster": "pilot_roster.csv",
        "drone_fleet": "drone_fleet.csv",
        "missions": "missions.csv"
    }

    if client and sheet_id:
        try:
            spreadsheet = client.open_by_key(sheet_id)
            worksheet = spreadsheet.worksheet(tab_name)
            data = worksheet.get_all_records()
            df = pd.DataFrame(data)
            if not df.empty:
                return df
        except Exception:
            pass

    # Fallback to local CSV
    if tab_name in csv_map and os.path.exists(csv_map[tab_name]):
        return pd.read_csv(csv_map[tab_name])
    return pd.DataFrame()

def update_cell(tab_name: str, id_col: str, id_val: str, update_col: str, new_value: str) -> dict:
    """Update a single cell in Google Sheets."""
    client = get_sheets_client()
    sheet_id = get_sheet_id()

    if not client or not sheet_id:
        return {"success": False, "error": "Google Sheets not configured — update not synced to cloud (local data unchanged)."}

    try:
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet(tab_name)
        all_data = worksheet.get_all_values()
        headers = all_data[0]

        id_col_idx = headers.index(id_col)
        update_col_idx = headers.index(update_col) + 1  # gspread is 1-indexed

        row_num = None
        for i, row in enumerate(all_data[1:], start=2):
            if len(row) > id_col_idx and str(row[id_col_idx]) == str(id_val):
                row_num = i
                break

        if row_num is None:
            return {"success": False, "error": f"Row with {id_col}='{id_val}' not found in {tab_name}"}

        worksheet.update_cell(row_num, update_col_idx, new_value)
        return {"success": True, "message": f"✅ Synced: {update_col} → '{new_value}' for {id_val} in Google Sheets"}

    except Exception as e:
        return {"success": False, "error": str(e)}

def update_multiple_cells(tab_name: str, id_col: str, id_val: str, updates: dict) -> dict:
    """Update multiple columns for one row."""
    results = []
    for col, val in updates.items():
        results.append(update_cell(tab_name, id_col, id_val, col, val))
    success = all(r["success"] for r in results)
    return {
        "success": success,
        "message": f"Updated {len(updates)} field(s) for {id_val} in {tab_name}",
        "details": results
    }
