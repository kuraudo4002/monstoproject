# -*- coding: utf-8 -*-

from collections import Counter


ATTACK_FRUITS = {
    "tribe": ["同族の加撃", "同族の加撃速", "同族の加命撃"],
    "style": ["戦型の加撃", "戦型の加撃速", "戦型の加命撃"],
    "battle_type": ["撃種の加撃", "撃種の加撃速", "撃種の加命撃"],
}

ALL_ATTACK_FRUITS = [
    "同族の加撃", "同族の加撃速", "同族の加命撃",
    "戦型の加撃", "戦型の加撃速", "戦型の加命撃",
    "撃種の加撃", "撃種の加撃速", "撃種の加命撃",
]

SUPPORT_TRIPLETS = [
    ["将命", "兵命", "速必"],
    ["将命", "兵命", "ケガ減り"],
]


def normalize_text(x):
    if x is None:
        return ""
    return str(x).strip()


def to_int_safe(x, default=0):
    try:
        if x is None:
            return default
        s = str(x).strip()
        if not s:
            return default
        return int(float(s))
    except Exception:
        return default


def is_attack_fruit(fruit):
    return normalize_text(fruit) in ALL_ATTACK_FRUITS


def is_support_fruit(fruit):
    return normalize_text(fruit) in ["将命", "兵命", "速必", "ケガ減り"]


def judge_role(fruits):
    fruits = [normalize_text(f) for f in fruits if normalize_text(f)]
    if not fruits:
        return "未設定"

    attack_count = sum(1 for f in fruits if is_attack_fruit(f))
    support_count = sum(1 for f in fruits if is_support_fruit(f))

    if support_count >= 2:
        return "サポート枠"
    if attack_count >= 2:
        return "攻撃枠"
    if support_count >= 1:
        return "サポート枠"
    if attack_count >= 1:
        return "攻撃枠"
    return "未設定"


def get_role_counts(rows):
    counts = {
        "攻撃枠": 0,
        "サポート枠": 0,
        "友情枠": 0,
        "未設定": 0,
    }

    for row in rows:
        role = normalize_text(row.get("current_role", "未設定"))
        if role not in counts:
            role = "未設定"
        counts[role] += 1

    return counts


def get_party_balance_comment(role_counts):
    attack = role_counts.get("攻撃枠", 0)
    support = role_counts.get("サポート枠", 0)

    comments = []

    if attack < 3:
        comments.append("加撃枠が不足")
    elif attack > 3:
        comments.append("加撃枠が多め")

    if support == 0:
        comments.append("サポート枠が不足")
    elif support > 1:
        comments.append("サポート枠が多め")

    if not comments:
        comments.append("基本構成はおおむね良好")

    return " / ".join(comments)


def rank_to_weight(rank_text):
    rank_text = normalize_text(rank_text).upper()
    if rank_text == "S":
        return 4
    if rank_text == "A":
        return 3
    if rank_text == "B":
        return 2
    return 1


def get_suitable_count(info):
    value = info.get("suitable_count", None)
    if value is not None:
        return to_int_safe(value, 0)

    quests = info.get("suitable_quests", [])
    if isinstance(quests, list):
        return len(quests)

    quest_count = info.get("quest_count", None)
    if quest_count is not None:
        return to_int_safe(quest_count, 0)

    return 0


def sum_owned_count(info):
    total = 0
    total += to_int_safe(info.get("main", 0))
    total += to_int_safe(info.get("sub", 0))
    total += to_int_safe(info.get("subsub", 0))
    total += to_int_safe(info.get("owned_count", 0))
    return total


def build_party_affinity_context(party_infos):
    infos = []

    for idx, raw in enumerate(party_infos):
        info = dict(raw)
        info["name"] = normalize_text(info.get("name", ""))
        info["attr"] = normalize_text(info.get("attr", ""))
        info["tribe"] = normalize_text(info.get("tribe", ""))
        info["style"] = normalize_text(info.get("style", ""))
        info["battle_type"] = normalize_text(info.get("battle_type", ""))
        info["rank"] = normalize_text(info.get("rank", ""))
        info["char_id"] = normalize_text(info.get("char_id", ""))
        info["wakuwaku"] = [normalize_text(x) for x in info.get("wakuwaku", []) if normalize_text(x)]
        info["current_role"] = normalize_text(info.get("current_role", ""))
        info["is_borrowed"] = bool(info.get("is_borrowed", False))
        info["_index"] = idx
        infos.append(info)

    return {
        "party_infos": infos,
    }


def build_attack_triplet(family_key):
    return ATTACK_FRUITS.get(family_key, ATTACK_FRUITS["tribe"])


def choose_support_triplet():
    return SUPPORT_TRIPLETS[0][:]


def get_axis_priority_tuple(info):
    return (
        rank_to_weight(info.get("rank", "")),
        -sum_owned_count(info),
        get_suitable_count(info),
    )


def is_axis_candidate(info):
    return get_suitable_count(info) >= 2


def find_axis_info(infos):
    candidates = [info for info in infos if is_axis_candidate(info)]
    if not candidates:
        candidates = infos[:]

    if not candidates:
        return None

    candidates.sort(key=get_axis_priority_tuple, reverse=True)
    return candidates[0]


def choose_support_info(infos, axis_info):
    axis_id = normalize_text(axis_info.get("char_id", "")) if axis_info else ""
    candidates = []

    for info in infos:
        cid = normalize_text(info.get("char_id", ""))
        if axis_id and cid == axis_id:
            continue
        candidates.append(info)

    if not candidates:
        return None

    # 既存サポート実が多い個体を優先、なければ後ろの個体を優先
    def score(info):
        existing_support = sum(1 for f in info.get("wakuwaku", []) if is_support_fruit(f))
        existing_attack = sum(1 for f in info.get("wakuwaku", []) if is_attack_fruit(f))
        return (
            existing_support,
            -existing_attack,
            info.get("_index", 0),
        )

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def choose_attackers(infos, support_info):
    support_id = normalize_text(support_info.get("char_id", "")) if support_info else ""
    out = []

    for info in infos:
        cid = normalize_text(info.get("char_id", ""))
        if not cid:
            continue
        if support_id and cid == support_id:
            continue
        out.append(info)

    return out


def build_party_wakuwaku_plan(context):
    infos = context.get("party_infos", [])
    plan = {}

    if not infos:
        return plan

    axis_info = find_axis_info(infos)
    support_info = choose_support_info(infos, axis_info)

    axis_id = normalize_text(axis_info.get("char_id", "")) if axis_info else ""
    support_id = normalize_text(support_info.get("char_id", "")) if support_info else ""

    if support_id:
        plan[support_id] = choose_support_triplet()

    attackers = choose_attackers(infos, support_info)
    attackers.sort(key=lambda x: x.get("_index", 0))

    ordered_attackers = []

    # 軸を先頭に
    if axis_id:
        for info in attackers:
            if normalize_text(info.get("char_id", "")) == axis_id:
                ordered_attackers.append(info)
                break

    for info in attackers:
        cid = normalize_text(info.get("char_id", ""))
        if not cid:
            continue
        if axis_id and cid == axis_id:
            continue
        ordered_attackers.append(info)

    # 攻撃3体に 9加撃を強制配布
    family_queue = ["tribe", "style", "battle_type"]

    for idx, info in enumerate(ordered_attackers):
        cid = normalize_text(info.get("char_id", ""))
        if not cid:
            continue

        if idx < len(family_queue):
            family = family_queue[idx]
        else:
            family = "tribe"

        plan[cid] = build_attack_triplet(family)

    return plan


def suggest_wakuwaku(
    char_name,
    attr,
    tribe="",
    battle_type="",
    style="",
    context=None,
    char_id="",
):
    char_id = normalize_text(char_id)

    if context is None:
        context = {"party_infos": []}

    plan = build_party_wakuwaku_plan(context)

    if char_id and char_id in plan:
        return plan[char_id]

    return build_attack_triplet("tribe")
