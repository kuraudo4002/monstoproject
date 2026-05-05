# -*- coding: utf-8 -*-

import json
import os

FILE_PATH = "refine_plan_data.json"


def default_data():
    return {
        "priority_quests": [],
        "frozen_plan": [],
        "quest_status": {},
        "clear_history": {},
        "fruit_decisions": {},
    }


def load_data():
    if not os.path.exists(FILE_PATH):
        return default_data()

    try:
        with open(FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return default_data()

    base = default_data()
    base.update(data)
    return base


def save_data(data):
    with open(FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_priority_quests():
    data = load_data()
    return data.get("priority_quests", [])


def set_priority_quests(quests):
    data = load_data()
    data["priority_quests"] = quests[:3]
    save_data(data)


def get_frozen_plan():
    data = load_data()
    return data.get("frozen_plan", [])


def set_frozen_plan(plan_rows):
    data = load_data()
    data["frozen_plan"] = plan_rows
    save_data(data)


def clear_frozen_plan():
    data = load_data()
    data["frozen_plan"] = []
    data["fruit_decisions"] = {}
    save_data(data)


def get_fruit_decisions(char_id):
    data = load_data()
    return data.get("fruit_decisions", {}).get(char_id, [])


def set_fruit_decisions(char_id, decisions):
    data = load_data()
    if "fruit_decisions" not in data:
        data["fruit_decisions"] = {}
    data["fruit_decisions"][char_id] = decisions
    save_data(data)


def get_quest_status(quest_name):
    data = load_data()
    return data.get("quest_status", {}).get(quest_name, {
        "refine_done": False,
        "cleared": False,
    })


def set_refine_done(quest_name, value: bool):
    data = load_data()
    if quest_name not in data["quest_status"]:
        data["quest_status"][quest_name] = {
            "refine_done": False,
            "cleared": False,
        }

    data["quest_status"][quest_name]["refine_done"] = bool(value)
    save_data(data)


def set_cleared(quest_name, value: bool):
    data = load_data()
    if quest_name not in data["quest_status"]:
        data["quest_status"][quest_name] = {
            "refine_done": False,
            "cleared": False,
        }

    data["quest_status"][quest_name]["cleared"] = bool(value)
    save_data(data)


def save_clear_history(quest_name, party_rows):
    data = load_data()
    data["clear_history"][quest_name] = {
        "party": party_rows
    }
    save_data(data)


def get_clear_history(quest_name):
    data = load_data()
    return data.get("clear_history", {}).get(quest_name, {})
