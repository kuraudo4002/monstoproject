# -*- coding: utf-8 -*-

import json
import re
import time
from collections import Counter
from itertools import product

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
    get_team_slot_state,
    set_team_slot_state,
)

app = FastAPI()

WAKUWAKU_CACHE = {}
WAKUWAKU_CACHE_TTL = 300

TEAM_SLOT_STATE = {}

def normalize_team_slot_key(quest, slot_no):
    return f"{normalize_text(quest)}||{int(slot_no)}"

def get_team_slot_state(quest, slot_no):
    key = normalize_team_slot_key(quest, slot_no)

    row = TEAM_SLOT_STATE.get(key)
    if not row:
        return {
            "mode": "auto",
            "char_id": "",
        }

    return {
        "mode": normalize_text(row.get("mode", "auto")) or "auto",
        "char_id": normalize_text(row.get("char_id", "")),
    }

def set_team_slot_state(quest, slot_no, mode, char_id):
    key = normalize_team_slot_key(quest, slot_no)

    TEAM_SLOT_STATE[key] = {
        "mode": normalize_text(mode) or "auto",
        "char_id": normalize_text(char_id),
    }

def build_team_rows_for_quest(quest, rows):
    slot_states = []

    for slot_no in range(1, 5):
        slot_states.append({
            "slot_no": slot_no,
            **get_team_slot_state(quest, slot_no),
        })

    locked = []
    manual = []
    auto = []

    used = set()

    for state in slot_states:
        mode = normalize_text(state.get("mode"))
        char_id = normalize_text(state.get("char_id"))

        if not char_id:
            continue

        matched = None

        for row in rows:
            if normalize_text(row.get("char_id")) == char_id:
                matched = row
                break

        if not matched:
            continue

        copied = dict(matched)
        copied["_slot_mode"] = mode

        if mode == "lock":
            locked.append(copied)
            used.add(char_id)

        elif mode == "manual":
            manual.append(copied)
            used.add(char_id)

    for row in rows:
        char_id = normalize_text(row.get("char_id"))

        if not char_id:
            continue

        if char_id in used:
            continue

        auto.append(dict(row))

    result = []

    result.extend(locked)
    result.extend(manual)
    result.extend(auto)

    return result[:4]

def cached_get_wakuwaku(char_id):
    char_id = normalize_text(char_id)
    now = time.time()

    cached = WAKUWAKU_CACHE.get(char_id)
    if cached:
        ts, value = cached
        if now - ts < WAKUWAKU_CACHE_TTL:
            return value

    try:
        value = get_wakuwaku(char_id)
    except Exception as e:
        print("wakuwaku read skipped:", e)
        value = ["", "", ""]

    WAKUWAKU_CACHE[char_id] = (now, value)
    return value

def clear_wakuwaku_cache(char_id=None):
    if char_id:
        WAKUWAKU_CACHE.pop(normalize_text(char_id), None)
    else:
        WAKUWAKU_CACHE.clear()

FRUITS = [
    "同族の加撃", "同族の加速", "同族の加命",
    "同族の加撃速", "同族の加命撃", "同族の加命速",
    "撃種の加撃", "撃種の加速", "撃種の加命",
    "撃種の加撃速", "撃種の加命撃", "撃種の加命速",
    "戦型の加撃", "戦型の加速", "戦型の加命",
    "戦型の加撃速", "戦型の加命撃", "戦型の加命速",
    "友撃", "速必", "将命", "兵命", "ケガ減り", "一撃失心", "ちび癒し", "その他",
]

ATTACK_FRUITS = {
    "同族の加撃", "同族の加撃速", "同族の加命撃",
    "戦型の加撃", "戦型の加撃速", "戦型の加命撃",
    "撃種の加撃", "撃種の加撃速", "撃種の加命撃",
}

SUPPORT_FRUITS = {"将命", "兵命", "速必", "ケガ減り"}
FRIEND_FRUITS = {"友撃"}
DUPLICATE_ALLOWED_FRUITS = {"一撃失心", "ちび癒し"}

STATUS_LABELS = {
    "fixed": "確定",
    "unselected": "未厳選",
}

MODE_LABELS = {
    "attack": "火力寄り",
    "support": "サポート寄り",
    "friend": "友情寄り",
    "keep": "元推奨維持",
}

def normalize_text(x):
    if x is None:
        return ""
    return str(x).strip()

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

def normalize_form_name_for_match(text):
    text = normalize_text(text)
    text = text.replace("\uff08", "(").replace("\uff09", ")")
    text = strip_rank_suffix(text)
    text = strip_account_suffix(text)
    text = re.sub(r"\s+", "", text).strip()
    return text

def has_form_suffix(text):
    text = normalize_form_name_for_match(text)
    return "(" in text and ")" in text

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

def is_attack_fruit(fruit):
    fruit = normalize_text(fruit)
    return fruit in ATTACK_FRUITS or fruit.startswith("同族") or fruit.startswith("戦型") or fruit.startswith("撃種")

def is_support_fruit(fruit):
    return normalize_text(fruit) in SUPPORT_FRUITS

def is_friend_fruit(fruit):
    return normalize_text(fruit) in FRIEND_FRUITS

def mode_label(x):
    return MODE_LABELS.get(normalize_text(x), "元推奨維持")

def status_label(x):
    return STATUS_LABELS.get(normalize_text(x), "未厳選")

def get_all_suitable_quests_for_char(char_name, priority_quests):
    try:
        data, _ = get_cached()
    except Exception:
        return []

    qx = data.get("quest_expanded")
    if qx is None or getattr(qx, "empty", True):
        return []

    target_full = normalize_form_name_for_match(char_name)
    if not target_full:
        return []

    quest_col = "\u30af\u30a8\u30b9\u30c8\u540d"
    rank_col = "\u30e9\u30f3\u30af"
    char_col = "\u30ad\u30e3\u30e9\u540d"

    required_cols = [quest_col, rank_col, char_col]
    for col in required_cols:
        if col not in qx.columns:
            return []

    found = []
    seen = set()

    for _, row in qx.iterrows():
        quest_name = normalize_text(row.get(quest_col, ""))
        rank = normalize_text(row.get(rank_col, ""))
        char_full = normalize_text(row.get(char_col, ""))

        if not quest_name:
            continue

        cand_full = normalize_form_name_for_match(char_full)

        # Exact form match only.
        # Example:
        # Gekirin(angry form) must not pick Gekirin(calm form).
        if cand_full != target_full:
            continue

        key = (quest_name, rank, cand_full)
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

    priority_first.sort(
        key=lambda x: priority_quests.index(x["quest"]) if x["quest"] in priority_quests else 999
    )
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
                    "pure_name": title_name,
                    "account": account_name,
                    "quests": [quest],
                    "suggest_wakuwaku": row.get("suggest", []),
                }
            else:
                if quest not in merged[char_id]["quests"]:
                    merged[char_id]["quests"].append(quest)

    return list(merged.values())

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

def optimizer_is_attack_fruit(fruit):
    fruit = normalize_text(fruit)
    return fruit.startswith("同族") or fruit.startswith("戦型") or fruit.startswith("撃種")

def optimizer_affected_count(fruit, members):
    fruit = normalize_text(fruit)

    if fruit.startswith("同族"):
        values = [normalize_text(m.get("tribe", "")) for m in members]
    elif fruit.startswith("戦型"):
        values = [normalize_text(m.get("style", "")) for m in members]
    elif fruit.startswith("撃種"):
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
        battle_type = normalize_text(member.get("battle_type", ""))

        for fruit in fruits:
            fruit = normalize_text(fruit)
            if not fruit:
                continue

            if fruit.startswith("同族"):
                key = (fruit, "same", tribe)
            elif fruit.startswith("戦型"):
                key = (fruit, "style", style)
            elif fruit.startswith("撃種"):
                key = (fruit, "type", battle_type)
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
        ("同族の加撃", "同族の加撃速", "同族の加命撃"),
        ("撃種の加撃", "撃種の加撃速", "撃種の加命撃"),
        ("戦型の加撃", "戦型の加撃速", "戦型の加命撃"),
        ("同族の加撃", "撃種の加撃", "戦型の加撃"),
        ("同族の加撃速", "撃種の加撃速", "戦型の加撃速"),
        ("同族の加命撃", "撃種の加命撃", "戦型の加命撃"),
        ("将命", "兵命", "速必"),
        ("将命", "兵命", "ケガ減り"),
        ("友撃", "速必", "ケガ減り"),
    ]

def optimizer_best_plan(members):
    if not members:
        return [], 0

    candidates = [optimizer_build_candidates() for _ in members]
    best = None
    best_score = -999999

    for combo in product(*candidates):
        current_score = optimizer_score(combo, members)
        if current_score > best_score:
            best_score = current_score
            best = combo

    return best or [], best_score

def optimizer_mode_from_suggest(suggest):
    attack_count = sum(1 for f in suggest if optimizer_is_attack_fruit(f))
    support_count = sum(1 for f in suggest if is_support_fruit(f) or is_friend_fruit(f))

    if attack_count >= 2:
        return "attack"
    if support_count >= 2:
        return "support"
    return "keep"

def normalize_three(items):
    values = [normalize_text(x) for x in items]
    values = values[:3]
    while len(values) < 3:
        values.append("")
    return values

def unordered_match_flags(current, target):
    current = normalize_three(current)
    target_pool = [x for x in normalize_three(target) if x]

    flags = []

    for fruit in current:
        fruit = normalize_text(fruit)
        if fruit and fruit in target_pool:
            flags.append(True)
            target_pool.remove(fruit)
        else:
            flags.append(False)

    return flags

def is_complete_by_current_and_target(current, target):
    current = normalize_three(current)
    target = normalize_three(target)

    if not all(current):
        return False
    if not all(target):
        return False

    return sorted(current) == sorted(target)

def calc_remain_count(current, target):
    flags = unordered_match_flags(current, target)
    return 3 - sum(1 for x in flags if x)

def sort_priority_rows(rows, priority_quests):
    quest_order_map = {q: i for i, q in enumerate(priority_quests)}

    def row_key(row):
        is_complete = 1 if row.get("is_complete") else 0
        first_priority = min(
            [quest_order_map.get(q, 999) for q in row.get("quests", [])]
        ) if row.get("quests") else 999
        priority_overlap = sum(1 for q in row.get("quests", []) if q in priority_quests)
        multi_quest_score = len(row.get("quests", []))

        return (
            is_complete,
            first_priority,
            -priority_overlap,
            -multi_quest_score,
            row.get("title_name", ""),
            row.get("account", ""),
        )

    return sorted(rows, key=row_key)

def build_plan_view_rows():
    frozen = get_frozen_plan()
    priority_quests = get_priority_quests()
    rows = []

    party_meta_by_quest = collect_party_meta_for_priority_quests(priority_quests)
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

    for row in frozen:
        char_id = row["char_id"]

        raw_current_wakuwaku = cached_get_wakuwaku(char_id)
        original_suggest = [normalize_text(x) for x in row.get("suggest_wakuwaku", []) if normalize_text(x)]
        current = normalize_three(raw_current_wakuwaku)

        stored_rows = get_fruit_decisions(char_id) or []

        refine_mode = "auto"
        saved_target = ["", "", ""]

        if stored_rows:
            first_mode = normalize_text(stored_rows[0].get("mode", ""))
            if first_mode in ["auto", "manual"]:
                refine_mode = first_mode

            for i in range(3):
                if i < len(stored_rows):
                    saved_target[i] = normalize_text(stored_rows[i].get("target", ""))
                    if not saved_target[i]:
                        saved_target[i] = normalize_text(stored_rows[i].get("manual_suggest", ""))

        ai_suggest = optimizer_suggest_by_char_id.get(char_id, original_suggest)
        ai_suggest = normalize_three(ai_suggest)

        if refine_mode == "manual" and any(saved_target):
            target = normalize_three(saved_target)
        else:
            target = normalize_three(ai_suggest)

        match_flags = unordered_match_flags(current, target)
        is_complete = is_complete_by_current_and_target(current, target)
        remain_count = calc_remain_count(current, target)
        status = "fixed" if is_complete else "unselected"

        suitable_quests = get_all_suitable_quests_for_char(
            char_name=row.get("title_name", "") or row.get("pure_name", ""),
            priority_quests=priority_quests,
        )

        if not suitable_quests:
            suitable_quests = [{"quest": q, "rank": "", "display": q} for q in row.get("quests", [])]

        display_rows = []
        for i in range(3):
            display_rows.append({
                "slot_no": i + 1,
                "current": current[i],
                "target": target[i],
                "matched": match_flags[i],
            })

        mode = optimizer_mode_from_suggest(ai_suggest)

        rows.append({
            "char_id": char_id,
            "title_name": row.get("title_name", ""),
            "account": row.get("account", ""),
            "suitable_quests": suitable_quests,
            "quests": row.get("quests", []),
            "refine_mode": refine_mode,
            "ai_suggest": ai_suggest,
            "target": target,
            "display_rows": display_rows,
            "status": status,
            "status_label": status_label(status),
            "remain_count": remain_count,
            "is_complete": is_complete,
            "mode": mode,
            "mode_label": mode_label(mode),
        })

    return sort_priority_rows(rows, priority_quests)

@app.get("/", response_class=HTMLResponse)
def home():
    fruits_js = json.dumps(FRUITS, ensure_ascii=True)

    html = """
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>モンスト編成ツール</title>
<style>
* {
  box-sizing: border-box;
}

body {
  font-family: Arial, sans-serif;
  padding: 24px;
  background: #f5f5f5;
  margin: 0;
}

h1, h2 {
  margin-top: 18px;
  margin-bottom: 10px;
}

select {
  padding: 8px;
  font-size: 16px;
  width: 260px;
  max-width: 100%;
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
  margin: 18px auto 0 auto;
  width: min(980px, 100%);
}

.row-card {
  background: #fff5f5;
  border: 1px solid #f1aeb5;
  border-radius: 8px;
  padding: 12px;
  margin-top: 12px;
}

.row-card-fixed {
  background: #f2fbf2;
  border-color: #8fd19e;
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
  margin-top: 8px;
}

.small {
  font-size: 12px;
  color: #666;
}

.mode-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.mode-line select {
  width: 140px;
  margin: 0;
}

.recommend-combo {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 8px;
  align-items: center;
}

.recommend-title {
  font-size: 13px;
  font-weight: bold;
}

.recommend-chip,
.target-chip {
  display: inline-block;
  padding: 5px 8px;
  border-radius: 6px;
  font-size: 12px;
  background: #dff3ff;
  word-break: break-word;
}

.grid-head,
.grid-row {
  display: grid;
  grid-template-columns: 50px minmax(0, 1.5fr) minmax(0, 0.9fr);
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

.grid-row-matched {
  background: #f2fbf2;
  border-color: #8fd19e;
}

.col-center {
  text-align: center;
}

.inline-select {
  width: 100%;
  min-width: 0;
  margin: 0;
}

.target-select {
  width: 100%;
  min-width: 0;
  margin: 0;
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

.completed-toggle {
  width: 100%;
  margin: 16px 0 0 0;
  padding: 10px 12px;
  border: 1px solid #8fd19e;
  border-radius: 8px;
  background: #f2fbf2;
  font-weight: bold;
  text-align: left;
}

.completed-area {
  display: none;
}

.completed-area.open {
  display: block;
}

.section-label {
  margin-top: 14px;
  font-size: 14px;
  font-weight: bold;
  color: #555;
}

@media (max-width: 700px) {
  body {
    padding: 12px;
  }

  .grid-head,
  .grid-row {
    grid-template-columns: 42px minmax(0, 1fr);
  }

  .grid-head div:nth-child(3),
  .grid-row div:nth-child(3) {
    grid-column: 2 / 3;
  }

  button {
    margin-top: 6px;
    margin-left: 0;
  }
}
.priority-third-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.decide-button {
  margin-left: 0;
  margin-bottom: 8px;
}

.team-toggle {
  width: 100%;
  margin: 14px 0 0 0;
  padding: 10px 12px;
  border: 1px solid #74c0fc;
  border-radius: 8px;
  background: #e7f5ff;
  font-weight: bold;
  text-align: left;
}

.team-area {
  display: none;
  margin-top: 10px;
}

.team-area.open {
  display: block;
}

.team-quest-box {
  margin-top: 12px;
  padding: 10px;
  border: 1px solid #d0ebff;
  border-radius: 8px;
  background: #f8fbff;
}

.team-quest-title {
  font-weight: bold;
  margin-bottom: 8px;
}

.unfinished-account-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.unfinished-account-box {
  margin-top: 0;
}

.team-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(150px, 1fr));
  gap: 10px;
}

.team-card {
  min-height: 220px;
  padding: 10px;
  border: 1px solid #adb5bd;
  border-radius: 10px;
  background: white;
  font-size: 14px;
}

.unfinished-card {
  margin-top: 12px;
}

.team-slot-mode {
  width: 100%;
  margin-bottom: 8px;
  font-size: 13px;
}

.team-card-title {
  font-weight: bold;
  font-size: 18px;
  line-height: 1.3;
  word-break: break-word;
}

.team-title-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 6px 0 8px 0;
}

.team-card-account {
  font-size: 15px;
  font-weight: bold;
  margin-top: 2px;
}

.team-card-line {
  margin-top: 6px;
  word-break: break-word;
}

.team-card-role {
  margin-top: 6px;
  display: inline-block;
  padding: 3px 8px;
  border-radius: 999px;
  background: #e7f5ff;
  font-size: 12px;
  font-weight: bold;
}

.team-fruit-area {
  margin-top: 10px;
}

.team-fruit-box {
  border: 1px solid #ced4da;
  border-radius: 8px;
  padding: 7px 8px;
  margin-top: 6px;
  background: #f8f9fa;
  font-size: 13px;
  font-weight: bold;
  word-break: break-word;
}

.team-empty {
  padding: 8px;
  color: #777;
  font-size: 12px;
}

@media (max-width: 700px) {
  .unfinished-account-grid {
    grid-template-columns: 1fr;
  }

  .team-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.team-lock-line {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 6px 0 8px 0;
  font-size: 13px;
  font-weight: bold;
}

.team-lock-button {
  width: 28px;
  height: 28px;
  margin: 0;
  padding: 0;
  border: 1px solid #adb5bd;
  border-radius: 50%;
  background: #f8f9fa;
  cursor: pointer;
  font-size: 15px;
  line-height: 1;
  font-weight: bold;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.team-lock-button.is-locked {
  border-color: #fab005;
  background: #fff9db;
}

</style>
</head>
<body>

<h1>モンスト編成ツール</h1>

<div class="block">
  <h2>わくわく厳選</h2>

  <div class="top-buttons">
  <div>1. <select id="priority1"></select></div>
  <div>2. <select id="priority2"></select></div>
  <div class="priority-third-row">
    <span>3. </span>
    <select id="priority3"></select>
    <button class="decide-button" onclick="decidePlan()">決定</button>
  </div>
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
    first.textContent = "クエストを選択";
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

async function decidePlan() {
  const q1 = document.getElementById("priority1").value || "";
  const q2 = document.getElementById("priority2").value || "";
  const q3 = document.getElementById("priority3").value || "";

  await fetch(`/refine/priority/set?quest1=${encodeURIComponent(q1)}&quest2=${encodeURIComponent(q2)}&quest3=${encodeURIComponent(q3)}`);
  await fetch("/refine/plan/freeze");

  await loadSavedPriorityQuests();
  await loadPlan();
}

async function savePriorityQuests() {
  const q1 = document.getElementById("priority1").value || "";
  const q2 = document.getElementById("priority2").value || "";
  const q3 = document.getElementById("priority3").value || "";

  await fetch(`/refine/priority/set?quest1=${encodeURIComponent(q1)}&quest2=${encodeURIComponent(q2)}&quest3=${encodeURIComponent(q3)}`);
  await loadSavedPriorityQuests();
}

async function freezePlan() {
  await fetch("/refine/plan/freeze");

  await loadPlan();
}

async function recalcPlan() {
  await fetch("/refine/plan/recalc");
}

async function clearPlan() {
  await fetch("/refine/plan/clear");
}

function makeFruitSelect(selectId, selectedValue) {
  const select = document.createElement("select");
  select.id = selectId;
  select.className = "inline-select";

  const first = document.createElement("option");
  first.value = "";
  first.textContent = "選択なし";
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

function makeTargetSelect(selectId, selectedValue, enabled) {
  const select = makeFruitSelect(selectId, selectedValue);
  select.className = "target-select";
  select.disabled = !enabled;
  return select;
}

function makeModeSelect(selectId, selectedValue) {
  const select = document.createElement("select");
  select.id = selectId;

  const options = [
    { value: "auto", label: "自動" },
    { value: "manual", label: "手動" },
  ];

  const normalizedValue = selectedValue || "auto";

  options.forEach(item => {
    const op = document.createElement("option");
    op.value = item.value;
    op.textContent = item.label;
    if (item.value === normalizedValue) op.selected = true;
    select.appendChild(op);
  });

  return select;
}

function toggleTargetMode(idx) {
  const mode = document.getElementById(`mode-${idx}`)?.value || "auto";

  for (let i = 0; i < 3; i++) {
    const target = document.getElementById(`target-${idx}-${i}`);
    if (!target) continue;
    target.disabled = mode !== "manual";
  }
}

async function saveRowSettings(charId, idx) {
  const params = new URLSearchParams();
  params.set("char_id", charId);

  const mode = document.getElementById(`mode-${idx}`)?.value || "auto";
  params.set("mode", mode);

  for (let i = 0; i < 3; i++) {
    const fruit = document.getElementById(`fruit-${idx}-${i}`)?.value || "";
    const target = document.getElementById(`target-${idx}-${i}`)?.value || "";

    params.append("fruit", fruit);
    params.append("target", target);
    params.append("suggest", target);
    params.append("decision", "unselected");
  }

  await fetch(`/refine/row/save?${params.toString()}`);
}

function addRecommendCombo(card, row) {
  const wrap = document.createElement("div");
  wrap.className = "recommend-combo";

  const title = document.createElement("span");
  title.className = "recommend-title";
  title.textContent = "\u63a8\u5968\u7d44\u307f\u5408\u308f\u305b:";
  wrap.appendChild(title);

  const suggestList = (row.target && row.target.length > 0)
    ? row.target
    : (row.ai_suggest || []);

  suggestList.forEach(fruit => {
    const chip = document.createElement("span");
    chip.className = "recommend-chip";
    chip.textContent = fruit || "\u306a\u3057";
    wrap.appendChild(chip);
  });

  card.appendChild(wrap);
}

function toggleCompletedArea() {
  const area = document.getElementById("completedArea");
  const btn = document.getElementById("completedToggleBtn");

  if (!area || !btn) return;

  const isOpen = area.classList.toggle("open");
  const count = btn.dataset.count || "0";
  btn.textContent = isOpen
    ? `厳選済みキャラ ${count}体を隠す ▲`
    : `厳選済みキャラ ${count}体を表示 ▼`;
}

function makeRowCard(row, idx, data) {
  const card = document.createElement("div");
  card.className = "team-card unfinished-card";

  if (row.is_complete) {
    card.classList.add("row-card-fixed");
  }

  const title = document.createElement("div");
  title.className = "team-card-title";
  title.textContent = row.title_name || "";
  card.appendChild(title);

  const acc = document.createElement("div");
  acc.className = "team-card-line";
  acc.textContent = row.account || "";
  card.appendChild(acc);

  const questsLine = document.createElement("div");
  questsLine.className = "team-card-line";

  const questsTitle = document.createElement("span");
  questsTitle.textContent = "適正クエスト: ";
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

  const mode = document.createElement("div");
  mode.className = "mode-line";

  const modeLabel = document.createElement("span");
  modeLabel.textContent = "厳選モード:";
  mode.appendChild(modeLabel);

  const modeSelect = makeModeSelect(`mode-${idx}`, row.refine_mode || "auto");
  modeSelect.onchange = () => { toggleTargetMode(idx); saveRowSettings(row.char_id, idx); };
  mode.appendChild(modeSelect);

  card.appendChild(mode);

  addRecommendCombo(card, row);

  const head = document.createElement("div");
  head.className = "grid-head";
  head.innerHTML = `
    <div class="col-center">枠</div>
    <div>現在</div>
    <div>目標</div>
  `;
  card.appendChild(head);

  (row.display_rows || []).forEach((r, i) => {
    const grid = document.createElement("div");
    grid.className = "grid-row";

    if (r.matched) {
      grid.classList.add("grid-row-matched");
    }

    const slot = document.createElement("div");
    slot.className = "col-center";
    slot.textContent = `枠${r.slot_no}`;
    grid.appendChild(slot);

    const currentWrap = document.createElement("div");
    const currentSelect = makeFruitSelect(`fruit-${idx}-${i}`, r.current || "");
      currentSelect.onchange = () => saveRowSettings(row.char_id, idx);
      currentWrap.appendChild(currentSelect);
    grid.appendChild(currentWrap);

    const targetWrap = document.createElement("div");
    const targetSelect = makeTargetSelect(
      `target-${idx}-${i}`,
      r.target || "",
      (row.refine_mode || "auto") === "manual"
    );
    targetSelect.onchange = () => saveRowSettings(row.char_id, idx);
    targetWrap.appendChild(targetSelect);
    grid.appendChild(targetWrap);

    card.appendChild(grid);
  });

  return card;
}

function toggleTeamArea() {
  const area = document.getElementById("teamArea");
  const btn = document.getElementById("teamToggleBtn");

  if (!area || !btn) return;

  const isOpen = area.classList.toggle("open");
  btn.textContent = isOpen
    ? "\u30c1\u30fc\u30e0\u7de8\u6210\u3092\u96a0\u3059 \u25b2"
    : "\u30c1\u30fc\u30e0\u7de8\u6210\u3092\u8868\u793a \u25bc";
}

async function saveTeamSlotState(quest, slotNo, mode, charId) {
  const params = new URLSearchParams();

  params.set("quest", quest || "");
  params.set("slot_no", String(slotNo));
  params.set("mode", mode || "auto");
  params.set("char_id", charId || "");

  await fetch(`/team/slot/state?${params.toString()}`);
}

function getQuestCandidateRows(data, quest) {
  const byQuest = data.team_candidates_by_quest || {};
  let rows = [];

  if (byQuest[quest]) {
    rows = [...byQuest[quest]];
  } else {
    rows = (data.frozen_plan || []).filter(row => {
      if ((row.quests || []).includes(quest)) {
        return true;
      }

      return (row.suitable_quests || []).some(item => {
        return item && item.quest === quest;
      });
    });
  }

  function accountOrder(account) {
    const value = String(account || "");

    if (value.startsWith("\u30e1\u30a4\u30f3")) return 0;
    if (value.startsWith("\u30b5\u30d6\u30b5\u30d6")) return 2;
    if (value.startsWith("\u30b5\u30d6")) return 1;

    return 999;
  }

  rows.sort((a, b) => {
    const accDiff = accountOrder(a.account) - accountOrder(b.account);

    if (accDiff !== 0) {
      return accDiff;
    }

    const nameDiff = String(a.title_name || "").localeCompare(
      String(b.title_name || ""),
      "ja"
    );

    if (nameDiff !== 0) {
      return nameDiff;
    }

    return String(a.char_id || "").localeCompare(String(b.char_id || ""));
  });

  return rows;
}


function makeTeamCard(row, quest, slotNo, data) {
  const card = document.createElement("div");
  card.className = "team-card";

  const modeSelect = document.createElement("select");
  modeSelect.className = "team-slot-mode";

  [
    { value: "auto", label: "\u81ea\u52d5" },
    { value: "manual", label: "\u624b\u52d5" },
  ].forEach(item => {
    const op = document.createElement("option");
    op.value = item.value;
    op.textContent = item.label;
    modeSelect.appendChild(op);
  });

  card.appendChild(modeSelect);

  const manualWrap = document.createElement("div");
  manualWrap.style.display = "none";

  const accountSelect = document.createElement("select");
  accountSelect.className = "team-slot-mode";

  const charSelect = document.createElement("select");
  charSelect.className = "team-slot-mode";

  const individualSelect = document.createElement("select");
  individualSelect.className = "team-slot-mode";

  manualWrap.appendChild(accountSelect);
  manualWrap.appendChild(charSelect);
  manualWrap.appendChild(individualSelect);
  card.appendChild(manualWrap);

  const candidateRows = getQuestCandidateRows(data, quest);

  function accountOrder(account) {
    const value = String(account || "");

    if (value.startsWith("\u30e1\u30a4\u30f3")) return 0;
    if (value.startsWith("\u30b5\u30d6\u30b5\u30d6")) return 2;
    if (value.startsWith("\u30b5\u30d6")) return 1;

    return 999;
  }

  function getCandidateById(charId) {
    return candidateRows.find(candidate => {
      return (candidate.char_id || "") === (charId || "");
    });
  }

  function getNumFromCharId(charId) {
    const parts = String(charId || "").split("||");
    return parts.length >= 4 ? parts[3] : "";
  }

  function resetSelect(select) {
    select.innerHTML = "";
  }

  function addOption(select, value, label, selected) {
    const op = document.createElement("option");
    op.value = value || "";
    op.textContent = label || "";
    if (selected) op.selected = true;
    select.appendChild(op);
  }

  function selectedAccount() {
    return accountSelect.value || "";
  }

  function selectedTitleName() {
    return charSelect.value || "";
  }

  function populateAccountSelect(selectedAcc) {
    resetSelect(accountSelect);

    const accounts = Array.from(new Set(
      candidateRows
        .map(candidate => candidate.account || "")
        .filter(Boolean)
    ));

    accounts.sort((a, b) => accountOrder(a) - accountOrder(b));

    accounts.forEach(acc => {
      addOption(accountSelect, acc, acc, acc === selectedAcc);
    });
  }

  function populateCharSelect(selectedName) {
    resetSelect(charSelect);

    const acc = selectedAccount();

    const names = Array.from(new Set(
      candidateRows
        .filter(candidate => (candidate.account || "") === acc)
        .map(candidate => candidate.title_name || "")
        .filter(Boolean)
    ));

    names.sort((a, b) => String(a).localeCompare(String(b), "ja"));

    names.forEach(name => {
      addOption(charSelect, name, name, name === selectedName);
    });
  }

  function populateIndividualSelect(selectedCharId) {
    resetSelect(individualSelect);

    const acc = selectedAccount();
    const name = selectedTitleName();

    const rows = candidateRows
      .filter(candidate => {
        return (candidate.account || "") === acc
          && (candidate.title_name || "") === name;
      })
      .sort((a, b) => {
        return String(a.char_id || "").localeCompare(String(b.char_id || ""));
      });

    rows.forEach(candidate => {
      const num = getNumFromCharId(candidate.char_id);
      const category = candidate.fruit_category || "\u672a\u53b3\u9078";
      const label = `\u500b\u4f53${num} | ${category}`;

      addOption(
        individualSelect,
        candidate.char_id || "",
        label,
        (candidate.char_id || "") === selectedCharId
      );
    });
  }

  function setupManualSelects() {
    const selected = getCandidateById(row.char_id || "") || row;
    const acc = selected.account || "";
    const title = selected.title_name || "";
    const charId = selected.char_id || row.char_id || "";

    populateAccountSelect(acc);
    populateCharSelect(title);
    populateIndividualSelect(charId);
  }

  setupManualSelects();

  const lockWrap = document.createElement("label");
  lockWrap.className = "team-lock-line";

  const lockButton = document.createElement("button");
  lockButton.type = "button";
  lockButton.className = "team-lock-button";
  lockWrap.appendChild(lockButton);

  let isLocked = false;

  function applyLockUi() {
    lockButton.textContent = isLocked ? "🔒" : "🔓";
    lockButton.classList.toggle("is-locked", isLocked);
  }

  function refreshManualVisibility() {
    const baseMode = modeSelect.value || "auto";

    manualWrap.style.display =
      baseMode === "manual" && !isLocked
        ? ""
        : "none";
  }

  const slotMode = row._slot_mode || "auto";

  if (slotMode === "manual") {
    modeSelect.value = "manual";
  } else {
    modeSelect.value = "auto";
  }

  if (slotMode === "lock") {
    isLocked = true;
    modeSelect.value = "auto";
  }

  applyLockUi();
  refreshManualVisibility();

  modeSelect.onchange = async () => {
    const baseMode = modeSelect.value || "auto";
    const mode = isLocked ? "lock" : baseMode;
    refreshManualVisibility();

    await saveTeamSlotState(
      quest,
      slotNo,
      mode,
      isLocked ? (row.char_id || "") : (individualSelect.value || row.char_id || "")
    );
  };

  lockButton.onclick = async () => {
    isLocked = !isLocked;
    applyLockUi();

    const baseMode = modeSelect.value || "auto";
    const mode = isLocked ? "lock" : baseMode;
    refreshManualVisibility();

    await saveTeamSlotState(
      quest,
      slotNo,
      mode,
      isLocked ? (row.char_id || "") : (individualSelect.value || row.char_id || "")
    );
  };

  accountSelect.onchange = async () => {
    populateCharSelect("");
    populateIndividualSelect("");

    await saveTeamSlotState(
      quest,
      slotNo,
      modeSelect.value || "auto",
      individualSelect.value || ""
    );
  };

  charSelect.onchange = async () => {
    populateIndividualSelect("");

    await saveTeamSlotState(
      quest,
      slotNo,
      modeSelect.value || "auto",
      individualSelect.value || ""
    );
  };

  individualSelect.onchange = async () => {
    const baseMode = modeSelect.value || "auto";
    const mode = isLocked ? "lock" : baseMode;

    await saveTeamSlotState(
      quest,
      slotNo,
      mode,
      individualSelect.value || ""
    );
  };

  const titleLine = document.createElement("div");
  titleLine.className = "team-title-line";
  titleLine.appendChild(lockWrap);

  const title = document.createElement("div");
  title.className = "team-card-title";
  title.textContent = row.title_name || "";
  titleLine.appendChild(title);
  card.appendChild(titleLine);

  const account = document.createElement("div");
  account.className = "team-card-line";
  account.textContent = row.account || "";
  card.appendChild(account);

  const role = document.createElement("div");
  role.className = "team-card-line";
  role.textContent = row.role_label ? `\u5f79\u5272: ${row.role_label}` : "";
  card.appendChild(role);

  const fruitArea = document.createElement("div");
  fruitArea.className = "team-fruit-area";

  const fruits = (row.display_rows || [])
    .map(r => r.current || "");

  for (let i = 0; i < 3; i++) {
    const fruitBox = document.createElement("div");
    fruitBox.className = "team-fruit-box";

    const fruit = fruits[i] || "\u306a\u3057";
    const target = ((row.display_rows || [])[i] || {}).target || "";
    const matched = Boolean(((row.display_rows || [])[i] || {}).matched);

    if (matched) {
      fruitBox.classList.add("team-fruit-box-matched");
    }

    const currentLine = document.createElement("div");
    currentLine.textContent = `${i + 1}. ${fruit}`;
    fruitBox.appendChild(currentLine);

    if (target) {
      const targetLine = document.createElement("div");
      targetLine.className = "small";
      targetLine.textContent = `\u63a8\u5968: ${target}`;
      fruitBox.appendChild(targetLine);
    }

    fruitArea.appendChild(fruitBox);
  }

  card.appendChild(fruitArea);

  return card;
}


function addTeamCompositionSection(div, data) {
  const teamRowsByQuest = data.team_rows_by_quest || {};

  const btn = document.createElement("button");
  btn.id = "teamToggleBtn";
  btn.className = "team-toggle";
  btn.textContent = "\u30c1\u30fc\u30e0\u7de8\u6210\u3092\u8868\u793a \u25bc";
  btn.onclick = toggleTeamArea;
  div.appendChild(btn);

  const area = document.createElement("div");
  area.id = "teamArea";
  area.className = "team-area";

  (data.priority_quests || []).forEach((quest, questIdx) => {
    const box = document.createElement("div");
    box.className = "team-quest-box";

    const title = document.createElement("div");
    title.className = "team-quest-title";
    title.textContent = `${questIdx + 1}. ${quest}`;
    box.appendChild(title);

    const grid = document.createElement("div");
    grid.className = "team-grid";

    const questRows = (teamRowsByQuest[quest] || [])
      .slice(0, 4);

    if (questRows.length === 0) {
      const empty = document.createElement("div");
      empty.className = "team-empty";
      empty.textContent = "\u7de8\u6210\u30ad\u30e3\u30e9\u306a\u3057";
      box.appendChild(empty);
    } else {
      questRows.forEach((row, idx) => {
        grid.appendChild(makeTeamCard(row, quest, idx + 1, data));
      });
      box.appendChild(grid);
    }

    area.appendChild(box);
  });

  const refreshWrap = document.createElement("div");
  refreshWrap.style.display = "flex";
  refreshWrap.style.justifyContent = "flex-end";
  refreshWrap.style.marginTop = "12px";

  const refreshBtn = document.createElement("button");
  refreshBtn.textContent = "\u66f4\u65b0";

  refreshBtn.onclick = async () => {
    await loadPlan();
  };

  refreshWrap.appendChild(refreshBtn);

  area.appendChild(refreshWrap);

  div.appendChild(area);
}

async function loadPlan() {
  const res = await fetch("/refine/plan/view");
  const data = await res.json();

  const div = document.getElementById("planArea");
  div.innerHTML = "";

  if (!data.priority_quests || data.priority_quests.length === 0) {
    const msg = document.createElement("div");
    msg.className = "empty-message";
    msg.textContent = "優先クエストが未設定です";
    div.appendChild(msg);
    return;
  }

  const summary = document.createElement("div");
  summary.className = "priority-summary-box";

  const summaryTitle = document.createElement("div");
  summaryTitle.className = "priority-summary-title";
  summaryTitle.textContent = "優先クエスト";
  summary.appendChild(summaryTitle);

  const summaryBody = document.createElement("div");
  summaryBody.textContent = (data.priority_quests || [])
    .map((q, i) => `${i + 1}. ${q}`)
    .join(" / ");
  summary.appendChild(summaryBody);

  div.appendChild(summary);

  if (!data.frozen_plan || data.frozen_plan.length === 0) {
    const msg = document.createElement("div");
    msg.className = "empty-message";
    msg.textContent = "厳選対象がまだ選出されていません";
    div.appendChild(msg);
    return;
  }

  const refineMap = new Map();
  const teamRowsByQuest = data.team_rows_by_quest || {};

  Object.values(teamRowsByQuest).forEach(rows => {
    (rows || []).forEach(row => {
      const charId = row.char_id || "";
      if (!charId) return;

      if (!refineMap.has(charId)) {
        refineMap.set(charId, row);
      }
    });
  });

  const refineRows = Array.from(refineMap.values());
  const unfinishedRows = refineRows.filter(row => !row.is_complete);

  addTeamCompositionSection(div, data);

  const unfinishedLabel = document.createElement("div");
  unfinishedLabel.className = "section-label";
  unfinishedLabel.textContent = `未厳選キャラ ${unfinishedRows.length}体`;
  div.appendChild(unfinishedLabel);

  function extractAccountCategory(accountText) {
    const value = String(accountText || "").replace(/\\s+/g, "");

    function pickToken(text) {
      const t = String(text || "");
      if (t.includes("サブサブ")) return "サブサブ";
      if (t.includes("サブ")) return "サブ";
      if (t.includes("メイン")) return "メイン";
      return "";
    }

    const beforeBracket = value.split(/[（(]/)[0] || "";
    if (beforeBracket.includes(":") || beforeBracket.includes("：")) {
      const parts = beforeBracket.split(/[:：]/).filter(Boolean);
      const right = parts.length > 1 ? pickToken(parts[parts.length - 1]) : "";
      if (right) return right;
      const left = parts.length > 0 ? pickToken(parts[0]) : "";
      if (left) return left;
    }

    const front = pickToken(beforeBracket);
    if (front) return front;

    const bracketMatch = value.match(/[（(](メイン|サブサブ|サブ)(?:[:：](メイン|サブサブ|サブ))?[）)]/);
    if (bracketMatch) {
      return bracketMatch[2] || bracketMatch[1] || "その他";
    }

    const any = pickToken(value);
    return any || "その他";
  }

  const grouped = new Map([
    ["メイン", []],
    ["サブ", []],
    ["サブサブ", []],
    ["その他", []],
  ]);

  unfinishedRows.forEach(row => {
    const category = extractAccountCategory(row.account || "");
    if (!grouped.has(category)) {
      grouped.set(category, []);
    }
    grouped.get(category).push(row);
  });

  const accountGrid = document.createElement("div");
  accountGrid.className = "unfinished-account-grid";

  const accountNames = ["メイン", "サブ", "サブサブ", "その他"]
    .filter(account => (grouped.get(account) || []).length > 0 || account !== "その他");

  let unfinishedIdx = 0;
  accountNames.forEach(account => {
    const accountBox = document.createElement("div");
    accountBox.className = "team-quest-box unfinished-account-box";

    const accountTitle = document.createElement("div");
    accountTitle.className = "team-quest-title";
    accountTitle.textContent = account;
    accountBox.appendChild(accountTitle);

    const rows = grouped.get(account) || [];
    if (rows.length === 0) {
      const empty = document.createElement("div");
      empty.className = "team-empty";
      empty.textContent = "未厳選キャラなし";
      accountBox.appendChild(empty);
    } else {
      rows.forEach(row => {
        accountBox.appendChild(makeRowCard(row, `u-${unfinishedIdx}`, data));
        unfinishedIdx += 1;
      });
    }

    accountGrid.appendChild(accountBox);
  });

  div.appendChild(accountGrid);
}

async function initPage() {
  await loadQuestOptions();
  await loadSavedPriorityQuests();
  setTimeout(loadSavedPriorityQuests, 200);

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
    suggest: list[str] = Query(default=[]),
    target: list[str] = Query(default=[]),
    mode: str = "auto",
):
    cleaned_fruits = []
    cleaned_targets = []

    mode = normalize_text(mode)
    if mode not in ["auto", "manual"]:
        mode = "auto"

    for i in range(3):
        f = normalize_text(fruit[i]) if i < len(fruit) else ""
        t = normalize_text(target[i]) if i < len(target) else ""
        if not t and i < len(suggest):
            t = normalize_text(suggest[i])

        cleaned_fruits.append(f)
        cleaned_targets.append(t)

    set_fruits(char_id, cleaned_fruits)
    clear_wakuwaku_cache(char_id)
    clear_wakuwaku_cache(char_id)

    rows = []
    for i in range(3):
        rows.append({
            "fruit": cleaned_fruits[i],
            "decision": "unselected",
            "mode": mode,
            "target": cleaned_targets[i],
            "manual_suggest": cleaned_targets[i],
        })

    set_fruit_decisions(char_id, rows)

    return {
        "status": "ok",
        "saved_fruits": cleaned_fruits,
        "saved_targets": cleaned_targets,
        "mode": mode,
    }

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

def safe_int_value(x):
    try:
        if x is None:
            return 0
        s = str(x).strip()
        if not s:
            return 0
        return int(float(s))
    except Exception:
        return 0

def make_local_char_id(name, attr, acc, num):
    return f"{name}||{attr}||{acc}||{num}"


def classify_fruit_category(fruits):
    fruits = normalize_three(fruits)
    filled = [normalize_text(x) for x in fruits if normalize_text(x)]

    if not filled:
        return "\u672a\u53b3\u9078"

    attack_types = set()

    for fruit in filled:
        if fruit.startswith("\u540c\u65cf"):
            attack_types.add("\u540c\u65cf")
        elif fruit.startswith("\u6483\u7a2e"):
            attack_types.add("\u6483\u7a2e")
        elif fruit.startswith("\u6226\u578b"):
            attack_types.add("\u6226\u578b")

    if len(attack_types) == 1:
        return list(attack_types)[0]

    support_count = sum(1 for fruit in filled if fruit in SUPPORT_FRUITS)
    if support_count >= 2:
        return "\u30b5\u30dd\u30fc\u30c8"

    return "\u305d\u306e\u4ed6"


def make_candidate_display_rows(char_id):
    current = normalize_three(cached_get_wakuwaku(char_id))

    return [
        {"slot_no": 1, "current": current[0], "target": "", "matched": False},
        {"slot_no": 2, "current": current[1], "target": "", "matched": False},
        {"slot_no": 3, "current": current[2], "target": "", "matched": False},
    ]


def get_team_candidates_for_quest(quest):
    try:
        data, _ = get_cached()
    except Exception:
        return []

    qx = data.get("quest_expanded")
    owned_df = data.get("owned")

    if qx is None or getattr(qx, "empty", True):
        return []

    if owned_df is None or getattr(owned_df, "empty", True):
        return []

    quest_col = "\u30af\u30a8\u30b9\u30c8\u540d"
    rank_col = "\u30e9\u30f3\u30af"
    char_col = "\u30ad\u30e3\u30e9\u540d"
    attr_col = "\u30ad\u30e3\u30e9\u5c5e\u6027"
    key_col = "\u5185\u90e8\u30ad\u30fc"

    account_cols = [
        "\u30e1\u30a4\u30f3",
        "\u30b5\u30d6",
        "\u30b5\u30d6\u30b5\u30d6",
    ]

    for col in [quest_col, rank_col, char_col]:
        if col not in qx.columns:
            return []

    if key_col not in owned_df.columns:
        return []

    owned_df = owned_df.copy()
    owned_df[key_col] = owned_df[key_col].map(normalize_text)

    out = []
    seen = set()
    target_quest = normalize_text(quest)

    for _, qrow in qx.iterrows():
        quest_name = normalize_text(qrow.get(quest_col, ""))
        if quest_name != target_quest:
            continue

        char_name = normalize_text(qrow.get(char_col, ""))
        rank = normalize_text(qrow.get(rank_col, ""))
        attr = normalize_text(qrow.get(attr_col, "")) if attr_col in qx.columns else ""

        if not char_name:
            continue

        base_name = normalize_name_for_match(char_name)

        search_keys = []
        if attr:
            search_keys.append(f"{char_name}||{attr}")
            search_keys.append(f"{base_name}||{attr}")

        search_keys.append(char_name)
        search_keys.append(base_name)

        search_keys = [x for x in dict.fromkeys(search_keys) if x]

        hit = owned_df[owned_df[key_col].isin(search_keys)]

        if hit.empty:
            continue

        for _, orow in hit.iterrows():
            for acc in account_cols:
                if acc not in owned_df.columns:
                    continue

                count = safe_int_value(orow.get(acc, 0))

                for num in range(1, count + 1):
                    char_id = make_local_char_id(char_name, attr, acc, num)
                    key = (char_id, quest_name, rank)

                    if key in seen:
                        continue
                    seen.add(key)

                    current_values = normalize_three(cached_get_wakuwaku(char_id))

                    out.append({
                        "char_id": char_id,
                        "title_name": char_name,
                        "account": acc,
                        "rank": rank,

                        "fruit_category": classify_fruit_category(current_values),
                        "display_rows": [
                            {"slot_no": 1, "current": current_values[0], "target": "", "matched": False},
                            {"slot_no": 2, "current": current_values[1], "target": "", "matched": False},
                            {"slot_no": 3, "current": current_values[2], "target": "", "matched": False},
                        ],

                        "tribe": normalize_text(qrow.get("\u7a2e\u65cf", "")),
                        "style": normalize_text(qrow.get("\u6226\u578b", "")),
                        "battle_type": normalize_text(qrow.get("\u6483\u7a2e", "")),

                        "quests": [quest_name],
                        "suitable_quests": [{
                            "quest": quest_name,
                            "rank": rank,
                            "display": f"{quest_name}({rank})" if rank else quest_name,
                        }],
                    })

    rank_order = {"S": 0, "A": 1, "B": 2}
    out.sort(key=lambda row: (
        rank_order.get(normalize_text(row.get("rank", "")), 9),
        normalize_text(row.get("title_name", "")),
        normalize_text(row.get("account", "")),
    ))

    return out

def ensure_team_row_current_fruits(team_rows):
    for row in team_rows:
        display_rows = row.get("display_rows", [])
        current_values = []

        for drow in display_rows:
            current_values.append(normalize_text(drow.get("current", "")))

        current_values = normalize_three(current_values)

        if any(current_values):
            continue

        char_id = normalize_text(row.get("char_id", ""))
        if not char_id:
            continue

        current_values = normalize_three(cached_get_wakuwaku(char_id))

        row["display_rows"] = [
            {"slot_no": 1, "current": current_values[0], "target": "", "matched": False},
            {"slot_no": 2, "current": current_values[1], "target": "", "matched": False},
            {"slot_no": 3, "current": current_values[2], "target": "", "matched": False},
        ]

        # ??3???????????????????
        row["is_complete"] = all(normalize_text(x) for x in current_values)

    return team_rows



def apply_team_optimizer_to_rows(team_rows):
    def get_current_from_row(row):
        current = []
        for drow in row.get("display_rows", []):
            current.append(normalize_text(drow.get("current", "")))
        current = normalize_three(current)

        if any(current):
            return current

        char_id = normalize_text(row.get("char_id", ""))
        if not char_id:
            return ["", "", ""]

        return normalize_three(cached_get_wakuwaku(char_id))

    def effect_key(row, fruit):
        fruit = normalize_text(fruit)

        if not fruit:
            return None

        if fruit in DUPLICATE_ALLOWED_FRUITS:
            return (fruit, "allowed", "")

        if fruit.startswith("??"):
            return (fruit, "tribe", normalize_text(row.get("tribe", "")))

        if fruit.startswith("??"):
            return (fruit, "style", normalize_text(row.get("style", "")))

        if fruit.startswith("??"):
            return (fruit, "battle_type", normalize_text(row.get("battle_type", "")))

        return (fruit, "other", "")

    def add_used_keys(row, fruits, used_keys):
        for fruit in normalize_three(fruits):
            fruit = normalize_text(fruit)
            if not fruit:
                continue

            key = effect_key(row, fruit)
            if key is not None and fruit not in DUPLICATE_ALLOWED_FRUITS:
                used_keys.add(key)

    def can_use(row, fruit, global_used, local_used):
        fruit = normalize_text(fruit)

        if not fruit:
            return False

        key = effect_key(row, fruit)

        if fruit in DUPLICATE_ALLOWED_FRUITS:
            return True

        if key in global_used:
            return False

        if key in local_used:
            return False

        return True

    clean_members = []
    for row in team_rows:
        clean_members.append({
            "tribe": normalize_text(row.get("tribe", "")),
            "style": normalize_text(row.get("style", "")),
            "battle_type": normalize_text(row.get("battle_type", "")),
        })

    combo, _score = optimizer_best_plan(clean_members)

    base_targets = []
    current_list = []

    for idx, row in enumerate(team_rows):
        planned = []
        if idx < len(combo):
            planned = list(combo[idx])

        base_targets.append(normalize_three(planned))
        current_list.append(get_current_from_row(row))

    attack_fill = []
    support_fill = []

    for cand_set in optimizer_build_candidates():
        for fruit in cand_set:
            fruit = normalize_text(fruit)
            if not fruit:
                continue

            if optimizer_is_attack_fruit(fruit):
                if fruit not in attack_fill:
                    attack_fill.append(fruit)
            else:
                if fruit not in support_fill:
                    support_fill.append(fruit)

    fill_candidates = attack_fill + support_fill

    global_used = set()
    fixed_indices = set()
    final_targets = {}

    # 1. ???3??????????????????
    for idx, row in enumerate(team_rows):
        current = normalize_three(current_list[idx])

        if all(normalize_text(x) for x in current):
            fixed_indices.add(idx)
            final_targets[idx] = current
            add_used_keys(row, current, global_used)

    # 2. ???????????????????????????
    for idx, row in enumerate(team_rows):
        current = normalize_three(current_list[idx])

        if idx in fixed_indices:
            target = normalize_three(final_targets[idx])
        else:
            base_target = normalize_three(base_targets[idx] if idx < len(base_targets) else [])
            target = ["", "", ""]
            local_used = set()

            # ???????????????????????????
            for i in range(3):
                fruit = normalize_text(current[i])
                if not fruit:
                    continue

                if can_use(row, fruit, global_used, local_used):
                    target[i] = fruit
                    key = effect_key(row, fruit)
                    if key is not None and fruit not in DUPLICATE_ALLOWED_FRUITS:
                        local_used.add(key)

            # ????????
            for i in range(3):
                if target[i]:
                    continue

                for fruit in base_target:
                    fruit = normalize_text(fruit)
                    if fruit in target and fruit not in DUPLICATE_ALLOWED_FRUITS:
                        continue

                    if can_use(row, fruit, global_used, local_used):
                        target[i] = fruit
                        key = effect_key(row, fruit)
                        if key is not None and fruit not in DUPLICATE_ALLOWED_FRUITS:
                            local_used.add(key)
                        break

            # ????????????????
            for i in range(3):
                if target[i]:
                    continue

                for fruit in fill_candidates:
                    fruit = normalize_text(fruit)
                    if fruit in target and fruit not in DUPLICATE_ALLOWED_FRUITS:
                        continue

                    if can_use(row, fruit, global_used, local_used):
                        target[i] = fruit
                        key = effect_key(row, fruit)
                        if key is not None and fruit not in DUPLICATE_ALLOWED_FRUITS:
                            local_used.add(key)
                        break

            target = normalize_three(target)
            add_used_keys(row, target, global_used)

        match_flags = unordered_match_flags(current, target)

        display_rows = []
        for i in range(3):
            display_rows.append({
                "slot_no": i + 1,
                "current": current[i],
                "target": target[i],
                "matched": match_flags[i],
            })

        row["display_rows"] = display_rows
        row["team_suggest"] = target
        row["ai_suggest"] = target
        row["target"] = target
        row["is_complete"] = is_complete_by_current_and_target(current, target)
        row["mode"] = optimizer_mode_from_suggest(target)
        row["mode_label"] = mode_label(row["mode"])

    return team_rows


@app.get("/refine/plan/view")
def refine_plan_view():
    priority_quests = get_priority_quests()
    frozen_plan = build_plan_view_rows()

    team_candidates_by_quest = {}
    team_rows_by_quest = {}

    for quest in priority_quests:
        team_candidates_by_quest[quest] = get_team_candidates_for_quest(quest)

        quest_rows = []
        seen_char_ids = set()

        for row in frozen_plan:
            if quest in row.get("quests", []):
                quest_rows.append(row)
                seen_char_ids.add(normalize_text(row.get("char_id", "")))
                continue

            for item in row.get("suitable_quests", []):
                if item and item.get("quest") == quest:
                    quest_rows.append(row)
                    seen_char_ids.add(normalize_text(row.get("char_id", "")))
                    break

        for candidate in team_candidates_by_quest[quest]:
            cid = normalize_text(candidate.get("char_id", ""))
            if not cid or cid in seen_char_ids:
                continue

            candidate_row = dict(candidate)
            candidate_row["display_rows"] = [
                {"slot_no": 1, "current": "", "target": "", "matched": False},
                {"slot_no": 2, "current": "", "target": "", "matched": False},
                {"slot_no": 3, "current": "", "target": "", "matched": False},
            ]

            candidate_row["tribe"] = normalize_text(
                candidate_row.get("tribe", "")
            )

            candidate_row["battle_type"] = normalize_text(
                candidate_row.get("battle_type", "")
            )

            candidate_row["style"] = normalize_text(
                candidate_row.get("style", "")
            )

            candidate_row["current_role"] = normalize_text(
                candidate_row.get("current_role", "")
            )

            candidate_row["suggest_role"] = normalize_text(
                candidate_row.get("suggest_role", "")
            )

            candidate_row["role_label"] = normalize_text(
                candidate_row.get("role_label", "")
            )

            candidate_row["role"] = normalize_text(
                candidate_row.get("role", "")
            )

            candidate_row["is_complete"] = False

            quest_rows.append(candidate_row)
            seen_char_ids.add(cid)

        team_rows = build_team_rows_for_quest(
            quest,
            quest_rows,
        )

        team_rows_by_quest[quest] = apply_team_optimizer_to_rows(team_rows)

    return {
        "priority_quests": priority_quests,
        "frozen_plan": frozen_plan,
        "team_candidates_by_quest": team_candidates_by_quest,
        "team_rows_by_quest": team_rows_by_quest,
        "recommend_balance_comment": "",
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

@app.get("/team/slot/state")
def team_slot_state(
    quest: str,
    slot_no: int,
    mode: str = "auto",
    char_id: str = "",
):
    set_team_slot_state(
        quest=quest,
        slot_no=slot_no,
        mode=mode,
        char_id=char_id,
    )

    return {
        "status": "ok",
    }

@app.get("/team/slot/get")
def team_slot_get(
    quest: str,
):
    rows = []

    for slot_no in range(1, 5):
        rows.append({
            "slot_no": slot_no,
            **get_team_slot_state(quest, slot_no),
        })

    return {
        "slots": rows
    }

