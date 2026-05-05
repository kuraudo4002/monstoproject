# -*- coding: utf-8 -*-

import re
import time
from collections import defaultdict
from db_loader import load_all
from normalize import normalize_all
from tier_logic import calc_tier
from party_logic import build_party_simple, assign_accounts
from wakuwaku_ai import (
    suggest_wakuwaku,
    judge_role,
    get_role_counts,
    get_party_balance_comment,
    build_party_affinity_context,
)

CACHE_SECONDS = 120

_cache = {
    "loaded_at": 0,
    "data": None,
    "tier": None,
}


def get_cached():
    now = time.time()

    if _cache["data"] is None or (now - _cache["loaded_at"]) > CACHE_SECONDS:
        print("再読み込み中...")

        raw = load_all()
        data = normalize_all(raw)
        tier = calc_tier(data["quest_expanded"])

        _cache["data"] = data
        _cache["tier"] = tier
        _cache["loaded_at"] = now

    return _cache["data"], _cache["tier"]


def make_char_id(name, attr, acc, num):
    return f"{name}||{attr}||{acc}||{num}"


def normalize_text(x):
    if x is None:
        return ""
    return str(x).strip()


def strip_form_name(name):
    name = normalize_text(name)
    name = name.replace("（", "(").replace("）", ")")
    name = re.sub(r"\(.*?\)", "", name).strip()
    return name


def get_char_master_info(char_master_df, name, attr):
    if char_master_df.empty:
        return {
            "\u7a2e\u65cf": "",
            "\u6226\u578b": "",
            "\u6483\u7a2e": "",
        }

    name = normalize_text(name)
    attr = normalize_text(attr)
    base_name = strip_form_name(name)

    col_internal_key = "\u5185\u90e8\u30ad\u30fc"
    col_name = "\u30ad\u30e3\u30e9\u540d"
    col_attr = "\u5c5e\u6027"
    col_tribe = "\u7a2e\u65cf"
    col_style = "\u6226\u578b"
    col_battle_type = "\u6483\u7a2e"

    candidates = [
        f"{name}||{attr}",
        f"{base_name}||{attr}",
    ]

    if col_internal_key in char_master_df.columns:
        for internal_key in candidates:
            hit = char_master_df[char_master_df[col_internal_key] == internal_key]
            if not hit.empty:
                row = hit.iloc[0]
                return {
                    col_tribe: normalize_text(row.get(col_tribe, "")),
                    col_style: normalize_text(row.get(col_style, "")),
                    col_battle_type: normalize_text(row.get(col_battle_type, "")),
                }

    work = char_master_df.copy()

    if col_name in work.columns:
        work["_name_norm"] = work[col_name].fillna("").astype(str).map(normalize_text)
        work["_base_name_norm"] = work["_name_norm"].map(strip_form_name)

        if col_attr in work.columns:
            work["_attr_norm"] = work[col_attr].fillna("").astype(str).map(normalize_text)
            work_attr = work[work["_attr_norm"] == attr]
            if not work_attr.empty:
                work = work_attr

        hit = work[work["_name_norm"] == name]
        if not hit.empty:
            row = hit.iloc[0]
            return {
                col_tribe: normalize_text(row.get(col_tribe, "")),
                col_style: normalize_text(row.get(col_style, "")),
                col_battle_type: normalize_text(row.get(col_battle_type, "")),
            }

        hit = work[work["_base_name_norm"] == base_name]
        if not hit.empty:
            row = hit.iloc[0]
            return {
                col_tribe: normalize_text(row.get(col_tribe, "")),
                col_style: normalize_text(row.get(col_style, "")),
                col_battle_type: normalize_text(row.get(col_battle_type, "")),
            }

        hit = work[work["_name_norm"].str.startswith(base_name, na=False)]
        if not hit.empty:
            row = hit.iloc[0]
            return {
                col_tribe: normalize_text(row.get(col_tribe, "")),
                col_style: normalize_text(row.get(col_style, "")),
                col_battle_type: normalize_text(row.get(col_battle_type, "")),
            }

    return {
        "\u7a2e\u65cf": "",
        "\u6226\u578b": "",
        "\u6483\u7a2e": "",
    }






def rank_weight_simple(rank):
    rank = normalize_text(rank).upper()
    if rank == "S":
        return 4
    if rank == "A":
        return 3
    if rank == "B":
        return 2
    return 1


def choose_support_triplet_simple():
    return [
        "\u5c06\u547d",
        "\u5175\u547d",
        "\u30b1\u30ac\u6e1b\u308a",
    ]


def build_attack_triplet_simple(family):
    if family == "style":
        return [
            "\u6226\u578b\u306e\u52a0\u6483",
            "\u6226\u578b\u306e\u52a0\u6483\u901f",
            "\u6226\u578b\u306e\u52a0\u547d\u6483",
        ]
    if family == "battle_type":
        return [
            "\u6483\u7a2e\u306e\u52a0\u6483",
            "\u6483\u7a2e\u306e\u52a0\u6483\u901f",
            "\u6483\u7a2e\u306e\u52a0\u547d\u6483",
        ]
    return [
        "\u540c\u65cf\u306e\u52a0\u6483",
        "\u540c\u65cf\u306e\u52a0\u6483\u901f",
        "\u540c\u65cf\u306e\u52a0\u547d\u6483",
    ]


def family_point(family):
    if family == "tribe":
        return 2
    if family == "style":
        return 1
    if family == "battle_type":
        return 1
    return 0


def family_value(row, family):
    if family == "tribe":
        return normalize_text(row.get("tribe", ""))
    if family == "style":
        return normalize_text(row.get("style", ""))
    if family == "battle_type":
        return normalize_text(row.get("battle_type", ""))
    return ""


def all_same_family(rows, family):
    vals = [family_value(r, family) for r in rows]
    vals = [v for v in vals if v]
    return bool(vals) and len(set(vals)) == 1 and len(vals) == len(rows)


def can_use_support(rows):
    if len(rows) != 4:
        return False
    return (
        all_same_family(rows, "tribe")
        and all_same_family(rows, "style")
        and all_same_family(rows, "battle_type")
    )


def row_priority_tuple(row):
    # ????? suitable_count / owned_count ? temp_rows ??????? 0 ???
    return (
        rank_weight_simple(row.get("rank", "")),
        int(row.get("suitable_count", 0)),
        int(row.get("owned_count", 0)),
        -int(row.get("_index", 0)),
    )


def choose_axis_row(rows):
    ranked = rows[:]
    ranked.sort(key=row_priority_tuple, reverse=True)
    return ranked[0]


def choose_support_row(rows, axis_row):
    non_axis = [r for r in rows if r["char_id"] != axis_row["char_id"]]
    if not non_axis:
        return None
    non_axis.sort(key=row_priority_tuple, reverse=True)
    return non_axis[-1]


def assignment_score(rows, assigned):
    """
    assigned: {char_id: family}
    family: tribe/style/battle_type

    ??????????
    ?? family ???????????????????
    ?:
      tribe + ?? ?1?????
      tribe + ?? ??????
      battle_type + ?? ?1?????
      battle_type + ?? ??????
    """
    used_groups = set()
    total = 0

    ordered_rows = sorted(rows, key=row_priority_tuple, reverse=True)

    for row in ordered_rows:
        cid = normalize_text(row.get("char_id", ""))
        family = assigned.get(cid, "")
        if not family:
            continue

        group_value = family_value(row, family)
        if not group_value:
            continue

        key = (family, group_value)
        if key in used_groups:
            continue

        used_groups.add(key)

        # ???????????? ? family?
        group_count = sum(
            1
            for other in rows
            if family_value(other, family) == group_value and group_value
        )
        total += group_count * family_point(family)

    # ???:
    # 1. ??? row ???? family ????
    # 2. style ? battle_type ????? battle_type ?????
    detail = []
    for row in ordered_rows:
        cid = normalize_text(row.get("char_id", ""))
        fam = assigned.get(cid, "")
        detail.append((
            family_point(fam),
            1 if fam == "battle_type" else 0,
            1 if fam == "style" else 0,
        ))

    return (total,) + tuple(detail)


def best_attack_assignment(rows, axis_row):
    families = ["tribe", "style", "battle_type"]
    axis_id = normalize_text(axis_row.get("char_id", ""))

    others = [r for r in rows if normalize_text(r.get("char_id", "")) != axis_id]

    best_assigned = None
    best_score = None

    def dfs(i, current):
        nonlocal best_assigned, best_score

        if i >= len(others):
            assigned = {axis_id: "tribe"}
            assigned.update(current)

            score = assignment_score(rows, assigned)
            if best_score is None or score > best_score:
                best_score = score
                best_assigned = dict(assigned)
            return

        row = others[i]
        cid = normalize_text(row.get("char_id", ""))

        for fam in families:
            current[cid] = fam
            dfs(i + 1, current)
            del current[cid]

    dfs(0, {})
    return best_assigned or {axis_id: "tribe"}


def build_party_suggest_map(temp_rows):
    valid_rows = [r for r in temp_rows if r["name"] != "\u8a72\u5f53\u306a\u3057" and r["char_id"]]

    suggest_map = {}
    if not valid_rows:
        return suggest_map

    axis_row = choose_axis_row(valid_rows)

    if can_use_support(valid_rows):
        support_row = choose_support_row(valid_rows, axis_row)
        if support_row is not None:
            suggest_map[support_row["char_id"]] = choose_support_triplet_simple()

        attackers = [r for r in valid_rows if support_row is None or r["char_id"] != support_row["char_id"]]
        attackers.sort(key=row_priority_tuple, reverse=True)

        ordered_attackers = [axis_row] + [r for r in attackers if r["char_id"] != axis_row["char_id"]]
        family_queue = ["tribe", "style", "battle_type"]

        for idx, r in enumerate(ordered_attackers):
            fam = family_queue[idx] if idx < len(family_queue) else "tribe"
            suggest_map[r["char_id"]] = build_attack_triplet_simple(fam)

        return suggest_map

    assigned = best_attack_assignment(valid_rows, axis_row)

    for r in valid_rows:
        cid = normalize_text(r.get("char_id", ""))
        fam = assigned.get(cid, "tribe")
        suggest_map[cid] = build_attack_triplet_simple(fam)

    return suggest_map


def _split_quest_cell(value):
    s = normalize_text(value)
    if not s:
        return []
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    parts = []
    for chunk in s.split("\n"):
        for part in chunk.split(","):
            p = normalize_text(part)
            if p:
                parts.append(p)
    return parts


def get_owned_count_for_char(data, name, attr):
    owned_df = data["owned"].copy()
    if owned_df.empty:
        return 0

    target_keys = [
        f"{normalize_text(name)}||{normalize_text(attr)}",
        f"{strip_form_name(name)}||{normalize_text(attr)}",
    ]

    col_key = "\u5185\u90e8\u30ad\u30fc"
    cols_owned = [
        "\u30e1\u30a4\u30f3",
        "\u30b5\u30d6",
        "\u30b5\u30d6\u30b5\u30d6",
    ]

    if col_key not in owned_df.columns:
        return 0

    owned_df[col_key] = owned_df[col_key].map(normalize_text)
    hit = owned_df[owned_df[col_key].isin(target_keys)]
    if hit.empty:
        return 0

    total = 0
    for col in cols_owned:
        if col in hit.columns:
            total += int(hit[col].fillna(0).astype(float).sum())
    return total


def get_suitable_count_for_char(data, name, attr):
    qx = data["quest_expanded"].copy()
    if qx.empty:
        return 0

    target_keys = {
        f"{normalize_text(name)}||{normalize_text(attr)}",
        f"{strip_form_name(name)}||{normalize_text(attr)}",
    }

    col_key = "\u5185\u90e8\u30ad\u30fc"

    if col_key in qx.columns:
        qx[col_key] = qx[col_key].map(normalize_text)
        hit = qx[qx[col_key].isin(target_keys)]
    else:
        hit = qx.iloc[0:0]

    return len(hit)

def get_party_result(quest):
    data, _ = get_cached()

    party = build_party_simple(
        data["quest_expanded"],
        data["owned"],
        quest
    )

    assigned = assign_accounts(party)

    counter = defaultdict(int)
    temp_rows = []

    for i, row in enumerate(assigned, start=1):
        name = normalize_text(row.get("char", ""))
        attr = normalize_text(row.get("\u30ad\u30e3\u30e9\u5c5e\u6027", ""))
        rank = normalize_text(row.get("\u30e9\u30f3\u30af", ""))
        acc = normalize_text(row.get("acc", ""))
        is_borrowed = bool(row.get("borrow"))

        if not rank and name != "\u8a72\u5f53\u306a\u3057":
            for p in party:
                p_name = normalize_text(p.get("\u30d9\u30fc\u30b9\u540d", "")) or normalize_text(p.get("\u30ad\u30e3\u30e9\u540d", ""))
                p_attr = normalize_text(p.get("\u30ad\u30e3\u30e9\u5c5e\u6027", ""))
                if p_name == name and p_attr == attr:
                    rank = normalize_text(p.get("\u30e9\u30f3\u30af", ""))
                    break

        if name == "\u8a72\u5f53\u306a\u3057":
            char_id = ""
            waku = []
            master_info = {
                "\u7a2e\u65cf": "",
                "\u6226\u578b": "",
                "\u6483\u7a2e": "",
            }
            owned_count = 0
            suitable_count = 0
        else:
            key = f"{name}||{attr}||{acc}"
            counter[key] += 1
            num = counter[key]

            char_id = make_char_id(name, attr, acc, num)
            master_info = get_char_master_info(data["char_master"], name, attr)
            owned_count = get_owned_count_for_char(data, name, attr)
            suitable_count = get_suitable_count_for_char(data, name, attr)

            waku = []

        if row.get("borrow"):
            text = f"{name}\uFF08{acc}\uFF1A{row['borrow']}\uFF09[{rank}]"
        else:
            text = f"{name}\uFF08{acc}\uFF09[{rank}]"

        current_role = "\u8cb8\u3057\u30e2\u30f3" if is_borrowed else judge_role(waku)

        temp_rows.append({
            "slot": f"{i}P",
            "text": text,
            "attr": attr,
            "char_id": char_id,
            "wakuwaku": waku,
            "current_role": current_role,
            "tribe": master_info["\u7a2e\u65cf"],
            "battle_type": master_info["\u6483\u7a2e"],
            "style": master_info["\u6226\u578b"],
            "is_borrowed": is_borrowed,
            "name": name,
            "rank": rank,
            "_index": i,
            "owned_count": owned_count,
            "suitable_count": suitable_count,
        })

    context_rows = []
    for row in temp_rows:
        if row["is_borrowed"]:
            continue
        if row["name"] == "該当なし":
            continue

        context_rows.append({
            "name": row["name"],
            "tribe": row["tribe"],
            "battle_type": row["battle_type"],
            "style": row["style"],
            "current_role": row["current_role"],
            "wakuwaku": row["wakuwaku"],
            "char_id": row.get("char_id", ""),
        })

    context = build_party_affinity_context(context_rows)

    suggest_map = build_party_suggest_map(temp_rows)

    result = []
    for row in temp_rows:
        if row["name"] == "????":
            suggest = []
            suggest_role = ""
        else:
            suggest = suggest_map.get(row["char_id"], [])
            suggest_role = judge_role(suggest)

        result.append({
            "slot": row["slot"],
            "text": row["text"],
            "attr": row["attr"],
            "char_id": row["char_id"],
            "wakuwaku": row["wakuwaku"],
            "suggest": suggest,
            "current_role": row["current_role"],
            "suggest_role": suggest_role,
            "tribe": row["tribe"],
            "battle_type": row["battle_type"],
            "style": row["style"],
            "is_borrowed": row["is_borrowed"],
            "rank": row.get("rank"),
            "owned_count": row.get("owned_count"),
            "suitable_count": row.get("suitable_count"),
        })

    current_role_counts = get_role_counts([r for r in result if not r.get("is_borrowed")])
    current_balance_comment = get_party_balance_comment(current_role_counts)

    recommend_role_rows = []
    for r in result:
        if r.get("is_borrowed"):
            continue
        recommend_role_rows.append({
            "current_role": r.get("suggest_role") or "未設定"
        })

    recommend_role_counts = get_role_counts(recommend_role_rows)
    recommend_balance_comment = get_party_balance_comment(recommend_role_counts)

    return {
        "party": result,
        "role_counts": current_role_counts,
        "balance_comment": current_balance_comment,
        "recommend_role_counts": recommend_role_counts,
        "recommend_balance_comment": recommend_balance_comment,
    }


def get_quest_list():
    data, _ = get_cached()

    quest_df = data["quest"]

    quests = []
    seen = set()

    for name in quest_df["クエスト名"].tolist():
        q = str(name).strip()
        if q and q not in seen:
            seen.add(q)
            quests.append(q)

    return {"quests": quests}
