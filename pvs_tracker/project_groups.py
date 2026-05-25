"""Группы проектов (как в PVS_Sonar_WebHook_FastAPI)."""

from __future__ import annotations

# id → отображаемое имя группы
GROUP_CHOICES: list[tuple[int, str]] = [
    (1, "QA"),
    (2, "QD"),
    (3, "QF"),
    (4, "QG"),
    (5, "QS"),
    (6, "QW"),
    (7, "Other_Projects"),
]

GROUP_ID_BY_NAME: dict[str, int] = {name: gid for gid, name in GROUP_CHOICES}

# Префиксы SonarQube Project Key при смене группы (логика из index.html)
GROUP_KEY_PREFIX: dict[str, str] = {
    "QA": "qa.",
    "QD": "qd.",
    "QF": "qf.",
    "QG": "qg.",
    "QS": "qs.",
    "QW": "qw.",
    "Other_Projects": "",
}


def group_name_from_id(group_id: int | str | None) -> str:
    if group_id is None or group_id == "":
        return "Ungrouped"
    try:
        gid = int(group_id)
    except (TypeError, ValueError):
        return str(group_id)
    for item_id, name in GROUP_CHOICES:
        if item_id == gid:
            return name
    return "Ungrouped"


def group_id_from_name(group_name: str | None) -> int:
    if not group_name:
        return 7
    return GROUP_ID_BY_NAME.get(group_name, 7)
