"""Телеграм-бот для составления расписания на неделю."""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

import storage
from scheduler import (
    DAY_SHORT,
    Settings,
    build_schedule,
    fmt_hours,
    fmt_time,
    format_schedule,
    parse_activities,
)

logging.basicConfig(level=logging.INFO)

HELP_TEXT = (
    "Привет! Я составляю расписание на неделю.\n\n"
    "Пришли список занятий — каждое с новой строки: название и количество "
    "часов в неделю. Например:\n\n"
    "<code>Программирование 10\n"
    "Английский 5\n"
    "Спорт 4.5</code>\n\n"
    "По будням я планирую время после 17:00, по выходным — с 11:00 "
    "(всё это можно поменять в /settings).\n\n"
    "Команды:\n"
    "/settings — настройки расписания\n"
    "/help — эта справка"
)


# ---------- клавиатуры ----------

def settings_keyboard(s: Settings) -> InlineKeyboardMarkup:
    def adjust_row(label: str, key: str) -> list[InlineKeyboardButton]:
        return [
            InlineKeyboardButton(text="−", callback_data=f"st:{key}:-"),
            InlineKeyboardButton(text=label, callback_data="st:noop"),
            InlineKeyboardButton(text="+", callback_data=f"st:{key}:+"),
        ]

    rows = [
        adjust_row(f"Будни с {fmt_time(s.weekday_start)}", "ws"),
        adjust_row(f"Выходные с {fmt_time(s.weekend_start)}", "we"),
        adjust_row(f"Конец дня {fmt_time(s.day_end)}", "de"),
        adjust_row(f"Макс. блок {fmt_hours(s.max_block)}", "mb"),
        adjust_row(f"Перерыв {s.break_min} мин", "br"),
        [
            InlineKeyboardButton(
                text=("✅ Выходные используются" if s.weekends_enabled
                      else "🚫 Выходные не используются"),
                callback_data="st:wk:t",
            )
        ],
        [
            InlineKeyboardButton(
                text=("🌴 " if i in s.days_off else "") + DAY_SHORT[i],
                callback_data=f"st:d:{i}",
            )
            for i in range(7)
        ],
        [InlineKeyboardButton(text="🔄 Пересоставить расписание", callback_data="rebuild")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Пересоставить", callback_data="rebuild"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
            ]
        ]
    )


SETTINGS_TEXT = (
    "⚙️ <b>Настройки</b>\n\n"
    "«−» и «+» меняют значение. Нижний ряд — дни отдыха (🌴 — день выключен).\n"
    "После изменений нажми «Пересоставить расписание»."
)


# ---------- обработчики ----------

dp = Dispatcher()


@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT)


@dp.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    s = storage.get_settings(message.from_user.id)
    await message.answer(SETTINGS_TEXT, reply_markup=settings_keyboard(s))


@dp.message(F.text & ~F.text.startswith("/"))
async def handle_activities(message: Message) -> None:
    activities, errors = parse_activities(message.text)
    if not activities:
        await message.answer(
            "Не понял ни одной строки 🤔\n\n"
            "Формат: название занятия и часы в неделю, каждое с новой строки:\n"
            "<code>Программирование 10\nАнглийский 5</code>"
        )
        return
    storage.save_last_input(message.from_user.id, message.text)
    s = storage.get_settings(message.from_user.id)
    schedule, warnings = build_schedule(activities, s)
    if errors:
        warnings.append("Не разобрал строки: " + "; ".join(f"«{e}»" for e in errors))
    await message.answer(
        format_schedule(schedule, warnings), reply_markup=schedule_keyboard()
    )


STEPS = {
    # key: (атрибут, шаг в минутах, минимум, максимум)
    "ws": ("weekday_start", 30, 6 * 60, 23 * 60),
    "we": ("weekend_start", 30, 6 * 60, 23 * 60),
    "de": ("day_end", 30, 7 * 60, 24 * 60),
    "mb": ("max_block", 30, 30, 300),
    "br": ("break_min", 15, 0, 60),
}


@dp.callback_query(F.data.startswith("st:"))
async def handle_settings_cb(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    action = parts[1]
    s = storage.get_settings(cb.from_user.id)

    if action == "noop":
        await cb.answer()
        return
    if action == "wk":
        s.weekends_enabled = not s.weekends_enabled
    elif action == "d":
        day = int(parts[2])
        if day in s.days_off:
            s.days_off.remove(day)
        else:
            s.days_off.append(day)
    elif action in STEPS:
        attr, step, lo, hi = STEPS[action]
        delta = step if parts[2] == "+" else -step
        setattr(s, attr, max(lo, min(hi, getattr(s, attr) + delta)))
        # конец дня не должен наезжать на начало
        if s.day_end <= min(s.weekday_start, s.weekend_start):
            await cb.answer("Конец дня должен быть позже начала", show_alert=True)
            return

    storage.save_settings(cb.from_user.id, s)
    await cb.message.edit_reply_markup(reply_markup=settings_keyboard(s))
    await cb.answer()


@dp.callback_query(F.data == "settings")
async def handle_open_settings(cb: CallbackQuery) -> None:
    s = storage.get_settings(cb.from_user.id)
    await cb.message.answer(SETTINGS_TEXT, reply_markup=settings_keyboard(s))
    await cb.answer()


@dp.callback_query(F.data == "rebuild")
async def handle_rebuild(cb: CallbackQuery) -> None:
    last = storage.get_last_input(cb.from_user.id)
    if not last:
        await cb.answer("Сначала пришли список занятий", show_alert=True)
        return
    activities, _ = parse_activities(last)
    s = storage.get_settings(cb.from_user.id)
    schedule, warnings = build_schedule(activities, s)
    await cb.message.answer(
        format_schedule(schedule, warnings), reply_markup=schedule_keyboard()
    )
    await cb.answer()


async def main() -> None:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit(
            "Не найден BOT_TOKEN. Создай файл .env со строкой BOT_TOKEN=<токен от @BotFather>"
        )
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
