# -*- coding: utf-8 -*-

import os
import json
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

# =========================
# 設定
# =========================
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_ID = "1PZKZITDQbgqJyCTDbuj9oV25tU01sfys_bkN7Bnc6vY"

SHEET_MAP = {
    "quest": "クエスト情報",
    "owned": "所持数",
    "tier": "キャラTier表",
    "character": "キャラ表",
    "char_master": "キャラ基礎情報",
    "master": "マスタ設定",
    "wakuwaku": {
        "メイン": "わくわく_メイン",
        "サブ": "わくわく_サブ",
        "サブサブ": "わくわく_サブサブ",
    }
}

DEFAULT_HEADERS = {
    "キャラTier表": ["キャラ名", "属性", "Tier", "ポイント", "内部キー"],
    "キャラ表": ["キャラ名", "属性", "Tier", "ポイント", "メイン", "サブ", "サブサブ", "内部キー"],
    "キャラ基礎情報": ["キャラ名", "種族", "戦型", "撃種", "内部キー"],
    "マスタ設定": ["カテゴリ", "キー", "値"],
    "わくわく_メイン": ["キャラ名", "個体番号", "わくわく1", "わくわく2", "わくわく3", "内部キー", "個体キー"],
    "わくわく_サブ": ["キャラ名", "個体番号", "わくわく1", "わくわく2", "わくわく3", "内部キー", "個体キー"],
    "わくわく_サブサブ": ["キャラ名", "個体番号", "わくわく1", "わくわく2", "わくわく3", "内部キー", "個体キー"],
}

# =========================
# キャッシュ
# =========================
_client_cache = None
_spreadsheet_cache = None
_ws_cache = {}
_sheet_color_cache = {}

# =========================
# 認証
# =========================
def get_client():
    global _client_cache
    if _client_cache is None:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")
        if creds_json:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(
                creds_dict, scopes=SCOPES
            )
        else:
            creds = Credentials.from_service_account_file(
                "credentials.json", scopes=SCOPES
            )
        _client_cache = gspread.authorize(creds)
    return _client_cache


def get_spreadsheet():
    global _spreadsheet_cache
    if _spreadsheet_cache is None:
        client = get_client()
        _spreadsheet_cache = client.open_by_key(SPREADSHEET_ID)
    return _spreadsheet_cache

# =========================
# 共通：DataFrame化
# =========================
def get_df(ws):
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame()

    df = pd.DataFrame(values[1:], columns=values[0])
    df.columns = [str(c).strip() for c in df.columns]
    return df

# =========================
# シート取得 or 作成
# =========================
def get_or_create_ws(spreadsheet, name):
    global _ws_cache

    if name in _ws_cache:
        return _ws_cache[name]

    try:
        ws = spreadsheet.worksheet(name)
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=name, rows=200, cols=20)

        headers = DEFAULT_HEADERS.get(name)
        if headers:
            ws.update(values=[headers], range_name="A1")

        print(f"作成: {name}")

    _ws_cache[name] = ws
    return ws

# =========================
# 背景色取得（クエスト専用）
# =========================
def get_sheet_with_color(spreadsheet, sheet_name):
    global _sheet_color_cache

    if sheet_name in _sheet_color_cache:
        return _sheet_color_cache[sheet_name]

    meta = spreadsheet.fetch_sheet_metadata(params={
        "includeGridData": True,
        "ranges": [sheet_name]
    })

    sheet = meta["sheets"][0]
    data = sheet["data"][0]
    row_data = data.get("rowData", [])

    values = []
    colors = []

    for row in row_data:
        row_vals = []
        row_cols = []

        cells = row.get("values", [])
        for cell in cells:
            val = cell.get("formattedValue", "")
            row_vals.append(val)

            bg = cell.get("userEnteredFormat", {}).get("backgroundColor", {})
            rgb = (
                bg.get("red", 1.0),
                bg.get("green", 1.0),
                bg.get("blue", 1.0),
            )
            row_cols.append(rgb)

        values.append(row_vals)
        colors.append(row_cols)

    if not values:
        result = (pd.DataFrame(), [])
        _sheet_color_cache[sheet_name] = result
        return result

    df = pd.DataFrame(values[1:], columns=values[0])
    df.columns = [str(c).strip() for c in df.columns]

    result = (df, colors)
    _sheet_color_cache[sheet_name] = result
    return result

# =========================
# キャッシュクリア
# =========================
def clear_loader_cache():
    global _client_cache, _spreadsheet_cache, _ws_cache, _sheet_color_cache
    _client_cache = None
    _spreadsheet_cache = None
    _ws_cache = {}
    _sheet_color_cache = {}

# =========================
# 各読み込み
# =========================
def load_all():
    spreadsheet = get_spreadsheet()

    # 必要シートを自動生成
    get_or_create_ws(spreadsheet, SHEET_MAP["tier"])
    get_or_create_ws(spreadsheet, SHEET_MAP["character"])
    get_or_create_ws(spreadsheet, SHEET_MAP["char_master"])
    get_or_create_ws(spreadsheet, SHEET_MAP["master"])
    get_or_create_ws(spreadsheet, SHEET_MAP["wakuwaku"]["メイン"])
    get_or_create_ws(spreadsheet, SHEET_MAP["wakuwaku"]["サブ"])
    get_or_create_ws(spreadsheet, SHEET_MAP["wakuwaku"]["サブサブ"])

    # 既存必須
    quest_df, quest_colors = get_sheet_with_color(spreadsheet, SHEET_MAP["quest"])
    owned_df = get_df(get_or_create_ws(spreadsheet, SHEET_MAP["owned"]))
    char_master_df = get_df(get_or_create_ws(spreadsheet, SHEET_MAP["char_master"]))

    return {
        "quest": quest_df,
        "quest_colors": quest_colors,
        "owned": owned_df,
        "tier": get_df(get_or_create_ws(spreadsheet, SHEET_MAP["tier"])),
        "character": get_df(get_or_create_ws(spreadsheet, SHEET_MAP["character"])),
        "char_master": char_master_df,
        "master": get_df(get_or_create_ws(spreadsheet, SHEET_MAP["master"])),
        "wakuwaku": {
            "メイン": get_df(get_or_create_ws(spreadsheet, SHEET_MAP["wakuwaku"]["メイン"])),
            "サブ": get_df(get_or_create_ws(spreadsheet, SHEET_MAP["wakuwaku"]["サブ"])),
            "サブサブ": get_df(get_or_create_ws(spreadsheet, SHEET_MAP["wakuwaku"]["サブサブ"])),
        }
    }

# =========================
# 実行テスト
# =========================
if __name__ == "__main__":
    data = load_all()
    print("OK: 読み込み成功")
    print("quest行数:", len(data["quest"]))
    print("owned行数:", len(data["owned"]))
    print("char_master行数:", len(data["char_master"]))
