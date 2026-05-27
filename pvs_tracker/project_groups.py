"""Группы проектов. Читаются из БД с кэшированием."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

from sqlmodel import Session, select

from pvs_tracker.db import engine
from pvs_tracker.models import ProjectGroup

# Старые константы – fallback, если таблица ProjectGroup пуста
FALLBACK_GROUP_CHOICES: list[tuple[int, str]] = [
    (1, "QA"),
    (2, "QD"),
    (3, "QF"),
    (4, "QG"),
    (5, "QS"),
    (6, "QW"),
    (7, "Other_Projects"),
    (8, "Ungrouped"),
]
FALLBACK_GROUP_ID_BY_NAME: dict[str, int] = {name: gid for gid, name in FALLBACK_GROUP_CHOICES}


def _get_groups_from_db(session: Session) -> list[tuple[int, str]]:
    """Загружает группы из БД, сортирует по display_order."""
    groups = session.exec(
        select(ProjectGroup).order_by(ProjectGroup.display_order, ProjectGroup.name)
    ).all()
    return [(g.id, g.name) for g in groups]


def get_group_choices(session: Session) -> list[tuple[int, str]]:
    """Возвращает список (id, название) для выпадающего списка групп."""
    choices = _get_groups_from_db(session)
    if choices:
        return choices
    # Если таблица пуста (старая БД), возвращаем fallback
    return FALLBACK_GROUP_CHOICES


def get_group_name_by_id(session: Session, group_id: int) -> str:
    """По id группы возвращает её название."""
    # Сначала пробуем достать из БД
    group = session.get(ProjectGroup, group_id)
    if group:
        return group.name
    # Если не найден, смотрим в fallback
    for gid, name in FALLBACK_GROUP_CHOICES:
        if gid == group_id:
            return name
    return "Ungrouped"


from sqlalchemy import func
def get_group_id_by_name(session: Session, group_name: Optional[str]) -> int:
    if not group_name:
        return 7
    clean_name = group_name.strip()
    # Поиск точного совпадения
    group = session.exec(select(ProjectGroup).where(ProjectGroup.name == clean_name)).first()
    if group:
        return group.id
    # Поиск без учёта регистра (на случай, если в БД имя с другим регистром)
    group = session.exec(select(ProjectGroup).where(func.lower(ProjectGroup.name) == func.lower(clean_name))).first()
    if group:
        return group.id
    # Fallback: возвращаем id группы "Ungrouped", если она есть, иначе 7
    ungrouped = session.exec(select(ProjectGroup).where(ProjectGroup.name == "Ungrouped")).first()
    if ungrouped:
        return ungrouped.id
    return 7


# Функции для обратной совместимости (используются в старых местах, где нет session)
def group_name_from_id(group_id: int | str | None) -> str:
    """Старая функция – использует fallback. Для новых мест используйте get_group_name_by_id."""
    if group_id is None or group_id == "":
        return "Ungrouped"
    try:
        gid = int(group_id)
    except (TypeError, ValueError):
        return str(group_id)
    for item_id, name in FALLBACK_GROUP_CHOICES:
        if item_id == gid:
            return name
    return "Ungrouped"


def group_id_from_name(group_name: str | None) -> int:
    """Старая функция – использует fallback."""
    if not group_name:
        return 7
    return FALLBACK_GROUP_ID_BY_NAME.get(group_name, 7)


# Для обратной совместимости со старым кодом
GROUP_CHOICES = FALLBACK_GROUP_CHOICES