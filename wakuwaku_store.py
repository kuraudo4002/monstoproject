# -*- coding: utf-8 -*-

import re
import time
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_ID = "1PZKZITDQbgqJyCTDbuj9oV25tU01sfys_bkN7Bnc6vY"

WAKU_SHEETS = {
    "メイン": "わくわく_メイン",
    "サブ": "わくわく_サブ",
    "サブサブ": "わくわく_サブサブ",
}

HEADERS = ["キャラ名", "個体番号", "わくわく1", "わくわく2", "わくわく3", "内部キー", "個体キー"]

CACHE_SECONDS = 30

_cache = {
    "loaded_at": 0,
    "client": None,
    "spreadsheet": None,
    "worksheets": {},
    "sheet_values": {},
}


def normalize_text(x):
    if x is None:
        return ""
    return str(x).strip()


def strip_form_name(name):
    name = normalize_text(name)
    name = name.replace("（", "(").replace("）", ")")
    name = re.sub(r"\(.*?\)", "", name).strip()
    return name


def make_internal_key(name, attr):
    base = strip_form_name(name)
    attr = normalize_text(attr)
    if not base or not attr:
        return ""
    return f"{base}||{attr}"


def _is_cache_expired():
    return (time.time() - _cache["loaded_at"]) > CACHE_SECONDS


def _reset_cache():
    _cache["loaded_at"] = time.time()
    _cache["client"] = None
    _cache["spreadsheet"] = None
    _cache["worksheets"] = {}
    _cache["sheet_values"] = {}


def get_client():
    if _cache["client"] is not None and not _is_cache_expired():
        return _cache["client"]

    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)

    if _is_cache_expired():
        _reset_cache()

    _cache["client"] = client
    return client


def get_spreadsheet():
    if _cache["spreadsheet"] is not None and not _is_cache_expired():
        return _cache["spreadsheet"]

    client = get_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    _cache["spreadsheet"] = spreadsheet
    return spreadsheet


def parse_char_id(char_id):
    """
    char_id:
    キャラ名||属性||アカウント||個体番号
    """
    parts = str(char_id).split("||")
    if len(parts) != 4:
        return None

    name, attr, acc, num = parts
    return {
        "name": normalize_text(name),
        "attr": normalize_text(attr),
        "acc": normalize_text(acc),
        "num": normalize_text(num),
        "internal_key": make_internal_key(name, attr),
    }


def find_header_indexes(headers):
    header_map = {normalize_text(h): i for i, h in enumerate(headers)}
    return {
        "name": header_map.get("キャラ名"),
        "num": header_map.get("個体番号"),
        "w1": header_map.get("わくわく1"),
        "w2": header_map.get("わくわく2"),
        "w3": header_map.get("わくわく3"),
        "internal_key": header_map.get("内部キー"),
        "item_key": header_map.get("個体キー"),
    }


def get_sheet_for_char_id(parsed):
    if not parsed:
        return None

    sheet_name = WAKU_SHEETS.get(parsed["acc"])
    if not sheet_name:
        return None

    if sheet_name in _cache["worksheets"] and not _is_cache_expired():
        return _cache["worksheets"][sheet_name]

    spreadsheet = get_spreadsheet()
    ws = spreadsheet.worksheet(sheet_name)
    _cache["worksheets"][sheet_name] = ws
    return ws


def get_sheet_values(ws):
    sheet_name = ws.title

    if sheet_name in _cache["sheet_values"] and not _is_cache_expired():
        return _cache["sheet_values"][sheet_name]

    values = ws.get_all_values()
    _cache["sheet_values"][sheet_name] = values
    return values


def invalidate_sheet_cache(ws):
    sheet_name = ws.title
    if sheet_name in _cache["sheet_values"]:
        del _cache["sheet_values"][sheet_name]


def _safe_cell(row, idx):
    if idx is None:
        return ""
    if idx >= len(row):
        return ""
    return normalize_text(row[idx])


def find_row(ws, char_id):
    parsed = parse_char_id(char_id)
    if not parsed:
        return None

    values = get_sheet_values(ws)
    if len(values) <= 1:
        return None

    headers = values[0]
    idx = find_header_indexes(headers)

    # 1. 個体キー完全一致
    if idx["item_key"] is not None:
        for row_no, row in enumerate(values[1:], start=2):
            item_key = _safe_cell(row, idx["item_key"])
            if item_key == normalize_text(char_id):
                return row_no

    # 2. 内部キー + 個体番号
    if idx["internal_key"] is not None and idx["num"] is not None:
        for row_no, row in enumerate(values[1:], start=2):
            row_internal_key = _safe_cell(row, idx["internal_key"])
            row_num = _safe_cell(row, idx["num"])

            if row_internal_key == parsed["internal_key"] and row_num == parsed["num"]:
                return row_no

    # 3. キャラ名(進化先除去) + 個体番号
    if idx["name"] is not None and idx["num"] is not None:
        target_base_name = strip_form_name(parsed["name"])
        for row_no, row in enumerate(values[1:], start=2):
            row_name = strip_form_name(_safe_cell(row, idx["name"]))
            row_num = _safe_cell(row, idx["num"])

            if row_name == target_base_name and row_num == parsed["num"]:
                return row_no

    return None


def get(char_id):
    parsed = parse_char_id(char_id)
    if not parsed:
        return []

    ws = get_sheet_for_char_id(parsed)
    if ws is None:
        return []

    row_no = find_row(ws, char_id)
    if not row_no:
        return []

    values = get_sheet_values(ws)
    row_idx = row_no - 1
    if row_idx >= len(values):
        return []

    row = values[row_idx]
    row = row + [""] * (len(HEADERS) - len(row))

    fruits = [
        normalize_text(row[2]),
        normalize_text(row[3]),
        normalize_text(row[4]),
    ]
    return [f for f in fruits if f]


def set_fruits(char_id, fruits):
    parsed = parse_char_id(char_id)
    if not parsed:
        print("set失敗: char_id形式不正", char_id)
        return False

    ws = get_sheet_for_char_id(parsed)
    if ws is None:
        print("set失敗: シート不明", parsed["acc"])
        return False

    row_no = find_row(ws, char_id)

    cleaned = []
    seen = set()

    for fruit in fruits:
        fruit = normalize_text(fruit)
        if not fruit:
            continue
        if fruit in seen:
            continue
        seen.add(fruit)
        cleaned.append(fruit)

    cleaned = cleaned[:3]
    while len(cleaned) < 3:
        cleaned.append("")

    # 既存行更新
    if row_no:
        ws.update(f"C{row_no}:E{row_no}", [cleaned])

        # 個体キーや内部キーが空の古い行にも補完を入れる
        ws.update(f"A{row_no}:G{row_no}", [[
            strip_form_name(parsed["name"]),
            parsed["num"],
            cleaned[0],
            cleaned[1],
            cleaned[2],
            parsed["internal_key"],
            char_id,
        ]])

        invalidate_sheet_cache(ws)
        print("set成功(更新):", char_id, cleaned, "row", row_no)
        return True

    # 新規行追加
    append_row = [
        strip_form_name(parsed["name"]),
        parsed["num"],
        cleaned[0],
        cleaned[1],
        cleaned[2],
        parsed["internal_key"],
        char_id,
    ]
    ws.append_row(append_row)

    invalidate_sheet_cache(ws)
    print("set成功(追加):", char_id, cleaned)
    return True


def add(char_id, fruit):
    current = get(char_id)
    if fruit not in current:
        current.append(fruit)
    return set_fruits(char_id, current)


def remove(char_id, fruit):
    current = [f for f in get(char_id) if normalize_text(f) != normalize_text(fruit)]
    return set_fruits(char_id, current)
