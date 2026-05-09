# -*- coding: utf-8 -*-

import json
import os
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

SHEET_NAME = "_refine_plan_store"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_client_cache = None
_spreadsheet_cache = None


def default_data():
    return {
        "priority_quests": [],
        "frozen_plan": [],
        "quest_status": {},
        "clear_history": {},
        "fruit_decisions": {},
    }


def get_spreadsheet_id():
    sid = os.environ.get("SPREADSHEET_ID")
    if sid:
        return sid

    for module_name in ["db_loader", "wakuwaku_store", "service"]:
        try:
            module = __import__(module_name)
            sid = getattr(module, "SPREADSHEET_ID", "")
            if sid:
                return sid
        except Exception:
            pass

    raise RuntimeError("SPREADSHEET_ID が見つかりません")


def get_client():
    global _client_cache

    if _client_cache is not None:
        return _client_cache

    creds_json = os.environ.get("GOOGLE_CREDENTIALS")

    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)

    _client_cache = gspread.authorize(creds)
    return _client_cache


def get_spreadsheet():
    global _spreadsheet_cache

    if _spreadsheet_cache is not None:
        return _spreadsheet_cache

    client = get_client()
    _spreadsheet_cache = client.open_by_key(get_spreadsheet_id())
    return _spreadsheet_cache


def get_store_sheet():
    spreadsheet = get_spreadsheet()

    try:
        ws = spreadsheet.worksheet(SHEET_NAME)
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=SHEET_NAME, rows=10, cols=2)
        ws.update("A1:B1", [["key", "json"]])
        ws.update("A2:B2", [["data", json.dumps(default_data(), ensure_ascii=False)]])

    return ws


def load_data():
    try:
        ws = get_store_sheet()
        raw = ws.acell("B2").value
        if not raw:
            return default_data()

        data = json.loads(raw)
    except Exception:
        return default_data()

    base = default_data()
    base.update(data)
    return base


def save_data(data):
    ws = get_store_sheet()
    raw = json.dumps(data, ensure_ascii=False)
    ws.update("A2:B2", [["data", raw]])


def get_priority_quests():
    data = load_data()
    return data.get("priority_quests", [])


def set_priority_quests(quests):
    data = load_data()
    data["priority_quests"] = quests[:3]
    save_data(data)


def get_frozen_plan():
    data = load_data()
    return data.get("frozen_plan", [])


def set_frozen_plan(plan_rows):
    data = load_data()
    data["frozen_plan"] = plan_rows
    save_data(data)


def clear_frozen_plan():
    data = load_data()
    data["frozen_plan"] = []
    data["fruit_decisions"] = {}
    save_data(data)


def get_fruit_decisions(char_id):
    data = load_data()
    return data.get("fruit_decisions", {}).get(char_id, [])


def set_fruit_decisions(char_id, decisions):
    data = load_data()
    if "fruit_decisions" not in data:
        data["fruit_decisions"] = {}
    data["fruit_decisions"][char_id] = decisions
    save_data(data)


def get_quest_status(quest_name):
    data = load_data()
    return data.get("quest_status", {}).get(quest_name, {
        "refine_done": False,
        "cleared": False,
    })


def set_refine_done(quest_name, value: bool):
    data = load_data()
    if "quest_status" not in data:
        data["quest_status"] = {}
    if quest_name not in data["quest_status"]:
        data["quest_status"][quest_name] = {
            "refine_done": False,
            "cleared": False,
        }

    data["quest_status"][quest_name]["refine_done"] = bool(value)
    save_data(data)


def set_cleared(quest_name, value: bool):
    data = load_data()
    if "quest_status" not in data:
        data["quest_status"] = {}
    if quest_name not in data["quest_status"]:
        data["quest_status"][quest_name] = {
            "refine_done": False,
            "cleared": False,
        }

    data["quest_status"][quest_name]["cleared"] = bool(value)
    save_data(data)


def save_clear_history(quest_name, party_rows):
    data = load_data()
    if "clear_history" not in data:
        data["clear_history"] = {}

    data["clear_history"][quest_name] = {
        "party": party_rows
    }
    save_data(data)


def get_clear_history(quest_name):
    data = load_data()
    return data.get("clear_history", {}).get(quest_name, {})
TEAM_SLOT_STATE = {}


def get_team_slot_state(quest):
    return TEAM_SLOT_STATE.get(str(quest), {})


def set_team_slot_state(quest, slot_no, mode, char_id):
    quest = str(quest)
    slot_key = f"slot{slot_no}"

    if quest not in TEAM_SLOT_STATE:
        TEAM_SLOT_STATE[quest] = {}

    TEAM_SLOT_STATE[quest][slot_key] = {
        "mode": str(mode),
        "char_id": str(char_id),
    }
