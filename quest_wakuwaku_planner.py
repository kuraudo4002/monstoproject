# -*- coding: utf-8 -*-

from planner_store import (
    get_priority_quests,
    get_quest_status,
    get_clear_history,
)


def build_planner_view(get_party_result_func):
    """
    get_party_result_func = service.get_party_result
    """
    quests = get_priority_quests()

    result = {
        "priority_quests": [],
    }

    for quest in quests:
        party_result = get_party_result_func(quest)
        status = get_quest_status(quest)
        clear_history = get_clear_history(quest)

        result["priority_quests"].append({
            "quest_name": quest,
            "status": status,
            "party": party_result.get("party", []),
            "role_counts": party_result.get("role_counts", {}),
            "balance_comment": party_result.get("balance_comment", ""),
            "clear_history": clear_history,
        })

    return result
