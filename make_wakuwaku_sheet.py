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

OWN_SHEET_NAME = "所持数"
CHAR_MASTER_SHEET_NAME = "キャラ基礎情報"

WAKU_SHEETS = {
    "メイン": "わくわく_メイン",
    "サブ": "わくわく_サブ",
    "サブサブ": "わくわく_サブサブ",
}

HEADERS = ["キャラ名", "個体番号", "わくわく1", "わくわく2", "わくわく3", "内部キー", "個体キー"]


def normalize_text(x):
    if pd.isna(x):
        return ""
    return str(x).strip()


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


def get_or_create_ws(spreadsheet, title):
    try:
        return spreadsheet.worksheet(title)
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=500, cols=10)
        ws.update(values=[HEADERS], range_name="A1")
        return ws


def load_df(ws):
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame()

    df = pd.DataFrame(values[1:], columns=values[0]).fillna("")
    df.columns = [normalize_text(c) for c in df.columns]

    for col in df.columns:
        df[col] = df[col].apply(normalize_text)

    return df


def find_first_existing_column(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    return None


def split_internal_key(internal_key):
    s = normalize_text(internal_key)
    if "||" in s:
        name, attr = s.split("||", 1)
        return name, attr
    return s, ""


def get_char_key_map(char_master_df):
    key_map = {}

    if char_master_df.empty:
        return key_map

    name_col = find_first_existing_column(char_master_df, ["キャラ名"])
    key_col = find_first_existing_column(char_master_df, ["内部キー"])

    if not name_col or not key_col:
        return key_map

    for _, row in char_master_df.iterrows():
        name = normalize_text(row.get(name_col, ""))
        key = normalize_text(row.get(key_col, ""))
        if name and key and name not in key_map:
            key_map[name] = key

    return key_map


def build_source_rows(own_df, char_master_df):
    key_map = get_char_key_map(char_master_df)

    name_col = find_first_existing_column(own_df, ["キャラ名", "名前"])
    main_col = find_first_existing_column(own_df, ["メイン"])
    sub_col = find_first_existing_column(own_df, ["サブ"])
    sub2_col = find_first_existing_column(own_df, ["サブサブ"])
    key_col = find_first_existing_column(own_df, ["内部キー"])

    print("所持数シート列:", list(own_df.columns))
    print("解決列:", {
        "name_col": name_col,
        "main_col": main_col,
        "sub_col": sub_col,
        "sub2_col": sub2_col,
        "key_col": key_col,
    })

    if not name_col or not main_col or not sub_col or not sub2_col:
        raise ValueError("所持数シートに必要列がありません。キャラ名 / メイン / サブ / サブサブ を確認してください。")

    rows = []

    for _, row in own_df.iterrows():
        name = normalize_text(row.get(name_col, ""))
        if not name:
            continue

        internal_key = normalize_text(row.get(key_col, "")) if key_col else ""
        if not internal_key:
            internal_key = key_map.get(name, "")

        _, attr = split_internal_key(internal_key)

        account_pairs = [
            ("メイン", main_col),
            ("サブ", sub_col),
            ("サブサブ", sub2_col),
        ]

        for acc, col_name in account_pairs:
            raw = normalize_text(row.get(col_name, "0"))

            try:
                count = int(float(raw)) if raw else 0
            except:
                count = 0

            for num in range(1, count + 1):
                # サイト側の char_id と同じ形式にする
                if attr:
                    item_key = f"{name}||{attr}||{acc}||{num}"
                else:
                    item_key = f"{name}||||{acc}||{num}"

                rows.append({
                    "アカウント": acc,
                    "キャラ名": name,
                    "個体番号": str(num),
                    "内部キー": internal_key,
                    "個体キー": item_key,
                })

    return pd.DataFrame(rows)


def rebuild_sheet_for_account(account_name, source_df, old_df):
    old_map = {}

    if not old_df.empty and "個体キー" in old_df.columns:
        for _, row in old_df.iterrows():
            item_key = normalize_text(row.get("個体キー", ""))
            if not item_key:
                continue

            old_map[item_key] = {
                "わくわく1": normalize_text(row.get("わくわく1", "")),
                "わくわく2": normalize_text(row.get("わくわく2", "")),
                "わくわく3": normalize_text(row.get("わくわく3", "")),
            }

    target = source_df[source_df["アカウント"] == account_name].copy()

    rebuilt = []
    for _, row in target.iterrows():
        item_key = row["個体キー"]
        old = old_map.get(item_key, {
            "わくわく1": "",
            "わくわく2": "",
            "わくわく3": "",
        })

        rebuilt.append({
            "キャラ名": row["キャラ名"],
            "個体番号": row["個体番号"],
            "わくわく1": old["わくわく1"],
            "わくわく2": old["わくわく2"],
            "わくわく3": old["わくわく3"],
            "内部キー": row["内部キー"],
            "個体キー": row["個体キー"],
        })

    return pd.DataFrame(rebuilt, columns=HEADERS)


def main():
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    own_ws = spreadsheet.worksheet(OWN_SHEET_NAME)
    char_master_ws = spreadsheet.worksheet(CHAR_MASTER_SHEET_NAME)

    own_df = load_df(own_ws)
    char_master_df = load_df(char_master_ws)

    print("所持数 行数:", len(own_df))
    print("キャラ基礎情報 行数:", len(char_master_df))

    source_df = build_source_rows(own_df, char_master_df)

    if source_df.empty:
        print("所持数から個体行を作れませんでした")
        return

    print("生成予定個体数:", len(source_df))

    for acc, sheet_name in WAKU_SHEETS.items():
        ws = get_or_create_ws(spreadsheet, sheet_name)
        ensure_headers(ws)

        old_df = load_df(ws)
        new_df = rebuild_sheet_for_account(acc, source_df, old_df)

        values = [HEADERS] + new_df.fillna("").astype(str).values.tolist()

        ws.clear()
        ws.update(values=values, range_name="A1")

        print(f"{sheet_name} 更新完了: {len(new_df)} 行")

    print("わくわくシート再構築完了")


if __name__ == "__main__":
    main()
