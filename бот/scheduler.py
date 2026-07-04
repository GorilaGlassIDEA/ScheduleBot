"""Логика распределения часов по неделе."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

SLOT = 30  # минимальная единица планирования, минут

DAY_NAMES = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]
DAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


@dataclass
class Settings:
    weekday_start: int = 17 * 60   # будни: с какого времени планировать (мин от полуночи)
    weekend_start: int = 11 * 60   # выходные: с какого времени
    day_end: int = 23 * 60         # до какого времени планировать
    weekends_enabled: bool = True  # использовать ли выходные
    max_block: int = 120           # макс. непрерывный блок одного занятия, мин
    break_min: int = 15            # перерыв между блоками, мин
    days_off: list[int] = field(default_factory=list)  # дни отдыха, 0=Пн .. 6=Вс

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        s = cls()
        for k, v in d.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s


@dataclass
class Activity:
    name: str
    hours: float


@dataclass
class Block:
    start: int  # минут от полуночи
    end: int
    name: str


def fmt_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def fmt_hours(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if m == 0:
        return f"{h} ч"
    if h == 0:
        return f"{m} мин"
    return f"{h} ч {m} мин"


def parse_activities(text: str) -> tuple[list[Activity], list[str]]:
    """Разбирает строки вида «Название 10», «Название — 2.5 ч» и т.п.

    Возвращает (занятия, ошибки по строкам)."""
    activities: list[Activity] = []
    errors: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        tokens = re.split(r"[\s—–:,-]+(?=[\d\s])|\s+", line)
        tokens = [t for t in tokens if t]
        hours = None
        idx = None
        for i in range(len(tokens) - 1, -1, -1):
            t = tokens[i].replace(",", ".").rstrip("чЧ.")
            try:
                hours = float(t)
                idx = i
                break
            except ValueError:
                continue
        name = " ".join(tokens[:idx]).strip(" -—–:") if idx else ""
        if hours is None or not name:
            errors.append(line)
            continue
        if not (0 < hours <= 100):
            errors.append(f"{line} (часы должны быть от 0.5 до 100)")
            continue
        activities.append(Activity(name=name, hours=hours))
    return activities, errors


def _day_windows(s: Settings) -> list[tuple[int, int, int]]:
    """Активные дни недели: (индекс дня, начало, конец) в минутах."""
    days = []
    for i in range(7):
        if i in s.days_off:
            continue
        if i >= 5 and not s.weekends_enabled:
            continue
        start = s.weekday_start if i < 5 else s.weekend_start
        if s.day_end - start >= SLOT:
            days.append((i, start, s.day_end))
    return days


def build_schedule(
    activities: list[Activity], s: Settings
) -> tuple[dict[int, list[Block]], list[str]]:
    """Распределяет занятия по неделе.

    Возвращает (расписание: день -> блоки, предупреждения)."""
    warnings: list[str] = []
    days = _day_windows(s)
    if not days:
        return {}, ["Нет доступных дней: проверь настройки (дни отдыха, время начала и конца)."]

    # округляем часы каждого занятия до слотов по 30 минут
    remaining = {
        a.name: max(1, round(a.hours * 60 / SLOT)) * SLOT for a in activities
    }
    required = sum(remaining.values())
    capacity = sum(end - start for _, start, end in days)

    if required > capacity:
        factor = capacity / required
        for k in remaining:
            remaining[k] = max(SLOT, int(remaining[k] * factor) // SLOT * SLOT)
        warnings.append(
            f"Запрошено {fmt_hours(required)}, а свободно всего {fmt_hours(capacity)} — "
            f"часы урезаны пропорционально."
        )

    # цель на каждый день — пропорционально его вместимости (метод наибольших остатков)
    req_slots = sum(remaining.values()) // SLOT
    cap_slots = [(end - start) // SLOT for _, start, end in days]
    total_cap_slots = sum(cap_slots)
    exact = [req_slots * c / total_cap_slots for c in cap_slots]
    targets = [int(x) for x in exact]
    deficit = req_slots - sum(targets)
    order = sorted(range(len(days)), key=lambda i: exact[i] - targets[i], reverse=True)
    for i in order:
        if deficit <= 0:
            break
        if targets[i] < cap_slots[i]:
            targets[i] += 1
            deficit -= 1

    schedule: dict[int, list[Block]] = {}
    cursors: dict[int, int] = {}

    def fill_day(day_idx: int, start: int, end: int, target_min: int | None) -> None:
        blocks = schedule.setdefault(day_idx, [])
        cursor = cursors.get(day_idx, start)
        placed = sum(b.end - b.start for b in blocks)
        last_name = blocks[-1].name if blocks else None
        while cursor + SLOT <= end and any(v > 0 for v in remaining.values()):
            if target_min is not None and placed >= target_min:
                break
            # берём занятие с наибольшим остатком, но не повторяем предыдущее подряд
            cands = sorted(
                (kv for kv in remaining.items() if kv[1] > 0),
                key=lambda kv: -kv[1],
            )
            pick = next((kv for kv in cands if kv[0] != last_name), cands[0])
            name, rem = pick
            block = min(rem, s.max_block, end - cursor)
            if target_min is not None:
                block = min(block, target_min - placed)
            block = block // SLOT * SLOT
            if block < SLOT:
                break
            blocks.append(Block(cursor, cursor + block, name))
            remaining[name] -= block
            placed += block
            last_name = name
            cursor = cursor + block + s.break_min
        cursors[day_idx] = cursor

    # первый проход — по дневным целям, второй — добираем то, что не влезло из-за перерывов
    for (day_idx, start, end), target in zip(days, targets):
        fill_day(day_idx, start, end, target * SLOT)
    if any(v > 0 for v in remaining.values()):
        for day_idx, start, end in days:
            fill_day(day_idx, start, end, None)

    unplaced = {k: v for k, v in remaining.items() if v > 0}
    if unplaced:
        details = ", ".join(f"{k} — {fmt_hours(v)}" for k, v in unplaced.items())
        warnings.append(
            f"Не поместилось: {details}. Попробуй увеличить окно времени или уменьшить перерывы."
        )
    return schedule, warnings


def format_schedule(schedule: dict[int, list[Block]], warnings: list[str]) -> str:
    lines = ["🗓 <b>Расписание на неделю</b>", ""]
    totals: dict[str, int] = {}
    for day_idx in range(7):
        blocks = schedule.get(day_idx)
        if not blocks:
            continue
        lines.append(f"<b>{DAY_NAMES[day_idx]}</b>")
        for b in blocks:
            lines.append(f"  {fmt_time(b.start)}–{fmt_time(b.end)} · {b.name}")
            totals[b.name] = totals.get(b.name, 0) + (b.end - b.start)
        lines.append("")
    if totals:
        lines.append("<b>Итого:</b>")
        for name, minutes in totals.items():
            lines.append(f"  {name} — {fmt_hours(minutes)}")
    for w in warnings:
        lines.append("")
        lines.append(f"⚠️ {w}")
    return "\n".join(lines).strip()
