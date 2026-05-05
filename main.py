# -*- coding: utf-8 -*-

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

SPREADSHEET_ID = "1PZKZITDQbgqJyCTDbuj9oV25tU01sfys_bkN7Bnc6vY"
QUEST_SHEET_NAME = "クエスト情報"
OWN_SHEET_NAME = "所持数"

# 今回のテスト条件
TARGET_QUEST = "庭園1"   # 全件で回したいときは None
USE_ACCOUNTS = ["メイン", "サブ", "サブサブ"]

ACCOUNT_ORDER = ["サブサブ", "サブ", "メイン"]
REVERSE_ORDER = ["メイン", "サブ", "サブサブ"]

# -------------------------
# 接続
# -------------------------
creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key(SPREADSHEET_ID)

# -------------------------
# 共通関数
# -------------------------
def resolve_col(df_columns, candidates, logical_name):
    for c in candidates:
        if c in df_columns:
            return c
    raise KeyError(f"列『{logical_name}』が見つかりません。実際の列名: {list(df_columns)}")

def has_value(v):
    if pd.isna(v):
        return False
    return str(v).strip() != ""

def is_none_marker(v):
    if pd.isna(v):
        return False
    return str(v).strip() == "無"

def get_base_name(name):
    s = str(name).strip()
    s = s.split("(")[0]
    s = s.split("（")[0]
    return s.strip()

def get_point(row):
    if "黎絶" in str(row["難易度"]):
        return 0
    if row["ランク"] == "S":
        return 4
    if row["ランク"] == "A":
        return 2
    if row["ランク"] == "B":
        return 1
    return 0

def get_tier(point):
    if point >= 5:
        return "S"
    if point == 4:
        return "A"
    if point == 3:
        return "B"
    return "C"

def can_use(row, acc, used_total, used_acc_char):
    name = row["ベース名"]

    if int(row[acc]) <= used_acc_char.get((acc, name), 0):
        return False

    if int(row["合計所持数"]) <= used_total.get(name, 0):
        return False

    return True

def format_party_cell(row):
    if row["char"] == "該当なし":
        return "該当なし"

    if row["borrow"]:
        return f"{row['char']}（{row['acc']}：{row['borrow']}）"

    return f"{row['char']}（{row['acc']}）"

def collect_farm_list(src_df, quest_name, col_quest, col_farm):
    farm_list = []

    for _, src_row in src_df.iterrows():
        qname = str(src_row[col_quest]).strip() if pd.notna(src_row[col_quest]) else ""
        if qname != quest_name:
            continue

        farm_value = str(src_row[col_farm]).strip() if pd.notna(src_row[col_farm]) else ""
        if farm_value == "" or farm_value == "無":
            continue

        farm_list.append(farm_value)

    # 重複除去しつつ順序維持
    farm_list = list(dict.fromkeys(farm_list))
    return farm_list

def build_party_for_quest(group, use_accounts):
    g = group.sort_values(
        by=["ランク数値", "Tier数値", "合計所持数"],
        ascending=[True, False, False]
    ).copy()

    selected = []
    used_total = {}
    used_acc_char = {}
    borrow_used = {acc: False for acc in use_accounts}
    lend_used = {acc: False for acc in use_accounts}

    # -------------------------
    # ① 各アカ最低1体
    # -------------------------
    for acc in ACCOUNT_ORDER:
        if acc not in use_accounts:
            continue

        picked = False

        # 自前優先
        for _, row in g.iterrows():
            if can_use(row, acc, used_total, used_acc_char):
                name = row["ベース名"]

                selected.append({
                    "acc": acc,
                    "char": name,
                    "borrow": None
                })

                used_total[name] = used_total.get(name, 0) + 1
                used_acc_char[(acc, name)] = used_acc_char.get((acc, name), 0) + 1
                picked = True
                break

        # 借りモン
        if not picked:
            for lender in REVERSE_ORDER:
                if lender == acc:
                    continue
                if lender not in use_accounts:
                    continue
                if lend_used[lender]:
                    continue
                if borrow_used[acc]:
                    continue

                for _, row in g.iterrows():
                    if int(row[lender]) <= 0:
                        continue

                    name = row["ベース名"]

                    if used_total.get(name, 0) >= int(row["合計所持数"]):
                        continue

                    selected.append({
                        "acc": acc,
                        "char": name,
                        "borrow": lender
                    })

                    used_total[name] = used_total.get(name, 0) + 1
                    used_acc_char[(lender, name)] = used_acc_char.get((lender, name), 0) + 1

                    borrow_used[acc] = True
                    lend_used[lender] = True
                    picked = True
                    break

                if picked:
                    break

        if not picked:
            selected.append({
                "acc": acc,
                "char": "該当なし",
                "borrow": None
            })

    # -------------------------
    # ② 4体目以降を補充
    # -------------------------
    for _, row in g.iterrows():
        if len(selected) >= 4:
            break

        name = row["ベース名"]

        # 自前優先
        for acc in ACCOUNT_ORDER:
            if acc not in use_accounts:
                continue

            if can_use(row, acc, used_total, used_acc_char):
                selected.append({
                    "acc": acc,
                    "char": name,
                    "borrow": None
                })

                used_total[name] = used_total.get(name, 0) + 1
                used_acc_char[(acc, name)] = used_acc_char.get((acc, name), 0) + 1
                break

        if len(selected) >= 4:
            break

        # 借りモンで補充
        for acc in ACCOUNT_ORDER:
            if acc not in use_accounts:
                continue
            if borrow_used[acc]:
                continue

            borrowed = False

            for lender in REVERSE_ORDER:
                if lender == acc:
                    continue
                if lender not in use_accounts:
                    continue
                if lend_used[lender]:
                    continue

                if int(row[lender]) <= 0:
                    continue

                if used_total.get(name, 0) >= int(row["合計所持数"]):
                    continue

                selected.append({
                    "acc": acc,
                    "char": name,
                    "borrow": lender
                })

                used_total[name] = used_total.get(name, 0) + 1
                used_acc_char[(lender, name)] = used_acc_char.get((lender, name), 0) + 1

                borrow_used[acc] = True
                lend_used[lender] = True
                borrowed = True
                break

            if borrowed:
                break

    # 4枠に満たない場合は詰める
    while len(selected) < 4:
        selected.append({
            "acc": None,
            "char": "該当なし",
            "borrow": None
        })

    return selected[:4]

# -------------------------
# クエスト情報取得
# -------------------------
quest_ws = spreadsheet.worksheet(QUEST_SHEET_NAME)
quest_rows = quest_ws.get_all_records()
df = pd.DataFrame(quest_rows)
df.columns = [str(c).strip() for c in df.columns]

COL_QUEST = resolve_col(df.columns, ["クエスト名"], "クエスト名")
COL_DIFF  = resolve_col(df.columns, ["難易度"], "難易度")
COL_ELEM  = resolve_col(df.columns, ["属性"], "属性")
COL_S     = resolve_col(df.columns, ["Sランク適正"], "Sランク適正")
COL_A     = resolve_col(df.columns, ["Aランク適正"], "Aランク適正")
COL_B     = resolve_col(df.columns, ["Bランク以下適正", "B以下適正"], "Bランク以下適正")
COL_FARM  = resolve_col(df.columns, ["降臨枠"], "降臨枠")

df[COL_QUEST] = df[COL_QUEST].replace("", pd.NA).ffill()
df[COL_DIFF]  = df[COL_DIFF].replace("", pd.NA).ffill()
df[COL_ELEM]  = df[COL_ELEM].replace("", pd.NA).ffill()

# -------------------------
# 正規化（S/A/Bを縦展開）
# ※ 降臨枠はここに混ぜない
# -------------------------
normalized_rows = []

for _, r in df.iterrows():
    if has_value(r[COL_S]) and not is_none_marker(r[COL_S]):
        normalized_rows.append({
            "クエスト名": r[COL_QUEST],
            "難易度": r[COL_DIFF],
            "属性": r[COL_ELEM],
            "ランク": "S",
            "キャラ名": str(r[COL_S]).strip(),
        })

    if has_value(r[COL_A]) and not is_none_marker(r[COL_A]):
        normalized_rows.append({
            "クエスト名": r[COL_QUEST],
            "難易度": r[COL_DIFF],
            "属性": r[COL_ELEM],
            "ランク": "A",
            "キャラ名": str(r[COL_A]).strip(),
        })

    if has_value(r[COL_B]) and not is_none_marker(r[COL_B]):
        normalized_rows.append({
            "クエスト名": r[COL_QUEST],
            "難易度": r[COL_DIFF],
            "属性": r[COL_ELEM],
            "ランク": "B",
            "キャラ名": str(r[COL_B]).strip(),
        })

clean_df = pd.DataFrame(normalized_rows)

if clean_df.empty:
    raise ValueError("適正キャラデータが空です。クエスト情報シートを確認してください。")

clean_df["ベース名"] = clean_df["キャラ名"].apply(get_base_name)

# -------------------------
# Tier計算
# -------------------------
clean_df["ポイント"] = clean_df.apply(get_point, axis=1)

grouped = clean_df.groupby("ベース名", as_index=False)["ポイント"].sum()
grouped["Tier"] = grouped["ポイント"].apply(get_tier)

tier_order = {"S": 3, "A": 2, "B": 1, "C": 0}
grouped["Tier数値"] = grouped["Tier"].map(tier_order)

# -------------------------
# 所持数シート読み込み
# -------------------------
own_ws = spreadsheet.worksheet(OWN_SHEET_NAME)
own_rows = own_ws.get_all_records()
own_df = pd.DataFrame(own_rows)

if own_df.empty:
    own_df = pd.DataFrame(columns=["キャラ名", "メイン", "サブ", "サブサブ"])

own_df.columns = [str(c).strip() for c in own_df.columns]

if "キャラ名" not in own_df.columns:
    own_df["キャラ名"] = ""

for col in ["メイン", "サブ", "サブサブ"]:
    if col not in own_df.columns:
        own_df[col] = 0
    own_df[col] = pd.to_numeric(own_df[col], errors="coerce").fillna(0).astype(int)

own_df["キャラ名"] = own_df["キャラ名"].astype(str).str.strip()
own_df["合計所持数"] = own_df["メイン"] + own_df["サブ"] + own_df["サブサブ"]

# -------------------------
# Tierと所持数を結合
# -------------------------
merged_owned = grouped.merge(
    own_df,
    left_on="ベース名",
    right_on="キャラ名",
    how="left",
)

for col in ["メイン", "サブ", "サブサブ", "合計所持数"]:
    merged_owned[col] = merged_owned[col].fillna(0).astype(int)

# -------------------------
# クエスト別候補（所持済みのみ）
# -------------------------
quest_owned = clean_df.merge(
    merged_owned[["ベース名", "Tier", "Tier数値", "メイン", "サブ", "サブサブ", "合計所持数"]],
    on="ベース名",
    how="left",
)

quest_owned = quest_owned[quest_owned["合計所持数"] > 0].copy()

rank_order = {"S": 0, "A": 1, "B": 2}
quest_owned["ランク数値"] = quest_owned["ランク"].map(rank_order)

if TARGET_QUEST is not None:
    quest_owned = quest_owned[quest_owned["クエスト名"] == TARGET_QUEST].copy()

quest_owned = quest_owned.sort_values(
    by=["クエスト名", "ランク数値", "Tier数値", "合計所持数"],
    ascending=[True, True, False, False],
)

# -------------------------
# 候補表示用データ
# ※ 同キャラ重複を潰して見やすくする
# -------------------------
candidate_rows = []

for quest, group in quest_owned.groupby("クエスト名"):
    display_group = (
        group.sort_values(
            by=["ランク数値", "Tier数値", "合計所持数"],
            ascending=[True, False, False]
        )
        .drop_duplicates(subset=["ベース名"], keep="first")
        .copy()
    )

    for _, row in display_group.iterrows():
        candidate_rows.append({
            "クエスト名": quest,
            "ランク": row["ランク"],
            "キャラ名": row["ベース名"],
            "Tier": row["Tier"],
            "メイン": int(row["メイン"]),
            "サブ": int(row["サブ"]),
            "サブサブ": int(row["サブサブ"]),
            "合計所持数": int(row["合計所持数"]),
        })

candidate_df = pd.DataFrame(candidate_rows)

# -------------------------
# 4体編成結果を表形式で作成
# -------------------------
result_rows = []

for quest, group in quest_owned.groupby("クエスト名"):
    selected = build_party_for_quest(group, USE_ACCOUNTS)
    farm_list = collect_farm_list(df, quest, COL_QUEST, COL_FARM)

    result_rows.append({
        "クエスト名": quest,
        "1P": format_party_cell(selected[0]),
        "2P": format_party_cell(selected[1]),
        "3P": format_party_cell(selected[2]),
        "4P": format_party_cell(selected[3]),
        "降臨枠": "、".join(farm_list) if farm_list else "該当なし",
    })

result_df = pd.DataFrame(result_rows)

# -------------------------
# コンソール出力
# -------------------------
print("=== 所持済み候補 ===")

if candidate_df.empty:
    print("\n該当なし")
else:
    for quest, group in candidate_df.groupby("クエスト名"):
        print(f"\n■ {quest}")
        for _, row in group.iterrows():
            print(
                f"{row['ランク']} | {row['キャラ名']} | "
                f"Tier:{row['Tier']} | "
                f"メイン:{row['メイン']} サブ:{row['サブ']} サブサブ:{row['サブサブ']}"
            )

print("\n=== 4体編成（借りモンあり） ===")

if result_df.empty:
    print("\n該当なし")
else:
    for _, row in result_df.iterrows():
        print(f"\n■ {row['クエスト名']}")
        print(f"1P：{row['1P']}")
        print(f"2P：{row['2P']}")
        print(f"3P：{row['3P']}")
        print(f"4P：{row['4P']}")
        print("降臨枠：")
        if row["降臨枠"] == "該当なし":
            print(" - 該当なし")
        else:
            for farm in str(row["降臨枠"]).split("、"):
                print(f" - {farm}")

# -------------------------
# 確認用
# 次ステップでこの result_df をそのままシート出力に使える
# -------------------------
print("\n=== 結果表データ ===")
if result_df.empty:
    print("該当なし")
else:
    print(result_df.to_string(index=False))
