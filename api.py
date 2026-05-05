# -*- coding: utf-8 -*-



import json

import re
import time

from collections import defaultdict

from fastapi import FastAPI, Query

from fastapi.responses import HTMLResponse



from service import get_party_result, get_quest_list, get_cached

from wakuwaku_store import set_fruits, get as get_wakuwaku

from refine_plan_store import (

    get_priority_quests,

    set_priority_quests,

    get_frozen_plan,

    set_frozen_plan,

    clear_frozen_plan,

    get_quest_status,

    set_refine_done,

    set_cleared,

    save_clear_history,

    get_clear_history,

    get_fruit_decisions,

    set_fruit_decisions,

)



app = FastAPI()


WAKUWAKU_CACHE = {}
WAKUWAKU_CACHE_TTL = 300

def cached_get_wakuwaku(char_id):
    return get_wakuwaku(char_id)


def clear_wakuwaku_cache(char_id=None):
    return None


FRUITS = [

    "同族の加撃", "同族の加速", "同族の加命",

    "同族の加撃速", "同族の加命撃", "同族の加命速",

    "撃種の加撃", "撃種の加速", "撃種の加命",

    "撃種の加撃速", "撃種の加命撃", "撃種の加命速",

    "戦型の加撃", "戦型の加速", "戦型の加命",

    "戦型の加撃速", "戦型の加命撃", "戦型の加命速",

    "友撃", "速必", "将命", "兵命", "ケガ減り", "一撃失心", "ちび癒し", "その他",

]



ATTACK_FAMILY_MAP = {

    "same": ["同族の加撃", "同族の加撃速", "同族の加命撃"],

    "style": ["戦型の加撃", "戦型の加撃速", "戦型の加命撃"],

    "type": ["撃種の加撃", "撃種の加撃速", "撃種の加命撃"],

}



FAMILY_LABELS = {

    "same": "同族",

    "style": "戦型",

    "type": "撃種",

}



SUPPORT_CORE = ["将命", "兵命"]



DECISION_LABELS = {

    "fixed": "確定",

    "redo": "つけ直し",

    "unselected": "未厳選",

}



LABEL_TO_DECISION = {v: k for k, v in DECISION_LABELS.items()}



STATUS_LABELS = {

    "fixed": "確定",

    "redo": "つけ直し",

    "unselected": "未厳選",

    "duplicate_redo": "重複あり付け直し",

}



MODE_LABELS = {

    "attack": "火力寄り",

    "support": "サポート寄り",

    "friend": "友情寄り",

    "keep": "元推奨維持",

}



ATTACK_FRUITS = {

    "同族の加撃", "同族の加撃速", "同族の加命撃",

    "戦型の加撃", "戦型の加撃速", "戦型の加命撃",

    "撃種の加撃", "撃種の加撃速", "撃種の加命撃",

}



SUPPORT_FRUITS = {"将命", "兵命", "速必", "ケガ減り"}

FRIEND_FRUITS = {"友撃"}

DUPLICATE_ALLOWED_FRUITS = {"一撃失心", "ちび癒し"}





def normalize_text(x):

    if x is None:

        return ""

    return str(x).strip()





def normalize_decision_value(x):

    s = normalize_text(x)

    if not s:

        return "unselected"

    if s in DECISION_LABELS:

        return s

    return LABEL_TO_DECISION.get(s, "unselected")





def decision_label(x):

    return DECISION_LABELS.get(normalize_decision_value(x), "未厳選")





def status_label(x):

    return STATUS_LABELS.get(normalize_text(x), "未厳選")





def mode_label(x):

    return MODE_LABELS.get(normalize_text(x), "元推奨維持")





def parse_char_id(char_id):

    parts = str(char_id).split("||")

    if len(parts) != 4:

        return None

    return {

        "name": normalize_text(parts[0]),

        "attr": normalize_text(parts[1]),

        "acc": normalize_text(parts[2]),

        "num": normalize_text(parts[3]),

    }





def strip_account_suffix(text):

    text = normalize_text(text)

    text = re.sub(r"（(メイン|サブ|サブサブ)）$", "", text).strip()

    text = re.sub(r"\((メイン|サブ|サブサブ)\)$", "", text).strip()

    text = re.sub(r"（(メイン|サブ|サブサブ)[:：](メイン|サブ|サブサブ)）$", "", text).strip()

    text = re.sub(r"\((メイン|サブ|サブサブ)[:：](メイン|サブ|サブサブ)\)$", "", text).strip()

    return text





def strip_rank_suffix(text):

    text = normalize_text(text)

    text = re.sub(r"\[[^\]]*\]$", "", text).strip()

    return text





def extract_account_from_text(text_value):

    text_value = normalize_text(text_value)

    m = re.search(

        r"[（(](メイン|サブ|サブサブ)(?:[:：](メイン|サブ|サブサブ))?[）)]",

        text_value,

    )

    if m:

        return m.group(1)

    return ""





def extract_source_account_from_text(text_value):

    text_value = normalize_text(text_value)

    m = re.search(

        r"[（(](メイン|サブ|サブサブ)[:：](メイン|サブ|サブサブ)[）)]",

        text_value,

    )

    if m:

        return m.group(2)

    return ""





def normalize_name_for_match(text):

    text = normalize_text(text)

    text = text.replace("（", "(").replace("）", ")")

    text = strip_rank_suffix(text)

    text = strip_account_suffix(text)

    text = re.sub(r"\(.*?\)", "", text).strip()

    return text





def build_title_name(party_row, char_id):

    text_value = normalize_text(party_row.get("text", ""))

    text_value = strip_rank_suffix(text_value)

    text_value = strip_account_suffix(text_value)



    if text_value:

        return text_value



    parsed = parse_char_id(char_id)

    if parsed and parsed["name"]:

        return parsed["name"]



    return ""





def build_account_name(party_row, char_id):

    parsed = parse_char_id(char_id)

    original_acc = parsed["acc"] if parsed else ""



    text_value = normalize_text(party_row.get("text", ""))

    assigned_acc = extract_account_from_text(text_value)

    source_acc = extract_source_account_from_text(text_value)



    is_borrowed = bool(party_row.get("is_borrowed"))



    if is_borrowed:

        left = assigned_acc or original_acc

        right = source_acc or original_acc

        if left and right:

            return f"{left}({right})"

        return left or right or original_acc



    return assigned_acc or original_acc





def fruit_family(fruit):

    fruit = normalize_text(fruit)

    if fruit.startswith("同族"):

        return "same"

    if fruit.startswith("戦型"):

        return "style"

    if fruit.startswith("撃種"):

        return "type"

    if fruit in SUPPORT_FRUITS:

        return "support"

    if fruit in FRIEND_FRUITS:

        return "friend"

    return "other"





def is_attack_fruit(fruit):

    return normalize_text(fruit) in ATTACK_FRUITS





def is_support_fruit(fruit):

    return normalize_text(fruit) in SUPPORT_FRUITS





def is_friend_fruit(fruit):

    return normalize_text(fruit) in FRIEND_FRUITS





def dedupe_keep_order(items):

    out = []

    seen = set()

    for item in items:

        item = normalize_text(item)

        if not item:

            continue

        if item in seen:

            continue

        seen.add(item)

        out.append(item)

    return out





def count_nonempty(items):

    return sum(1 for x in items if normalize_text(x))





def count_fixed_decisions(decisions):

    return sum(1 for d in decisions if normalize_decision_value(d) == "fixed")





def infer_role_from_fruits(fruits):

    fruits = [normalize_text(x) for x in fruits if normalize_text(x)]

    attack_count = sum(1 for f in fruits if is_attack_fruit(f))

    support_count = sum(1 for f in fruits if is_support_fruit(f))

    friend_count = sum(1 for f in fruits if is_friend_fruit(f))



    if support_count >= 2:

        return "support"

    if attack_count >= 2:

        return "attack"

    if friend_count >= 1 and support_count == 0 and attack_count == 0:

        return "friend"

    if support_count >= 1 and attack_count == 0:

        return "support"

    return "attack"





def infer_status_from_decisions(suggest, decisions):

    visible_suggest = [normalize_text(x) for x in suggest if normalize_text(x)]

    decisions = [normalize_decision_value(x) for x in decisions]



    if not visible_suggest:

        return "unselected", 0



    if any(d == "redo" for d in decisions):

        fixed_count = sum(1 for d in decisions if d == "fixed")

        return "redo", max(0, len(visible_suggest) - fixed_count)



    fixed_count = sum(1 for d in decisions if d == "fixed")



    if fixed_count >= len(visible_suggest):

        return "fixed", 0



    if fixed_count > 0:

        return "unselected", max(0, len(visible_suggest) - fixed_count)



    return "unselected", len(visible_suggest)





def reorder_current_by_suggest(current_wakuwaku, suggest_wakuwaku):

    current = [normalize_text(x) for x in current_wakuwaku if normalize_text(x)]

    suggest = [normalize_text(x) for x in suggest_wakuwaku if normalize_text(x)]



    matched = []

    remaining_current = current[:]



    for s in suggest:

        if s in remaining_current:

            matched.append(s)

            remaining_current.remove(s)



    ordered = matched + remaining_current

    ordered = ordered[:3]

    while len(ordered) < 3:

        ordered.append("")

    return ordered





def align_decisions_to_display(display_current, stored_decisions):

    result = []

    remaining = list(stored_decisions or [])



    for fruit in display_current:

        fruit = normalize_text(fruit)

        matched = None



        for i, item in enumerate(remaining):

            if normalize_text(item.get("fruit", "")) == fruit:

                matched = remaining.pop(i)

                break



        if matched is None:

            matched = {"fruit": fruit, "decision": "unselected"}



        decision_value = normalize_decision_value(matched.get("decision", "unselected"))



        result.append({

            "fruit": fruit,

            "decision": decision_value,

        })



    while len(result) < 3:

        result.append({"fruit": "", "decision": "unselected"})



    return result[:3]





def pick_attack_family_from_locked(locked):

    scores = {"same": 0, "style": 0, "type": 0}



    for fruit in locked:

        fam = fruit_family(fruit)

        if fam in scores:

            scores[fam] += 1



    best_family = None

    best_score = -1



    for fam in ["same", "style", "type"]:

        if scores[fam] > best_score:

            best_score = scores[fam]

            best_family = fam



    return best_family if best_score > 0 else None





def pick_attack_family_from_original(original_suggest):

    scores = {"same": 0, "style": 0, "type": 0}



    for fruit in original_suggest:

        fam = fruit_family(fruit)

        if fam in scores:

            scores[fam] += 1



    best_family = None

    best_score = -1



    for fam in ["same", "style", "type"]:

        if scores[fam] > best_score:

            best_score = scores[fam]

            best_family = fam



    return best_family if best_score > 0 else None





def choose_mode(locked, original_suggest, quest_count):

    locked = [normalize_text(x) for x in locked if normalize_text(x)]

    original_suggest = [normalize_text(x) for x in original_suggest if normalize_text(x)]



    locked_attack = sum(1 for f in locked if is_attack_fruit(f))

    locked_support = sum(1 for f in locked if is_support_fruit(f))

    locked_friend = sum(1 for f in locked if is_friend_fruit(f))



    original_attack = sum(1 for f in original_suggest if is_attack_fruit(f))

    original_support = sum(1 for f in original_suggest if is_support_fruit(f))

    original_friend = sum(1 for f in original_suggest if is_friend_fruit(f))



    if locked_support >= 2:

        return "support"

    if locked_attack >= 2:

        return "attack"

    if locked_friend >= 1 and locked_support >= 1:

        return "friend"

    if locked_friend >= 1:

        return "friend"

    if locked_support >= 1 and locked_attack == 0:

        return "support"

    if locked_attack >= 1:

        return "attack"



    if quest_count >= 2:

        if original_attack >= 2:

            return "attack"

        if original_support >= 2:

            return "support"

        if original_friend >= 1:

            return "friend"



    if original_attack >= original_support and original_attack >= original_friend:

        return "attack"

    if original_support >= original_attack and original_support >= original_friend:

        return "support"

    if original_friend >= 1:

        return "friend"



    return "keep"





def build_attack_recommendation(preferred_family, original_suggest, quest_count):
    base = []

    if preferred_family in ATTACK_FAMILY_MAP:
        base.extend(ATTACK_FAMILY_MAP[preferred_family])

    for fruit in original_suggest:
        if is_attack_fruit(fruit) and fruit not in base:
            base.append(fruit)

    for fam in ["same", "type", "style"]:
        for fruit in ATTACK_FAMILY_MAP[fam]:
            if fruit not in base:
                base.append(fruit)

    base = dedupe_keep_order(base)[:3]
    while len(base) < 3:
        base.append("")
    return base


def build_support_recommendation(locked, quest_count):
    base = []
    base.extend(locked)

    for fruit in ["\u5c06\u547d", "\u5175\u547d", "\u30b1\u30ac\u6e1b\u308a", "\u901f\u5fc5", "\u53cb\u6483"]:
        if fruit not in base:
            base.append(fruit)

    base = dedupe_keep_order(base)[:3]
    while len(base) < 3:
        base.append("")
    return base


def build_friend_recommendation(locked, quest_count):

    base = ["友撃", "将命", "兵命"]



    if "速必" in locked:

        base = ["友撃", "速必", "将命"]



    base = dedupe_keep_order(base)[:3]

    while len(base) < 3:

        base.append("")

    return base





def extend_with_locked_first(locked, base_recommendation):

    out = dedupe_keep_order(locked)



    for fruit in base_recommendation:

        if fruit not in out:

            out.append(fruit)

        if len(out) >= 3:

            break



    out = out[:3]

    while len(out) < 3:

        out.append("")

    return out





def apply_decisions(display_current_wakuwaku, original_suggest, decisions, quest_count=1, forced_mode=None):

    current_wakuwaku = [normalize_text(x) for x in display_current_wakuwaku if normalize_text(x)]

    original_suggest = [normalize_text(x) for x in original_suggest if normalize_text(x)]



    locked = []

    cleaned_decisions = []



    for i, fruit in enumerate(current_wakuwaku):

        decision = "unselected"

        if i < len(decisions):

            decision = normalize_decision_value(decisions[i].get("decision", "unselected"))



        cleaned_decisions.append(decision)



        if decision == "fixed" and fruit not in locked:

            locked.append(fruit)



    mode = forced_mode or choose_mode(locked, original_suggest, quest_count)



    preferred_attack_family = pick_attack_family_from_locked(locked)

    if preferred_attack_family is None:

        preferred_attack_family = pick_attack_family_from_original(original_suggest)



    if mode == "support":

        base = build_support_recommendation(locked, quest_count)

    elif mode == "attack":

        base = build_attack_recommendation(preferred_attack_family, original_suggest, quest_count)

    elif mode == "friend":

        base = build_friend_recommendation(locked, quest_count)

    else:

        base = dedupe_keep_order(original_suggest)[:3]

        while len(base) < 3:

            base.append("")



    recomputed = extend_with_locked_first(locked, base)



    if not [x for x in recomputed if normalize_text(x)]:

        fallback = []

        fallback.extend(locked)

        fallback.extend([

            "同族の加撃",

            "同族の加撃速",

            "同族の加命撃",

        ])

        recomputed = dedupe_keep_order(fallback)[:3]

        while len(recomputed) < 3:

            recomputed.append("")



    status_text, remain_count = infer_status_from_decisions(

        recomputed,

        cleaned_decisions,

    )



    has_fixed = any(d == "fixed" for d in cleaned_decisions)

    has_redo = any(d == "redo" for d in cleaned_decisions)

    fixed_support_count = sum(

        1

        for fruit, decision in zip(current_wakuwaku, cleaned_decisions)

        if decision == "fixed" and is_support_fruit(fruit)

    )



    return {

        "locked_fruits": locked,

        "recomputed_suggest": recomputed,

        "status": status_text,

        "status_label": status_label(status_text),

        "remain_count": remain_count,

        "mode": mode,

        "mode_label": mode_label(mode),

        "effective_role": infer_role_from_fruits(recomputed),

        "has_fixed": has_fixed,

        "has_redo": has_redo,

        "fixed_support_count": fixed_support_count,

        "cleaned_decisions": cleaned_decisions,

        "current_count": count_nonempty(current_wakuwaku),

    }





def fruit_duplicate_key(fruit, meta):

    fruit = normalize_text(fruit)

    if not fruit:

        return None

    if fruit in DUPLICATE_ALLOWED_FRUITS:

        return None



    fam = fruit_family(fruit)



    if fam == "same":

        target = normalize_text(meta.get("tribe", ""))

        if not target:

            return None

        return (fruit, fam, target)



    if fam == "style":

        target = normalize_text(meta.get("style", ""))

        if not target:

            return None

        return (fruit, fam, target)



    if fam == "type":

        target = normalize_text(meta.get("battle_type", ""))

        if not target:

            return None

        return (fruit, fam, target)



    return (fruit, fam, "__global__")





def get_all_suitable_quests_for_char(char_name, priority_quests):

    try:

        data, _ = get_cached()

    except Exception:

        return []



    qx = data.get("quest_expanded")

    if qx is None or getattr(qx, "empty", True):

        return []



    target_name = normalize_name_for_match(char_name)

    if not target_name:

        return []



    required_cols = ["クエスト名", "ランク", "キャラ名", "ベース名"]

    for col in required_cols:

        if col not in qx.columns:

            return []



    found = []

    seen = set()



    for _, row in qx.iterrows():

        quest_name = normalize_text(row.get("クエスト名", ""))

        rank = normalize_text(row.get("ランク", ""))

        char_full = normalize_text(row.get("キャラ名", ""))

        base_name = normalize_text(row.get("ベース名", ""))



        if not quest_name:

            continue



        cand1 = normalize_name_for_match(char_full)

        cand2 = normalize_name_for_match(base_name)



        if target_name not in [cand1, cand2]:

            continue



        key = (quest_name, rank)

        if key in seen:

            continue

        seen.add(key)



        found.append({

            "quest": quest_name,

            "rank": rank,

            "display": f"{quest_name}({rank})" if rank else quest_name,

        })



    priority_first = []

    others = []



    for item in found:

        if item["quest"] in priority_quests:

            priority_first.append(item)

        else:

            others.append(item)



    priority_first.sort(key=lambda x: priority_quests.index(x["quest"]) if x["quest"] in priority_quests else 999)

    others.sort(key=lambda x: (x["quest"], x["rank"]))



    return priority_first + others





def build_frozen_plan():

    quests = get_priority_quests()

    merged = {}



    for quest in quests:

        party_result = get_party_result(quest)

        for row in party_result.get("party", []):

            char_id = normalize_text(row.get("char_id", ""))

            if not char_id:

                continue



            parsed = parse_char_id(char_id)

            char_name = parsed["name"] if parsed else ""

            account_name = build_account_name(row, char_id)

            title_name = build_title_name(row, char_id)



            if char_id not in merged:

                merged[char_id] = {

                    "char_id": char_id,

                    "title_name": title_name,

                    "pure_name": char_name or title_name,

                    "account": account_name,

                    "quests": [quest],

                    "suggest_wakuwaku": row.get("suggest", []),

                }

            else:

                if quest not in merged[char_id]["quests"]:

                    merged[char_id]["quests"].append(quest)



    return list(merged.values())





def sort_priority_rows(rows, priority_quests):

    quest_order_map = {q: i for i, q in enumerate(priority_quests)}



    def row_key(row):

        first_priority = min([quest_order_map.get(q, 999) for q in row.get("quests", [])]) if row.get("quests") else 999

        multi_quest_score = len(row.get("quests", []))

        remain_count = int(row.get("remain_count", 0))

        priority_overlap = sum(1 for q in row.get("quests", []) if q in priority_quests)

        duplicate_penalty = 0 if row.get("has_duplicate") else 1



        return (

            duplicate_penalty,

            first_priority,

            -priority_overlap,

            -multi_quest_score,

            -remain_count,

            row.get("title_name", ""),

        )



    return sorted(rows, key=row_key)





def collect_party_meta_for_priority_quests(priority_quests):

    meta_by_quest = {}



    for quest in priority_quests:

        party_result = get_party_result(quest)

        members = []



        for row in party_result.get("party", []):

            char_id = normalize_text(row.get("char_id", ""))

            if not char_id:

                continue

            if "該当なし" in normalize_text(row.get("text", "")):

                continue



            members.append({

                "char_id": char_id,

                "text": normalize_text(row.get("text", "")),

                "tribe": normalize_text(row.get("tribe", "")),

                "style": normalize_text(row.get("style", "")),

                "battle_type": normalize_text(row.get("battle_type", "")),

            })



        meta_by_quest[quest] = members



    return meta_by_quest





def account_keep_score(row):
    parsed = parse_char_id(row.get("char_id", ""))
    acc = ""

    if parsed:
        acc = parsed.get("acc", "")

    account_text = normalize_text(row.get("account", "")) or acc

    if "\u30e1\u30a4\u30f3" in account_text:
        return 3
    if "\u30b5\u30d6\u30b5\u30d6" in account_text:
        return 1
    if "\u30b5\u30d6" in account_text:
        return 2
    return 0


def row_keep_score(row):

    applied = row["applied"]

    return (

        count_fixed_decisions(applied["cleaned_decisions"]),

        applied["current_count"],

        account_keep_score(row),

        row.get("title_name", ""),

    )







def rebalance_support_overlap(rows_by_char_id, party_meta_by_quest):

    for quest, members in party_meta_by_quest.items():

        party_rows = []



        for member in members:

            row = rows_by_char_id.get(member["char_id"])

            if row:

                party_rows.append(row)



        if not party_rows:

            continue




        fixed_support_rows = [

            row for row in party_rows

            if row["applied"].get("fixed_support_count", 0) > 0

        ]



        if fixed_support_rows:

            fixed_support_rows.sort(key=row_keep_score, reverse=True)

            support_keeper = fixed_support_rows[0]

        else:


            support_candidate_rows = [

                row for row in party_rows

                if row["applied"].get("effective_role") == "support"

            ]



            if not support_candidate_rows:

                continue



            support_candidate_rows.sort(key=row_keep_score, reverse=True)

            support_keeper = support_candidate_rows[0]




        for row in party_rows:

            if row["char_id"] == support_keeper["char_id"]:

                continue





            if row["applied"].get("fixed_support_count", 0) > 0:

                continue



            row["applied"] = apply_decisions(

                display_current_wakuwaku=row["display_current"],

                original_suggest=row["original_suggest"],

                decisions=row["aligned_decisions"],

                quest_count=len(row.get("quests", [])),

                forced_mode="attack",

            )







def build_candidate_fruits_for_row(row):
    applied = row["applied"]
    locked = applied.get("locked_fruits", [])
    original_suggest = row.get("original_suggest", [])
    mode = applied.get("mode", "keep")

    candidates = []
    candidates.extend(locked)

    if mode == "support":
        for fruit in ["\u5c06\u547d", "\u5175\u547d", "\u30b1\u30ac\u6e1b\u308a", "\u901f\u5fc5", "\u53cb\u6483"]:
            if fruit not in candidates:
                candidates.append(fruit)
        return dedupe_keep_order(candidates)

    if mode == "friend":
        for fruit in ["\u53cb\u6483", "\u901f\u5fc5", "\u5c06\u547d", "\u5175\u547d", "\u30b1\u30ac\u6e1b\u308a"]:
            if fruit not in candidates:
                candidates.append(fruit)
        return dedupe_keep_order(candidates)

    for fruit in original_suggest:
        if is_attack_fruit(fruit):
            candidates.append(fruit)

    for fam in ["same", "type", "style"]:
        candidates.extend(ATTACK_FAMILY_MAP[fam])

    return dedupe_keep_order(candidates)


def rebuild_suggest_avoiding_duplicates(row, member, occupied_keys):

    applied = row["applied"]

    current = row["display_current"]

    decisions = applied.get("cleaned_decisions", [])



    fixed_fruits = []

    fixed_conflict = False



    for fruit, decision in zip(current, decisions):

        fruit = normalize_text(fruit)

        decision = normalize_decision_value(decision)



        if decision != "fixed" or not fruit:

            continue



        fixed_fruits.append(fruit)



        key = fruit_duplicate_key(fruit, member)

        if key is not None and key in occupied_keys:

            fixed_conflict = True



    result = []

    for fruit in fixed_fruits:

        if fruit not in result:

            result.append(fruit)



    candidates = build_candidate_fruits_for_row(row)



    for fruit in candidates:

        fruit = normalize_text(fruit)

        if not fruit:

            continue

        if fruit in result:

            continue



        key = fruit_duplicate_key(fruit, member)

        if key is not None and key in occupied_keys:

            continue



        result.append(fruit)



        if len(result) >= 3:

            break



    while len(result) < 3:

        result.append("")



    return result[:3], fixed_conflict






def role_score_for_row(row):
    current = row.get("display_current", [])
    decisions = row.get("applied", {}).get("cleaned_decisions", [])

    fixed_attack = 0
    fixed_support = 0
    fixed_friend = 0
    current_attack = 0
    current_support = 0
    current_friend = 0

    for fruit, decision in zip(current, decisions):
        fruit = normalize_text(fruit)
        decision = normalize_decision_value(decision)

        if is_attack_fruit(fruit):
            current_attack += 1
            if decision == "fixed":
                fixed_attack += 1

        if is_support_fruit(fruit):
            current_support += 1
            if decision == "fixed":
                fixed_support += 1

        if is_friend_fruit(fruit):
            current_friend += 1
            if decision == "fixed":
                fixed_friend += 1

    return {
        "attack": fixed_attack * 10 + current_attack,
        "support": fixed_support * 10 + fixed_friend * 8 + current_support + current_friend,
        "fixed_attack": fixed_attack,
        "fixed_support": fixed_support + fixed_friend,
    }


def choose_support_row_for_party(party_rows):
    scored = []
    for row in party_rows:
        s = role_score_for_row(row)
        scored.append((row, s))

    scored.sort(
        key=lambda pair: (
            pair[1]["support"],
            -pair[1]["fixed_attack"],
            -pair[1]["attack"],
            account_keep_score(pair[0]),
            pair[0].get("title_name", ""),
        ),
        reverse=True,
    )

    return scored[0][0] if scored else None


def optimize_party_roles(rows_by_char_id, party_meta_by_quest):
    for quest, members in party_meta_by_quest.items():
        party_rows = []

        for member in members:
            row = rows_by_char_id.get(member["char_id"])
            if row:
                party_rows.append(row)

        if not party_rows:
            continue

        support_row = choose_support_row_for_party(party_rows)
        if support_row is None:
            continue

        for row in party_rows:
            forced_mode = "support" if row["char_id"] == support_row["char_id"] else "attack"

            row["applied"] = apply_decisions(
                display_current_wakuwaku=row["display_current"],
                original_suggest=row["original_suggest"],
                decisions=row["aligned_decisions"],
                quest_count=len(row.get("quests", [])),
                forced_mode=forced_mode,
            )

def resolve_duplicate_conflicts(rows_by_char_id, party_meta_by_quest):

    duplicate_rows = defaultdict(set)

    keeper_rows = set()



    for quest, members in party_meta_by_quest.items():

        party_rows = []



        for member in members:

            row = rows_by_char_id.get(member["char_id"])

            if not row:

                continue

            party_rows.append((member, row))



        if not party_rows:

            continue





        party_rows.sort(key=lambda pair: row_keep_score(pair[1]), reverse=True)



        occupied_keys = {}



        for member, row in party_rows:

            new_suggest, fixed_conflict = rebuild_suggest_avoiding_duplicates(

                row,

                member,

                occupied_keys,

            )



            row["applied"]["recomputed_suggest"] = new_suggest

            row["applied"]["effective_role"] = infer_role_from_fruits(new_suggest)



            if infer_role_from_fruits(new_suggest) == "attack":

                row["applied"]["mode"] = "attack"

                row["applied"]["mode_label"] = mode_label("attack")



            if fixed_conflict:

                duplicate_rows[row["char_id"]].add(quest)


                continue



            for fruit in new_suggest:

                fruit = normalize_text(fruit)

                if not fruit:

                    continue



                key = fruit_duplicate_key(fruit, member)

                if key is None:

                    continue



                if key not in occupied_keys:

                    occupied_keys[key] = row["char_id"]

                    keeper_rows.add(row["char_id"])

                elif occupied_keys[key] != row["char_id"]:


                    duplicate_rows[row["char_id"]].add(quest)



    return duplicate_rows, keeper_rows






def optimizer_is_attack_fruit(fruit):
    fruit = normalize_text(fruit)
    return fruit.startswith("\u540c\u65cf") or fruit.startswith("\u6226\u578b") or fruit.startswith("\u6483\u7a2e")


def optimizer_affected_count(fruit, members):
    from collections import Counter

    fruit = normalize_text(fruit)

    if fruit.startswith("\u540c\u65cf"):
        values = [normalize_text(m.get("tribe", "")) for m in members]
    elif fruit.startswith("\u6226\u578b"):
        values = [normalize_text(m.get("style", "")) for m in members]
    elif fruit.startswith("\u6483\u7a2e"):
        values = [normalize_text(m.get("battle_type", "")) for m in members]
    else:
        return 0

    values = [v for v in values if v]
    if not values:
        return 0

    return max(Counter(values).values())


def optimizer_score(combo, members):
    seen = set()
    duplicate_count = 0
    score = 0
    attack_count = 0
    support_count = 0

    for fruits, member in zip(combo, members):
        tribe = normalize_text(member.get("tribe", ""))
        style = normalize_text(member.get("style", ""))
        btype = normalize_text(member.get("battle_type", ""))

        for fruit in fruits:
            fruit = normalize_text(fruit)
            if not fruit:
                continue

            # 🔥 ここが重要：効果対象込みでキーを作る
            if fruit.startswith("同族"):
                key = (fruit, "same", tribe)
            elif fruit.startswith("戦型"):
                key = (fruit, "style", style)
            elif fruit.startswith("撃種"):
                key = (fruit, "type", btype)
            else:
                key = (fruit, "other")

            if key in seen:
                duplicate_count += 1
                continue

            seen.add(key)

            if optimizer_is_attack_fruit(fruit):
                score += optimizer_affected_count(fruit, members)
                attack_count += 1
            else:
                support_count += 1

    score -= duplicate_count * 100
    score += attack_count * 0.01
    score += support_count * 0.001
    return score



def optimizer_build_candidates():
    return [
        ("\u540c\u65cf\u306e\u52a0\u6483", "\u540c\u65cf\u306e\u52a0\u6483\u901f", "\u540c\u65cf\u306e\u52a0\u547d\u6483"),
        ("\u6483\u7a2e\u306e\u52a0\u6483", "\u6483\u7a2e\u306e\u52a0\u6483\u901f", "\u6483\u7a2e\u306e\u52a0\u547d\u6483"),
        ("\u6226\u578b\u306e\u52a0\u6483", "\u6226\u578b\u306e\u52a0\u6483\u901f", "\u6226\u578b\u306e\u52a0\u547d\u6483"),

        ("\u540c\u65cf\u306e\u52a0\u6483", "\u6483\u7a2e\u306e\u52a0\u6483", "\u6226\u578b\u306e\u52a0\u6483"),
        ("\u540c\u65cf\u306e\u52a0\u6483\u901f", "\u6483\u7a2e\u306e\u52a0\u6483\u901f", "\u6226\u578b\u306e\u52a0\u6483\u901f"),
        ("\u540c\u65cf\u306e\u52a0\u547d\u6483", "\u6483\u7a2e\u306e\u52a0\u547d\u6483", "\u6226\u578b\u306e\u52a0\u547d\u6483"),

        ("\u5c06\u547d", "\u5175\u547d", "\u901f\u5fc5"),
        ("\u5c06\u547d", "\u5175\u547d", "\u30b1\u30ac\u6e1b\u308a"),
        ("\u53cb\u6483", "\u901f\u5fc5", "\u30b1\u30ac\u6e1b\u308a"),
    ]


def optimizer_best_plan(members):
    import itertools

    if not members:
        return [], 0

    candidates = [optimizer_build_candidates() for _ in members]
    best = None
    best_score = -999999

    for combo in itertools.product(*candidates):
        current_score = optimizer_score(combo, members)
        if current_score > best_score:
            best_score = current_score
            best = combo

    return best or [], best_score


def merge_locked_with_optimizer_plan(display_current, aligned_decisions, planned_fruits):
    locked = []

    for fruit, decision_row in zip(display_current, aligned_decisions):
        fruit = normalize_text(fruit)
        decision = normalize_decision_value(decision_row.get("decision", ""))

        if decision == "fixed" and fruit and fruit not in locked:
            locked.append(fruit)

    result = []
    for fruit in locked:
        if fruit not in result:
            result.append(fruit)

    for fruit in planned_fruits:
        fruit = normalize_text(fruit)
        if fruit and fruit not in result:
            result.append(fruit)
        if len(result) >= 3:
            break

    fallback = [
        "\u540c\u65cf\u306e\u52a0\u6483", "\u540c\u65cf\u306e\u52a0\u6483\u901f", "\u540c\u65cf\u306e\u52a0\u547d\u6483",
        "\u6483\u7a2e\u306e\u52a0\u6483", "\u6483\u7a2e\u306e\u52a0\u6483\u901f", "\u6483\u7a2e\u306e\u52a0\u547d\u6483",
        "\u6226\u578b\u306e\u52a0\u6483", "\u6226\u578b\u306e\u52a0\u6483\u901f", "\u6226\u578b\u306e\u52a0\u547d\u6483",
        "\u5c06\u547d", "\u5175\u547d", "\u901f\u5fc5", "\u30b1\u30ac\u6e1b\u308a", "\u53cb\u6483",
    ]

    for fruit in fallback:
        if len(result) >= 3:
            break
        if fruit not in result:
            result.append(fruit)

    return result[:3]


def optimizer_mode_from_suggest(suggest):
    attack_count = sum(1 for f in suggest if optimizer_is_attack_fruit(f))
    support_count = sum(1 for f in suggest if is_support_fruit(f) or is_friend_fruit(f))

    if attack_count >= 2:
        return "attack"
    if support_count >= 2:
        return "support"
    return "keep"



def build_plan_view_rows():
    frozen = get_frozen_plan()
    quests = get_priority_quests()
    rows = []

    for row in frozen:
        char_id = row["char_id"]
        raw_current_wakuwaku = cached_get_wakuwaku(char_id)
        original_suggest = [normalize_text(x) for x in row.get("suggest_wakuwaku", []) if normalize_text(x)]

        display_current = reorder_current_by_suggest(raw_current_wakuwaku, original_suggest)
        stored_decisions = get_fruit_decisions(char_id)
        aligned_decisions = align_decisions_to_display(display_current, stored_decisions)

        suitable_quests = get_all_suitable_quests_for_char(
            char_name=row.get("pure_name", "") or row.get("title_name", ""),
            priority_quests=quests,
        )

        if not suitable_quests:
            suitable_quests = [{"quest": q, "rank": "", "display": q} for q in row.get("quests", [])]

        rows.append({
            "char_id": char_id,
            "title_name": row.get("title_name", ""),
            "account": row.get("account", ""),
            "suitable_quests": suitable_quests,
            "display_current": display_current,
            "original_suggest": original_suggest,
            "aligned_decisions": aligned_decisions,
            "quests": row.get("quests", []),
        })

    rows_by_char_id = {row["char_id"]: row for row in rows}
    party_meta_by_quest = collect_party_meta_for_priority_quests(quests)

    optimizer_suggest_by_char_id = {}

    for quest, members in party_meta_by_quest.items():
        clean_members = []
        clean_char_ids = []

        for member in members:
            char_id = normalize_text(member.get("char_id", ""))
            if not char_id:
                continue

            clean_members.append({
                "tribe": normalize_text(member.get("tribe", "")),
                "style": normalize_text(member.get("style", "")),
                "battle_type": normalize_text(member.get("battle_type", "")),
            })
            clean_char_ids.append(char_id)

        combo, _score = optimizer_best_plan(clean_members)

        for i, fruits in enumerate(combo):
            if i >= len(clean_char_ids):
                continue
            optimizer_suggest_by_char_id[clean_char_ids[i]] = list(fruits)

    final_rows = []

    for row in rows:
        planned = optimizer_suggest_by_char_id.get(row["char_id"], row["original_suggest"])
        recomputed = merge_locked_with_optimizer_plan(
            row["display_current"],
            row["aligned_decisions"],
            planned,
        )

        decision_values = [d.get("decision", "unselected") for d in row["aligned_decisions"]]
        status, remain_count = infer_status_from_decisions(recomputed, decision_values)

        locked_fruits = []
        for fruit, decision_row in zip(row["display_current"], row["aligned_decisions"]):
            fruit = normalize_text(fruit)
            decision = normalize_decision_value(decision_row.get("decision", ""))
            if decision == "fixed" and fruit:
                locked_fruits.append(fruit)

        mode = optimizer_mode_from_suggest(recomputed)

        display_rows = []
        for i in range(3):
            current_fruit = row["display_current"][i] if i < len(row["display_current"]) else ""
            suggest_fruit = recomputed[i] if i < len(recomputed) else ""
            decision_value = row["aligned_decisions"][i]["decision"] if i < len(row["aligned_decisions"]) else "unselected"

            display_rows.append({
                "slot_no": i + 1,
                "current": current_fruit,
                "suggest": suggest_fruit,
                "decision": decision_value,
            })

        final_rows.append({
            "char_id": row["char_id"],
            "title_name": row.get("title_name", ""),
            "account": row.get("account", ""),
            "suitable_quests": row.get("suitable_quests", []),
            "locked_fruits": locked_fruits,
            "status": status,
            "status_label": status_label(status),
            "remain_count": remain_count,
            "display_rows": display_rows,
            "mode": mode,
            "mode_label": mode_label(mode),
            "quests": row.get("quests", []),
            "has_fixed": status == "fixed",
            "has_duplicate": False,
            "duplicate_quests": [],
        })

    return sort_priority_rows(final_rows, quests)


@app.get("/", response_class=HTMLResponse)

def home():

    fruits_js = json.dumps(FRUITS, ensure_ascii=True)



    html = """

<!DOCTYPE html>

<html lang="ja">

<head>

<meta charset="UTF-8">

<title>\u30e2\u30f3\u30b9\u30c8\u7de8\u6210\u30c4\u30fc\u30eb</title>

<style>

body {

  font-family: Arial, sans-serif;

  padding: 24px;

  background: #f5f5f5;

}

h1, h2 {

  margin-top: 18px;

  margin-bottom: 10px;

}

select {

  padding: 8px;

  font-size: 16px;

  width: 260px;

  margin-right: 8px;

  margin-bottom: 8px;

}

button {

  padding: 6px 10px;

  margin-left: 6px;

  cursor: pointer;

}

.block {

  background: white;

  border-radius: 10px;

  padding: 12px;

  margin-top: 18px;

  max-width: 980px;

}

.row-card {

  background: #fafafa;

  border: 1px solid #ddd;

  border-radius: 8px;

  padding: 12px;

  margin-top: 12px;

}

.row-card-fixed {

  background: #f2fbf2;

  border-color: #8fd19e;

}

.row-card-unselected {

  background: #fff5f5;

  border-color: #f1aeb5;

}

.row-card-duplicate {

  background: #fff5f5;

  border-color: #f1aeb5;

}

.char-title {

  font-size: 22px;

  font-weight: bold;

  margin-bottom: 6px;

}

.account-line {

  margin-top: 4px;

  font-size: 14px;

}

.quest-line {

  margin-top: 8px;

  font-size: 14px;

  line-height: 1.8;

}

.tag {

  background: #eee;

  padding: 3px 6px;

  margin: 2px;

  display: inline-block;

  border-radius: 5px;

  font-size: 13px;

}

.priority-quest-tag {

  background: #ffd8a8;

}

.normal-quest-tag {

  background: #ececec;

}

.line {

  margin-top: 6px;

}

.small {

  font-size: 12px;

  color: #666;

}

.warn {

  color: #c1121f;

  font-weight: bold;

}

.state {

  display: inline-block;

  padding: 3px 8px;

  border-radius: 6px;

  background: #ececec;

  margin-right: 8px;

}

.state-mitei {

  background: #ececec;

}

.state-tochu {

  background: #fff1bf;

}

.state-kakutei {

  background: #d3f9d8;

}

.info-box {

  margin-top: 10px;

  padding: 10px 12px;

  background: #f2f7ff;

  border: 1px solid #cfe0ff;

  border-radius: 8px;

}

.info-title {

  font-weight: bold;

  margin-bottom: 4px;

}

.grid-head,

.grid-row {

  display: grid;

  grid-template-columns: 50px minmax(0, 1.35fr) minmax(0, 0.72fr) minmax(0, 0.93fr);

  gap: 6px;

  align-items: center;

}

.grid-head {

  margin-top: 12px;

  padding: 8px 10px;

  background: #efefef;

  border-radius: 8px;

  font-weight: bold;

}

.grid-row {

  margin-top: 8px;

  padding: 10px;

  background: #fff;

  border: 1px solid #e5e5e5;

  border-radius: 8px;

}

.col-center {

  text-align: center;

}

.inline-select {

  width: 100%;

  min-width: 0;

  margin: 0;

}

.decision-select {

  width: 100%;

  min-width: 0;

  margin: 0;

}

.suggest-chip {

  display: inline-block;

  padding: 4px 8px;

  border-radius: 6px;

  font-size: 12px;

  background: #dff3ff;

  word-break: break-word;

}

.top-buttons button {

  margin-top: 8px;

}

.priority-summary-box {

  margin-top: 10px;

  padding: 10px 12px;

  background: #fff8e6;

  border: 1px solid #ffe2a8;

  border-radius: 8px;

}

.priority-summary-title {

  font-weight: bold;

  margin-bottom: 6px;

}

.empty-message {

  margin-top: 10px;

  padding: 10px 12px;

  background: #fafafa;

  border: 1px solid #e5e5e5;

  border-radius: 8px;

}

</style>

</head>

<body>



<h1>\u30e2\u30f3\u30b9\u30c8\u7de8\u6210\u30c4\u30fc\u30eb</h1>



<div class="block">

  <h2>\u308f\u304f\u308f\u304f\u53b3\u9078</h2>



  <div class="top-buttons">

    <select id="priority1"></select><br>

    <select id="priority2"></select><br>

    <select id="priority3"></select><br>



    <button onclick="savePriorityQuests()">\u512a\u5148\u30af\u30a8\u30b9\u30c8\u3092\u4fdd\u5b58</button>

    <button onclick="freezePlan()">\u53b3\u9078\u5bfe\u8c61\u9078\u51fa</button>

    <button onclick="recalcPlan()">\u518d\u9078\u51fa</button>

    <button onclick="clearPlan()">\u9078\u51fa\u89e3\u9664</button>

  </div>



  <div id="planArea"></div>

</div>



<script>

const FRUITS = __FRUITS_JS__;



async function loadQuestOptions() {

  const res = await fetch("/quests");

  const data = await res.json();



  ["priority1", "priority2", "priority3"].forEach(id => {

    const select = document.getElementById(id);

    select.innerHTML = "";



    const first = document.createElement("option");

    first.value = "";

    first.textContent = "\u30af\u30a8\u30b9\u30c8\u3092\u9078\u629e";

    select.appendChild(first);



    data.quests.forEach(q => {

      const op = document.createElement("option");

      op.value = q;

      op.textContent = q;

      select.appendChild(op);

    });

  });

}



async function loadSavedPriorityQuests() {

  const res = await fetch("/refine/priority");

  const data = await res.json();

  document.getElementById("priority1").value = data.quests?.[0] || "";

  document.getElementById("priority2").value = data.quests?.[1] || "";

  document.getElementById("priority3").value = data.quests?.[2] || "";

}



async function savePriorityQuests() {

  const q1 = document.getElementById("priority1").value || "";

  const q2 = document.getElementById("priority2").value || "";

  const q3 = document.getElementById("priority3").value || "";

  await fetch(`/refine/priority/set?quest1=${encodeURIComponent(q1)}&quest2=${encodeURIComponent(q2)}&quest3=${encodeURIComponent(q3)}`);

  await loadPlan();

}



async function freezePlan() {

  await fetch("/refine/plan/freeze");

  await loadPlan();

}



async function recalcPlan() {

  await fetch("/refine/plan/recalc");

  await loadPlan();

}



async function clearPlan() {

  await fetch("/refine/plan/clear");

  await loadPlan();

}



function makeFruitSelect(selectId, selectedValue) {

  const select = document.createElement("select");

  select.id = selectId;

  select.className = "inline-select";



  const first = document.createElement("option");

  first.value = "";

  first.textContent = "\u9078\u629e\u306a\u3057";

  select.appendChild(first);



  FRUITS.forEach(fruit => {

    const op = document.createElement("option");

    op.value = fruit;

    op.textContent = fruit;

    if (fruit === selectedValue) op.selected = true;

    select.appendChild(op);

  });



  return select;

}



function makeDecisionSelect(selectId, selectedValue) {

  const select = document.createElement("select");

  select.id = selectId;

  select.className = "decision-select";



  const options = [

    { value: "unselected", label: "\u672a\u53b3\u9078" },

    { value: "fixed", label: "\u78ba\u5b9a" },

    { value: "redo", label: "\u3064\u3051\u76f4\u3057" },

  ];



  const normalizedValue = selectedValue || "unselected";



  options.forEach(item => {

    const op = document.createElement("option");

    op.value = item.value;

    op.textContent = item.label;

    if (item.value === normalizedValue) op.selected = true;

    select.appendChild(op);

  });



  return select;

}



function getStateClass(status) {

  if (status === "fixed") return "state state-kakutei";

  if (status === "redo") return "state state-tochu";

  if (status === "duplicate_redo") return "state state-tochu";

  return "state state-mitei";

}



async function saveRowSettings(charId, idx) {

  const params = new URLSearchParams();

  params.set("char_id", charId);



  for (let i = 0; i < 3; i++) {

    const fruit = document.getElementById(`fruit-${idx}-${i}`)?.value || "";

    const decision = document.getElementById(`decision-${idx}-${i}`)?.value || "unselected";

    params.append("fruit", fruit);

    params.append("decision", decision);

  }



  await fetch(`/refine/row/save?${params.toString()}`);

  await loadPlan();

}



async function loadPlan() {

  const res = await fetch("/refine/plan/view");

  const data = await res.json();



  const div = document.getElementById("planArea");

  div.innerHTML = "";



  if (!data.priority_quests || data.priority_quests.length === 0) {

    const msg = document.createElement("div");

    msg.className = "empty-message";

    msg.textContent = "\u512a\u5148\u30af\u30a8\u30b9\u30c8\u304c\u672a\u8a2d\u5b9a\u3067\u3059";

    div.appendChild(msg);

    return;

  }



  const summary = document.createElement("div");

  summary.className = "priority-summary-box";



  const summaryTitle = document.createElement("div");

  summaryTitle.className = "priority-summary-title";

  summaryTitle.textContent = "\u512a\u5148\u30af\u30a8\u30b9\u30c8";

  summary.appendChild(summaryTitle);



  const summaryBody = document.createElement("div");

  summaryBody.textContent = (data.priority_quests || []).join(" / ");

  summary.appendChild(summaryBody);



  div.appendChild(summary);



  if (data.recommend_balance_comment) {

    const infoBox = document.createElement("div");

    infoBox.className = "info-box";



    const title = document.createElement("div");

    title.className = "info-title";

    title.textContent = "\u304a\u3059\u3059\u3081\u5f79\u5272\u30d0\u30e9\u30f3\u30b9";

    infoBox.appendChild(title);



    const body = document.createElement("div");

    body.textContent = data.recommend_balance_comment;

    infoBox.appendChild(body);



    div.appendChild(infoBox);

  }



  if (!data.frozen_plan || data.frozen_plan.length === 0) {

    const msg = document.createElement("div");

    msg.className = "empty-message";

    msg.textContent = "\u53b3\u9078\u5bfe\u8c61\u304c\u307e\u3060\u9078\u51fa\u3055\u308c\u3066\u3044\u307e\u305b\u3093";

    div.appendChild(msg);

    return;

  }



  data.frozen_plan.forEach((row, idx) => {

    const card = document.createElement("div");

    card.className = "row-card";

    if (row.status === "fixed") {

      card.classList.add("row-card-fixed");

    } else {

      card.classList.add("row-card-unselected");

    }

    if (row.has_duplicate) card.classList.add("row-card-duplicate");



    const title = document.createElement("div");

    title.className = "char-title";

    title.textContent = row.title_name || "";

    card.appendChild(title);



    const acc = document.createElement("div");

    acc.className = "account-line";

    acc.textContent = `\u30a2\u30ab\u30a6\u30f3\u30c8\u540d: ${row.account || ""}`;

    card.appendChild(acc);



    const questsLine = document.createElement("div");

    questsLine.className = "quest-line";



    const questsTitle = document.createElement("span");

    questsTitle.textContent = "\u9069\u6b63\u30af\u30a8\u30b9\u30c8: ";

    questsLine.appendChild(questsTitle);



    (row.suitable_quests || []).forEach(item => {

      const displayText = (item && item.display) ? String(item.display).trim() : "";

      const questName = (item && item.quest) ? String(item.quest).trim() : "";



      const tag = document.createElement("span");

      tag.className =

        "tag " +

        ((data.priority_quests || []).includes(questName)

          ? "priority-quest-tag"

          : "normal-quest-tag");



      tag.textContent = displayText || questName;

      questsLine.appendChild(tag);

    });



    card.appendChild(questsLine);



    const statusLine = document.createElement("div");

    statusLine.className = "line";



    const state = document.createElement("span");

    state.className = getStateClass(row.status || "unselected");

    state.textContent = `\u72b6\u614b: ${row.status_label || "\u672a\u53b3\u9078"}`;

    statusLine.appendChild(state);



    const remain = document.createElement("span");

    remain.className = "state";

    remain.textContent = `\u6b8b\u308a: ${row.remain_count || 0}\u67a0`;

    statusLine.appendChild(remain);



    card.appendChild(statusLine);



    if (row.has_duplicate) {

      const warn = document.createElement("div");

      warn.className = "line small warn";

      warn.textContent = `\u91cd\u8907\u7121\u52b9\u306e\u53ef\u80fd\u6027: ${(row.duplicate_quests || []).join(" / ")}`;

      card.appendChild(warn);

    }



    const locked = document.createElement("div");

    locked.className = "line small";

    locked.textContent = `\u78ba\u5b9a\u6e08\u307f: ${((row.locked_fruits || []).join(" / ")) || "\u306a\u3057"}`;

    card.appendChild(locked);



    const mode = document.createElement("div");

    mode.className = "line small";

    mode.textContent = `\u518d\u63a8\u5968\u30e2\u30fc\u30c9: ${row.mode_label || "\u5143\u63a8\u5968\u7dad\u6301"}`;

    card.appendChild(mode);



    const head = document.createElement("div");

    head.className = "grid-head";

    head.innerHTML = `

      <div class="col-center">\u67a0</div>

      <div>\u73fe\u5728</div>

      <div>\u63a8\u5968</div>

      <div>\u53b3\u9078\u5224\u5b9a</div>

    `;

    card.appendChild(head);



    (row.display_rows || []).forEach((r, i) => {

      const grid = document.createElement("div");

      grid.className = "grid-row";



      const slot = document.createElement("div");

      slot.className = "col-center";

      slot.textContent = `\u67a0${r.slot_no}`;

      grid.appendChild(slot);



      const currentWrap = document.createElement("div");

      currentWrap.appendChild(makeFruitSelect(`fruit-${idx}-${i}`, r.current || ""));

      grid.appendChild(currentWrap);



      const suggestWrap = document.createElement("div");

      const suggestChip = document.createElement("span");

      suggestChip.className = "suggest-chip";

      suggestChip.textContent = r.suggest || "\u306a\u3057";

      suggestWrap.appendChild(suggestChip);

      grid.appendChild(suggestWrap);



      const decisionWrap = document.createElement("div");

      decisionWrap.appendChild(makeDecisionSelect(`decision-${idx}-${i}`, r.decision || "unselected"));

      grid.appendChild(decisionWrap);



      card.appendChild(grid);

    });



    const saveBtnLine = document.createElement("div");

    saveBtnLine.className = "line";

    const saveBtn = document.createElement("button");

    saveBtn.textContent = "\u3053\u306e\u500b\u4f53\u3092\u4fdd\u5b58";

    saveBtn.onclick = () => saveRowSettings(row.char_id, idx);

    saveBtnLine.appendChild(saveBtn);



    const note = document.createElement("span");

    note.className = "small";

    note.textContent = " \u9806\u756a\u9055\u3044\u3060\u3051\u3067\u306f\u4e0d\u4e00\u81f4\u6271\u3044\u306b\u3057\u307e\u305b\u3093\u3002";

    saveBtnLine.appendChild(note);



    card.appendChild(saveBtnLine);

    div.appendChild(card);

  });

}



async function initPage() {

  await loadQuestOptions();

  await loadSavedPriorityQuests();

  await loadPlan();

}



initPage();

</script>



</body>

</html>

"""

    html = html.replace("__FRUITS_JS__", fruits_js)

    return html





@app.get("/refine/row/save")

def refine_row_save(

    char_id: str,

    fruit: list[str] = Query(default=[]),

    decision: list[str] = Query(default=[]),

):

    cleaned_fruits = []

    cleaned_decisions = []



    for i in range(3):

        f = normalize_text(fruit[i]) if i < len(fruit) else ""

        d = normalize_decision_value(decision[i] if i < len(decision) else "unselected")

        cleaned_fruits.append(f)

        cleaned_decisions.append(d)



    set_fruits(char_id, cleaned_fruits)



    rows = []

    for i in range(3):

        rows.append({

            "fruit": cleaned_fruits[i],

            "decision": cleaned_decisions[i],

        })



    set_fruit_decisions(char_id, rows)

    return {"status": "ok", "saved_fruits": cleaned_fruits, "saved_decisions": cleaned_decisions}





@app.get("/refine/priority")

def refine_priority():

    return {"quests": get_priority_quests()}





@app.get("/refine/priority/set")

def refine_priority_set(quest1: str = "", quest2: str = "", quest3: str = ""):

    quests = [q for q in [quest1.strip(), quest2.strip(), quest3.strip()] if q]

    set_priority_quests(quests)

    return {"status": "ok", "quests": quests}





@app.get("/refine/plan/freeze")

def refine_plan_freeze():

    plan = build_frozen_plan()

    set_frozen_plan(plan)

    return {"status": "ok", "count": len(plan)}





@app.get("/refine/plan/recalc")

def refine_plan_recalc():

    plan = get_frozen_plan()

    return {"status": "ok", "count": len(plan), "recalculated": True}





@app.get("/refine/plan/clear")

def refine_plan_clear():

    clear_frozen_plan()

    return {"status": "ok"}





@app.get("/refine/plan/view")

def refine_plan_view():

    priority_quests = get_priority_quests()

    frozen_plan = build_plan_view_rows()



    recommend_balance_comment = ""

    if priority_quests:

        try:

            party_result = get_party_result(priority_quests[0])

            recommend_balance_comment = normalize_text(party_result.get("recommend_balance_comment", ""))

        except Exception:

            recommend_balance_comment = ""



    return {

        "priority_quests": priority_quests,

        "frozen_plan": frozen_plan,

        "recommend_balance_comment": recommend_balance_comment,

    }





@app.get("/party")

def get_party(quest: str):

    return get_party_result(quest)





@app.get("/quests")

def get_quests():

    return get_quest_list()





@app.get("/planner/refine_done")

def planner_refine_done(quest: str, value: str):

    flag = value == "1"

    set_refine_done(quest, flag)

    return {"status": "ok"}





@app.get("/planner/cleared")

def planner_cleared(quest: str, value: str):

    flag = value == "1"

    set_cleared(quest, flag)

    return {"status": "ok"}





@app.get("/planner/save_clear_party")

def planner_save_clear_party(quest: str):

    party_result = get_party_result(quest)

    save_clear_history(quest, party_result.get("party", []))

    return {"status": "ok"}





@app.get("/planner/clear_history")

def planner_clear_history(quest: str):

    return get_clear_history(quest)

