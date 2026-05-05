# -*- coding: utf-8 -*-

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_ID = "1PZKZITDQbgqJyCTDbuj9oV25tU01sfys_bkN7Bnc6vY"
QUEST_SHEET_NAME = "クエスト情報"
OWN_SHEET_NAME = "所持数"

HEADERS = [
    "キャラ名", "メイン", "サブ", "サブサブ",
    "退避キャラ名", "退避メイン", "退避サブ", "退避サブサブ", "理由",
    "内部キー", "退避キー"
]

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

def make_key(base_name, attr):
    return f"{base_name}||{attr}"

def split_key(key):
    s = normalize_text(key)
    if "||" in s:
        name, attr = s.split("||", 1)
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

def ensure_headers(ws):
    values = ws.get_all_values()
    if not values:
        ws.update(values=[HEADERS], range_name="A1")
        return
    if values[0] != HEADERS:
        body = values[1:] if len(values) > 1 else []
        padded = []
        for row in body:
            row = row + [""] * (len(HEADERS) - len(row))
            padded.append(row[:len(HEADERS)])
        ws.clear()
        ws.update(values=[HEADERS] + padded, range_name="A1")

creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key(SPREADSHEET_ID)

quest_ws = spreadsheet.worksheet(QUEST_SHEET_NAME)
own_ws = spreadsheet.worksheet(OWN_SHEET_NAME)

# =========================
# 1. DB側を背景色ベースで作る
# =========================
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

db_rows = []

for r_idx in range(1, len(quest_values)):
    row = quest_values[r_idx]
    value_cells = row_data[r_idx].get("values", []) if r_idx < len(row_data) else []

    for c_idx in [idx_s, idx_a, idx_b]:
        cell_value = normalize_text(row[c_idx]) if c_idx < len(row) else ""
        if not has_value(cell_value):
            continue

        base_name = get_base_name(cell_value)
        cell_obj = value_cells[c_idx] if c_idx < len(value_cells) else {}
        rgb = get_bg_rgb(cell_obj)
        attr = attr_from_rgb(rgb)

        if attr == "":
            print(f"[警告] 属性色判定不可: 行={r_idx+1} 列={c_idx+1} 値={cell_value} RGB={rgb}")
            continue

        db_rows.append({
            "キャラ名": base_name,
            "属性": attr,
            "内部キー": make_key(base_name, attr),
        })

db_df = pd.DataFrame(db_rows).drop_duplicates()
if db_df.empty:
    raise ValueError("DB側キャラ一覧が空です。背景色を確認してください。")

db_df["attr_order"] = db_df["属性"].map(lambda x: ATTR_ORDER.get(x, 999))
db_df = db_df.sort_values(by=["キャラ名", "attr_order"]).reset_index(drop=True)

db_key_set = set(db_df["内部キー"].tolist())

# 名前が一意かどうか判定
name_count = db_df.groupby("キャラ名").size().to_dict()

# =========================
# 2. 所持数シート読み込み
# =========================
ensure_headers(own_ws)
own_values = own_ws.get_all_values()
odf = pd.DataFrame(own_values[1:], columns=own_values[0]).fillna("")

for col in HEADERS:
    if col not in odf.columns:
        odf[col] = ""

odf = odf[HEADERS].copy()

# 現役ブロック取得
active_rows = []
for _, row in odf.iterrows():
    name = normalize_text(row["キャラ名"])
    key = normalize_text(row["内部キー"])
    main = normalize_text(row["メイン"])
    sub = normalize_text(row["サブ"])
    subsub = normalize_text(row["サブサブ"])

    if name == "" and key == "" and main == "" and sub == "" and subsub == "":
        continue

    active_rows.append({
        "キャラ名": name,
        "メイン": main,
        "サブ": sub,
        "サブサブ": subsub,
        "内部キー": key,
    })

active_df = pd.DataFrame(active_rows)
if active_df.empty:
    active_df = pd.DataFrame(columns=["キャラ名", "メイン", "サブ", "サブサブ", "内部キー"])

# 退避ブロック取得
archive_rows = []
for _, row in odf.iterrows():
    name = normalize_text(row["退避キャラ名"])
    key = normalize_text(row["退避キー"])
    main = normalize_text(row["退避メイン"])
    sub = normalize_text(row["退避サブ"])
    subsub = normalize_text(row["退避サブサブ"])
    reason = normalize_text(row["理由"])

    if name == "" and key == "" and main == "" and sub == "" and subsub == "" and reason == "":
        continue

    archive_rows.append({
        "退避キャラ名": name,
        "退避メイン": main,
        "退避サブ": sub,
        "退避サブサブ": subsub,
        "理由": reason,
        "退避キー": key,
    })

archive_df = pd.DataFrame(archive_rows)
if archive_df.empty:
    archive_df = pd.DataFrame(columns=["退避キャラ名", "退避メイン", "退避サブ", "退避サブサブ", "理由", "退避キー"])

# 現役側のキー補完
if not active_df.empty:
    for idx, row in active_df.iterrows():
        if normalize_text(row["内部キー"]) != "":
            continue

        name = row["キャラ名"]
        if name_count.get(name, 0) == 1:
            key = db_df[db_df["キャラ名"] == name].iloc[0]["内部キー"]
            active_df.at[idx, "内部キー"] = key

# =========================
# 3. 現役のうちDBにないものを退避
# =========================
to_archive = active_df[~active_df["内部キー"].isin(db_key_set)].copy()
still_valid = active_df[active_df["内部キー"].isin(db_key_set)].copy()

if not to_archive.empty:
    to_archive = to_archive.rename(columns={
        "キャラ名": "退避キャラ名",
        "メイン": "退避メイン",
        "サブ": "退避サブ",
        "サブサブ": "退避サブサブ",
        "内部キー": "退避キー",
    })
    to_archive["理由"] = "DB不一致"
    to_archive = to_archive[["退避キャラ名", "退避メイン", "退避サブ", "退避サブサブ", "理由", "退避キー"]]
    archive_df = pd.concat([archive_df, to_archive], ignore_index=True)

# =========================
# 4. DB基準で現役ブロックを再構築
# =========================
# 既存数値マップ
active_map = {}
for _, row in still_valid.iterrows():
    key = normalize_text(row["内部キー"])
    if key == "":
        continue
    active_map[key] = {
        "メイン": normalize_text(row["メイン"]),
        "サブ": normalize_text(row["サブ"]),
        "サブサブ": normalize_text(row["サブサブ"]),
    }

rebuilt_active_rows = []
for _, row in db_df.iterrows():
    key = row["内部キー"]
    nums = active_map.get(key, {"メイン": "", "サブ": "", "サブサブ": ""})
    rebuilt_active_rows.append({
        "キャラ名": row["キャラ名"],
        "メイン": nums["メイン"],
        "サブ": nums["サブ"],
        "サブサブ": nums["サブサブ"],
        "内部キー": key,
        "属性": row["属性"],
    })

active_df = pd.DataFrame(rebuilt_active_rows)

# =========================
# 5. 退避整理
# =========================
archive_df = archive_df.drop_duplicates(
    subset=["退避キー", "退避キャラ名", "退避メイン", "退避サブ", "退避サブサブ", "理由"],
    keep="last"
)

# 退避色はキーから属性を取る
archive_attrs = []
for _, row in archive_df.iterrows():
    _, attr = split_key(row["退避キー"])
    archive_attrs.append(attr)
archive_df["属性"] = archive_attrs
archive_df["attr_order"] = archive_df["属性"].map(lambda x: ATTR_ORDER.get(x, 999))
archive_df = archive_df.sort_values(by=["退避キャラ名", "attr_order"]).reset_index(drop=True)

# =========================
# 6. 同じシートに再配置
# =========================
max_len = max(len(active_df), len(archive_df), 1)

active_df = active_df.reindex(range(max_len)).fillna("")
archive_df = archive_df.reindex(range(max_len)).fillna("")

final_df = pd.DataFrame({
    "キャラ名": active_df["キャラ名"],
    "メイン": active_df["メイン"],
    "サブ": active_df["サブ"],
    "サブサブ": active_df["サブサブ"],
    "退避キャラ名": archive_df["退避キャラ名"],
    "退避メイン": archive_df["退避メイン"],
    "退避サブ": archive_df["退避サブ"],
    "退避サブサブ": archive_df["退避サブサブ"],
    "理由": archive_df["理由"],
    "内部キー": active_df["内部キー"],
    "退避キー": archive_df["退避キー"],
})

write_values = [HEADERS] + final_df[HEADERS].fillna("").astype(str).values.tolist()

own_ws.clear()
own_ws.update(values=write_values, range_name="A1")

# =========================
# 7. 色リセット＆再塗装
# =========================
requests = []

# A列 / E列を白にリセット
for col_start in [0, 4]:
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": own_ws.id,
                "startRowIndex": 1,
                "endRowIndex": max_len + 1,
                "startColumnIndex": col_start,
                "endColumnIndex": col_start + 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 1, "green": 1, "blue": 1}
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })

# 現役A列
for i, row in final_df.iterrows():
    key = normalize_text(row["内部キー"])
    if key == "":
        continue
    _, attr = split_key(key)
    rgb = ATTR_RGB.get(attr)
    if not rgb:
        continue

    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": own_ws.id,
                "startRowIndex": i + 1,
                "endRowIndex": i + 2,
                "startColumnIndex": 0,
                "endColumnIndex": 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {
                        "red": rgb[0], "green": rgb[1], "blue": rgb[2]
                    }
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })

# 退避E列
for i, row in final_df.iterrows():
    key = normalize_text(row["退避キー"])
    if key == "":
        continue
    _, attr = split_key(key)
    rgb = ATTR_RGB.get(attr)
    if not rgb:
        continue

    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": own_ws.id,
                "startRowIndex": i + 1,
                "endRowIndex": i + 2,
                "startColumnIndex": 4,
                "endColumnIndex": 5,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {
                        "red": rgb[0], "green": rgb[1], "blue": rgb[2]
                    }
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })

# J:K を非表示
requests.append({
    "updateDimensionProperties": {
        "range": {
            "sheetId": own_ws.id,
            "dimension": "COLUMNS",
            "startIndex": 9,
            "endIndex": 11
        },
        "properties": {
            "hiddenByUser": True
        },
        "fields": "hiddenByUser"
    }
})

spreadsheet.batch_update({"requests": requests})

print("同期完了")
print(f"現役件数: {len([x for x in final_df['キャラ名'] if normalize_text(x) != ''])}")
print(f"退避件数: {len([x for x in final_df['退避キャラ名'] if normalize_text(x) != ''])}")
