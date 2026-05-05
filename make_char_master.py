# -*- coding: utf-8 -*-

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_ID = "1PZKZITDQbgqJyCTDbuj9oV25tU01sfys_bkN7Bnc6vY"

QUEST_SHEET_NAME = "クエスト情報"
CHAR_MASTER_SHEET_NAME = "キャラ基礎情報"

HEADERS = ["キャラ名", "ベース名", "種族", "戦型", "撃種", "内部キー"]

ATTR_RGB = {
    "火": (234 / 255, 153 / 255, 153 / 255),
    "水": (159 / 255, 197 / 255, 232 / 255),
    "木": (182 / 255, 215 / 255, 168 / 255),
    "光": (255 / 255, 229 / 255, 153 / 255),
    "闇": (213 / 255, 166 / 255, 189 / 255),
}
ATTR_ORDER = {"火": 0, "水": 1, "木": 2, "光": 3, "闇": 4}


def normalize_text(x):
    if pd.isna(x):
        return ""
    return str(x).strip()


def get_base_name(name):
    s = normalize_text(name)
    s = s.split("(")[0]
    s = s.split("（")[0]
    return s.strip()


def make_key(full_name, attr):
    return f"{full_name}||{attr}"


def split_key(key):
    s = normalize_text(key)
    if "||" in s:
        name, attr = s.rsplit("||", 1)
        return name, attr
    return s, ""


def is_close_rgb(a, b, tol=0.03):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def attr_from_rgb(rgb):
    for attr, target in ATTR_RGB.items():
        if is_close_rgb(rgb, target):
            return attr
    return ""


def get_bg_rgb(cell_obj):
    try:
        bg = cell_obj.get("userEnteredFormat", {}).get("backgroundColor", {})
        return (
            float(bg.get("red", 1.0)),
            float(bg.get("green", 1.0)),
            float(bg.get("blue", 1.0)),
        )
    except Exception:
        return (1.0, 1.0, 1.0)


def resolve_col(headers, candidates, logical_name):
    for c in candidates:
        if c in headers:
            return headers.index(c)
    raise KeyError(f"列『{logical_name}』が見つかりません: {headers}")


def has_value(v):
    return normalize_text(v) not in ["", "無"]


def get_or_create_ws(spreadsheet, sheet_name, rows=500, cols=10):
    try:
        return spreadsheet.worksheet(sheet_name)
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=sheet_name, rows=rows, cols=cols)
        ws.update(values=[HEADERS], range_name="A1")
        return ws


def build_db_characters(spreadsheet):
    quest_ws = spreadsheet.worksheet(QUEST_SHEET_NAME)
    quest_values = quest_ws.get_all_values()
    if not quest_values:
        raise ValueError("クエスト情報シートが空です")

    q_headers = [normalize_text(x) for x in quest_values[0]]

    idx_s = resolve_col(q_headers, ["Sランク適正"], "Sランク適正")
    idx_a = resolve_col(q_headers, ["Aランク適正"], "Aランク適正")
    idx_b = resolve_col(q_headers, ["Bランク以下適正", "B以下適正"], "Bランク以下適正")

    meta = spreadsheet.fetch_sheet_metadata(params={
        "includeGridData": True,
        "ranges": [f"{QUEST_SHEET_NAME}!A:G"]
    })

    sheet_block = meta["sheets"][0]["data"][0]
    row_data = sheet_block.get("rowData", [])

    rows = []

    for r_idx in range(1, len(quest_values)):
        row = quest_values[r_idx]
        value_cells = row_data[r_idx].get("values", []) if r_idx < len(row_data) else []

        for c_idx in [idx_s, idx_a, idx_b]:
            full_name = normalize_text(row[c_idx]) if c_idx < len(row) else ""
            if not has_value(full_name):
                continue

            cell_obj = value_cells[c_idx] if c_idx < len(value_cells) else {}
            rgb = get_bg_rgb(cell_obj)
            attr = attr_from_rgb(rgb)
            if attr == "":
                continue

            rows.append({
                "キャラ名": full_name,
                "ベース名": get_base_name(full_name),
                "属性": attr,
                "内部キー": make_key(full_name, attr),
            })

    db_df = pd.DataFrame(rows)
    if db_df.empty:
        raise ValueError("DB側キャラ一覧が空です。背景色を確認してください。")

    # 進化形態ごとに残す。完全一致だけ重複排除。
    db_df = db_df.drop_duplicates(subset=["キャラ名", "属性"]).copy()

    db_df["attr_order"] = db_df["属性"].map(lambda x: ATTR_ORDER.get(x, 999))
    db_df = db_df.sort_values(by=["ベース名", "キャラ名", "attr_order"]).reset_index(drop=True)

    return db_df


def load_existing_master(master_ws):
    values = master_ws.get_all_values()
    if len(values) <= 1:
        return pd.DataFrame(columns=HEADERS)

    old_headers = [normalize_text(x) for x in values[0]]
    df = pd.DataFrame(values[1:], columns=old_headers).fillna("")

    for col in df.columns:
        df[col] = df[col].apply(normalize_text)

    if "キャラ名" not in df.columns:
        df["キャラ名"] = ""

    if "ベース名" not in df.columns:
        df["ベース名"] = df["キャラ名"].apply(get_base_name)

    if "種族" not in df.columns:
        df["種族"] = ""

    if "戦型" not in df.columns:
        df["戦型"] = ""

    if "撃種" not in df.columns:
        df["撃種"] = ""

    if "内部キー" not in df.columns:
        df["内部キー"] = ""

    return df[["キャラ名", "ベース名", "種族", "戦型", "撃種", "内部キー"]].copy()


def rebuild_master(db_df, old_df):
    # 旧入力は「内部キー」優先、なければ「キャラ名」で救済
    old_by_key = {}
    old_by_name = {}

    for _, row in old_df.iterrows():
        key = normalize_text(row["内部キー"])
        full_name = normalize_text(row["キャラ名"])

        payload = {
            "種族": normalize_text(row["種族"]),
            "戦型": normalize_text(row["戦型"]),
            "撃種": normalize_text(row["撃種"]),
        }

        if key:
            old_by_key[key] = payload

        if full_name and full_name not in old_by_name:
            old_by_name[full_name] = payload

    rebuilt_rows = []

    for _, row in db_df.iterrows():
        key = row["内部キー"]
        full_name = row["キャラ名"]
        base_name = row["ベース名"]

        existing = old_by_key.get(key)
        if existing is None:
            existing = old_by_name.get(full_name, {"種族": "", "戦型": "", "撃種": ""})

        rebuilt_rows.append({
            "キャラ名": full_name,
            "ベース名": base_name,
            "種族": existing.get("種族", ""),
            "戦型": existing.get("戦型", ""),
            "撃種": existing.get("撃種", ""),
            "内部キー": key,
            "属性": row["属性"],
        })

    final_df = pd.DataFrame(rebuilt_rows)
    final_df["attr_order"] = final_df["属性"].map(lambda x: ATTR_ORDER.get(x, 999))
    final_df = final_df.sort_values(by=["ベース名", "キャラ名", "attr_order"]).reset_index(drop=True)

    return final_df


def write_master(master_ws, final_df):
    write_df = final_df[["キャラ名", "ベース名", "種族", "戦型", "撃種", "内部キー"]].copy()
    write_values = [HEADERS] + write_df.fillna("").astype(str).values.tolist()

    master_ws.clear()
    master_ws.update(values=write_values, range_name="A1")


def paint_and_hide(master_ws, final_df, spreadsheet):
    max_len = max(len(final_df), 1)
    requests = []

    # A列を白に初期化
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": master_ws.id,
                "startRowIndex": 1,
                "endRowIndex": max_len + 1,
                "startColumnIndex": 0,
                "endColumnIndex": 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 1, "green": 1, "blue": 1}
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })

    # A列に属性色
    for i, row in final_df.iterrows():
        key = normalize_text(row["内部キー"])
        if not key:
            continue

        _, attr = split_key(key)
        rgb = ATTR_RGB.get(attr)
        if not rgb:
            continue

        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": master_ws.id,
                    "startRowIndex": i + 1,
                    "endRowIndex": i + 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {
                            "red": rgb[0],
                            "green": rgb[1],
                            "blue": rgb[2]
                        }
                    }
                },
                "fields": "userEnteredFormat.backgroundColor"
            }
        })

    # F列（内部キー）非表示
    requests.append({
        "updateDimensionProperties": {
            "range": {
                "sheetId": master_ws.id,
                "dimension": "COLUMNS",
                "startIndex": 5,
                "endIndex": 6
            },
            "properties": {
                "hiddenByUser": True
            },
            "fields": "hiddenByUser"
        }
    })

    spreadsheet.batch_update({"requests": requests})


def main():
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    master_ws = get_or_create_ws(spreadsheet, CHAR_MASTER_SHEET_NAME)

    db_df = build_db_characters(spreadsheet)
    old_df = load_existing_master(master_ws)
    final_df = rebuild_master(db_df, old_df)

    write_master(master_ws, final_df)
    paint_and_hide(master_ws, final_df, spreadsheet)

    print("キャラ基礎情報シート更新完了")
    print(f"件数: {len(final_df)}")


if __name__ == "__main__":
    main()
