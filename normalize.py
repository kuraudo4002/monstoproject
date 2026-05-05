# -*- coding: utf-8 -*-

import pandas as pd

ATTR_RGB = {
    "火": (234 / 255, 153 / 255, 153 / 255),
    "水": (159 / 255, 197 / 255, 232 / 255),
    "木": (182 / 255, 215 / 255, 168 / 255),
    "光": (255 / 255, 229 / 255, 153 / 255),
    "闇": (213 / 255, 166 / 255, 189 / 255),
}

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

def is_none_marker(v):
    return normalize_text(v) == "無"

def has_value(v):
    return normalize_text(v) not in ["", "無"]

def is_close_rgb(a, b, tol=0.03):
    return all(abs(x - y) <= tol for x, y in zip(a, b))

def attr_from_rgb(rgb):
    for attr, target in ATTR_RGB.items():
        if is_close_rgb(rgb, target):
            return attr
    return ""

def normalize_quest_df(raw_df):
    if raw_df.empty:
        return pd.DataFrame(columns=["クエスト名", "難易度", "属性", "Sランク適正", "Aランク適正", "Bランク以下適正", "降臨枠"])

    df = raw_df.copy()
    df.columns = [normalize_text(c) for c in df.columns]

    for col in ["クエスト名", "難易度", "属性"]:
        if col in df.columns:
            df[col] = df[col].replace("", pd.NA).ffill()

    return df

def normalize_owned_df(raw_df):
    if raw_df.empty:
        return pd.DataFrame(columns=["キャラ名", "属性", "メイン", "サブ", "サブサブ", "退避キャラ名", "退避属性", "退避メイン", "退避サブ", "退避サブサブ", "理由", "参照情報", "内部キー", "退避キー"])

    df = raw_df.copy()
    df.columns = [normalize_text(c) for c in df.columns]

    for col in ["キャラ名", "属性", "退避キャラ名", "退避属性", "理由", "参照情報", "内部キー", "退避キー"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].apply(normalize_text)

    for col in ["メイン", "サブ", "サブサブ", "退避メイン", "退避サブ", "退避サブサブ"]:
        if col not in df.columns:
            df[col] = 0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    return df

def normalize_char_master_df(raw_df):
    if raw_df.empty:
        return pd.DataFrame(columns=["キャラ名", "種族", "戦型", "撃種", "内部キー"])

    df = raw_df.copy()
    df.columns = [normalize_text(c) for c in df.columns]

    for col in ["キャラ名", "種族", "戦型", "撃種", "内部キー"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].apply(normalize_text)

    return df

def normalize_master_df(raw_df):
    if raw_df.empty:
        return pd.DataFrame(columns=["カテゴリ", "キー", "値"])

    df = raw_df.copy()
    df.columns = [normalize_text(c) for c in df.columns]
    for col in df.columns:
        df[col] = df[col].apply(normalize_text)
    return df

def normalize_wakuwaku_df(raw_df):
    if raw_df.empty:
        return pd.DataFrame(columns=["キャラ名", "個体番号", "わくわく1", "わくわく2", "わくわく3", "内部キー", "個体キー"])

    df = raw_df.copy()
    df.columns = [normalize_text(c) for c in df.columns]

    for col in ["キャラ名", "わくわく1", "わくわく2", "わくわく3", "内部キー", "個体キー"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].apply(normalize_text)

    if "個体番号" not in df.columns:
        df["個体番号"] = 0
    df["個体番号"] = pd.to_numeric(df["個体番号"], errors="coerce").fillna(0).astype(int)

    return df

def expand_quest_characters(quest_df, quest_colors):
    if quest_df.empty:
        return pd.DataFrame(columns=["クエスト名", "難易度", "クエスト属性", "ランク", "キャラ名", "ベース名", "キャラ属性", "内部キー"])

    col_map = {c: i for i, c in enumerate(quest_df.columns)}

    required = ["クエスト名", "難易度", "属性", "Sランク適正", "Aランク適正", "Bランク以下適正"]
    for c in required:
        if c not in col_map:
            raise KeyError(f"クエスト情報に列がありません: {c}")

    rank_cols = [
        ("S", "Sランク適正"),
        ("A", "Aランク適正"),
        ("B", "Bランク以下適正"),
    ]

    rows = []
    for df_idx, (_, row) in enumerate(quest_df.iterrows(), start=1):
        color_row = quest_colors[df_idx] if df_idx < len(quest_colors) else []

        for rank, col_name in rank_cols:
            value = row[col_name]
            if not has_value(value):
                continue

            col_idx = col_map[col_name]
            rgb = color_row[col_idx] if col_idx < len(color_row) else (1.0, 1.0, 1.0)
            char_attr = attr_from_rgb(rgb)

            base_name = get_base_name(value)
            rows.append({
                "クエスト名": normalize_text(row["クエスト名"]),
                "難易度": normalize_text(row["難易度"]),
                "クエスト属性": normalize_text(row["属性"]),
                "ランク": rank,
                "キャラ名": normalize_text(value),
                "ベース名": base_name,
                "キャラ属性": char_attr,
                "内部キー": make_key(base_name, char_attr),
            })

    return pd.DataFrame(rows)

def normalize_all(raw_data):
    quest_df = normalize_quest_df(raw_data["quest"])
    owned_df = normalize_owned_df(raw_data["owned"])
    char_master_df = normalize_char_master_df(raw_data["char_master"])
    master_df = normalize_master_df(raw_data["master"])

    wakuwaku = {
        "メイン": normalize_wakuwaku_df(raw_data["wakuwaku"]["メイン"]),
        "サブ": normalize_wakuwaku_df(raw_data["wakuwaku"]["サブ"]),
        "サブサブ": normalize_wakuwaku_df(raw_data["wakuwaku"]["サブサブ"]),
    }

    expanded_quest_df = expand_quest_characters(quest_df, raw_data["quest_colors"])

    return {
        "quest": quest_df,
        "owned": owned_df,
        "char_master": char_master_df,
        "master": master_df,
        "wakuwaku": wakuwaku,
        "quest_expanded": expanded_quest_df,
    }
