# -*- coding: utf-8 -*-

import pandas as pd

def get_point(row):
    diff = str(row["難易度"])
    rank = row["ランク"]

    # 黎絶は除外
    if "黎絶" in diff:
        return 0

    # 爆絶・超絶は0.5倍率
    multiplier = 1.0
    if "爆絶" in diff or "超絶" in diff:
        multiplier = 0.5

    if rank == "S":
        base = 4
    elif rank == "A":
        base = 2
    elif rank == "B":
        base = 1
    else:
        base = 0

    return base * multiplier


def calc_tier(expanded_df):
    if expanded_df.empty:
        return pd.DataFrame(columns=["ベース名", "ポイント", "Tier"])

    df = expanded_df.copy()

    # ポイント付与
    df["ポイント"] = df.apply(get_point, axis=1)

    # キャラごと合計
    grouped = df.groupby("ベース名", as_index=False)["ポイント"].sum()

    # Tier判定（四捨五入）
    def get_tier(point):
        p = round(point)

        if p >= 5:
            return "S"
        elif p == 4:
            return "A"
        elif p == 3:
            return "B"
        else:
            return "C"

    grouped["Tier"] = grouped["ポイント"].apply(get_tier)

    # 並び用
    tier_order = {"S": 3, "A": 2, "B": 1, "C": 0}
    grouped["Tier数値"] = grouped["Tier"].map(tier_order)

    # ソート
    grouped = grouped.sort_values(
        by=["Tier数値", "ポイント"],
        ascending=[False, False]
    )

    return grouped