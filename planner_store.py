# -*- coding: utf-8 -*-

import json
import os

FILE_PATH = "planner_data.json"


def load_data():
    if not os.path.exists(FILE_PATH):
        return {
            "priority_quests": [],
            "quest_status": {},
            "clear_history": {},
        }

    try:
        with open(FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except:
        return {
            "priority_quests": [],
            "quest_status": {},
            "clear_history": {},
        }

    if "priority_quests" not in data:
        data["priority_quests"] = []
    if "quest_status" not in data:
        data["quest_status"] = {}
    if "clear_history" not in data:
        data["clear_history"] = {}

    return data


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


def get_quest_status(quest_name):
    data = load_data()
    return data.get("quest_status", {}).get(quest_name, {
        "refine_done": False,
        "cleared": False,
    })


def set_refine_done(quest_name, value: bool):
    data = load_data()
    if "quest_status" not in data:
        data["quest_status"] = {}
    if quest_name not in data["quest_status"]:
        data["quest_status"][quest_name] = {
            "refine_done": False,
            "cleared": False,
        }

    data["quest_status"][quest_name]["refine_done"] = bool(value)
    save_data(data)


def set_cleared(quest_name, value: bool):
    data = load_data()
    if "quest_status" not in data:
        data["quest_status"] = {}
    if quest_name not in data["quest_status"]:
        data["quest_status"][quest_name] = {
            "refine_done": False,
            "cleared": False,
        }

    data["quest_status"][quest_name]["cleared"] = bool(value)
    save_data(data)


def save_clear_history(quest_name, party_rows):
    data = load_data()
    if "clear_history" not in data:
        data["clear_history"] = {}

    data["clear_history"][quest_name] = {
        "party": party_rows
    }
    save_data(data)


def get_clear_history(quest_name):
    data = load_data()
    return data.get("clear_history", {}).get(quest_name, {})
