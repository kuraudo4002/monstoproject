# -*- coding: utf-8 -*-

import pandas as pd


def _normalize_text(x):
    if x is None:
        return ""
    return str(x).strip()


def _to_int_series(series):
    return pd.to_numeric(series, errors="coerce").fillna(0).astype(int)


def build_party_simple(df, owned_df, target_quest):
    if df is None or len(df) == 0:
        return []

    if owned_df is None or len(owned_df) == 0:
        return []

    if "クエスト名" not in df.columns:
        return []

    work = df.copy()
    work["クエスト名"] = work["クエスト名"].map(_normalize_text)
    target_quest = _normalize_text(target_quest)
    work = work[work["クエスト名"] == target_quest].copy()

    if work.empty:
        return []

    # 必須列チェック
    required_quest_cols = ["キャラ名", "ベース名", "キャラ属性", "ランク", "内部キー"]
    for col in required_quest_cols:
        if col not in work.columns:
            return []

    if "内部キー" not in owned_df.columns:
        return []

    owned = owned_df.copy()

    # 所持数列を保証
    for col in ["メイン", "サブ", "サブサブ"]:
        if col not in owned.columns:
            owned[col] = 0

    owned["内部キー"] = owned["内部キー"].map(_normalize_text)
    owned["メイン"] = _to_int_series(owned["メイン"])
    owned["サブ"] = _to_int_series(owned["サブ"])
    owned["サブサブ"] = _to_int_series(owned["サブサブ"])

    # 内部キー単位で集約
    owned_grouped = (
        owned.groupby("内部キー", as_index=False)[["メイン", "サブ", "サブサブ"]]
        .sum()
    )

    # 内部キーで突き合わせ
    work["内部キー"] = work["内部キー"].map(_normalize_text)
    merged = work.merge(
        owned_grouped,
        on="内部キー",
        how="left"
    )

    for col in ["メイン", "サブ", "サブサブ"]:
        merged[col] = _to_int_series(merged[col])

    merged["合計所持数"] = merged["メイン"] + merged["サブ"] + merged["サブサブ"]

    # 所持しているキャラだけ
    merged = merged[merged["合計所持数"] > 0].copy()

    if merged.empty:
        return []

    # ランク順
    rank_order = {"S": 0, "A": 1, "B": 2}
    merged["ランク"] = merged["ランク"].map(_normalize_text)
    merged["ランク数値"] = merged["ランク"].map(rank_order).fillna(99)

    # 表示・後続処理用に shape を揃える
    merged["キャラ名"] = merged["キャラ名"].map(_normalize_text)
    merged["ベース名"] = merged["ベース名"].map(_normalize_text)
    merged["キャラ属性"] = merged["キャラ属性"].map(_normalize_text)

    # S優先、次に所持数が多い順
    merged = merged.sort_values(
        by=["ランク数値", "合計所持数", "キャラ名"],
        ascending=[True, False, True]
    )

    # service.py は row["ベース名"] を char として使うが、
    # 今回は進化先つき表示を優先したいので キャラ名 をベース名として渡す
    merged["ベース名"] = merged["キャラ名"]

    return merged.head(4).to_dict("records")


def assign_accounts(party_list):
    account_order = ["\u30b5\u30d6\u30b5\u30d6", "\u30b5\u30d6", "\u30e1\u30a4\u30f3"]
    reverse_order = ["\u30e1\u30a4\u30f3", "\u30b5\u30d6", "\u30b5\u30d6\u30b5\u30d6"]

    result = []
    borrow_used = {acc: False for acc in account_order}
    lend_used = {acc: False for acc in account_order}

    def rank_score(rank_text):
        rank_text = _normalize_text(rank_text)
        order = {"S": 3, "A": 2, "B": 1}
        return order.get(rank_text, 0)

    def make_record(row, acc, borrow_from=None):
        return {
            "char": row.get("\u30d9\u30fc\u30b9\u540d", ""),
            "acc": acc,
            "borrow": borrow_from,
            "\u30ad\u30e3\u30e9\u5c5e\u6027": row.get("\u30ad\u30e3\u30e9\u5c5e\u6027", ""),
            "\u30e9\u30f3\u30af": row.get("\u30e9\u30f3\u30af", ""),
        }

    def choose_best_for_acc(acc):
        candidates = []

        for row_idx, row in enumerate(party_list):
            if int(row.get(acc, 0)) > 0:
                candidates.append((
                    rank_score(row.get("\u30e9\u30f3\u30af", "")),
                    1,
                    -row_idx,
                    "self",
                    row,
                    None,
                ))

        if not borrow_used[acc]:
            for lender in reverse_order:
                if lender == acc:
                    continue
                if lend_used[lender]:
                    continue

                for row_idx, row in enumerate(party_list):
                    if int(row.get(lender, 0)) > 0:
                        candidates.append((
                            rank_score(row.get("\u30e9\u30f3\u30af", "")),
                            0,
                            -row_idx,
                            "borrow",
                            row,
                            lender,
                        ))

        if not candidates:
            return None

        candidates.sort(reverse=True)
        _, _, _, kind, row, lender = candidates[0]
        return kind, row, lender

    def consume_for_acc(acc, picked):
        kind, row, lender = picked

        if kind == "self":
            row[acc] -= 1
            return make_record(row, acc, None)

        row[lender] -= 1
        borrow_used[acc] = True
        lend_used[lender] = True
        return make_record(row, acc, lender)

    for acc in account_order:
        picked = choose_best_for_acc(acc)
        if picked is None:
            result.append({
                "char": "\u8a72\u5f53\u306a\u3057",
                "acc": acc,
                "borrow": None,
                "\u30ad\u30e3\u30e9\u5c5e\u6027": "",
                "\u30e9\u30f3\u30af": "",
            })
        else:
            result.append(consume_for_acc(acc, picked))

    while len(result) < 4:
        global_candidates = []

        for acc in account_order:
            picked = choose_best_for_acc(acc)
            if picked is None:
                continue

            kind, row, lender = picked
            global_candidates.append((
                rank_score(row.get("\u30e9\u30f3\u30af", "")),
                1 if kind == "self" else 0,
                acc,
                kind,
                row,
                lender,
            ))

        if not global_candidates:
            break

        global_candidates.sort(reverse=True)
        _, _, acc, kind, row, lender = global_candidates[0]
        result.append(consume_for_acc(acc, (kind, row, lender)))

    return result
