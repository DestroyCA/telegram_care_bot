import asyncio
import json
import os
import random
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from aiohttp import web

# ===================== ЛОГИРОВАНИЕ =====================
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = RotatingFileHandler("bot.log", maxBytes=10*1024*1024, backupCount=5)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# ===================== КОНСТАНТЫ =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден! Добавь его в переменные окружения Render.")

PORT = int(os.environ.get("PORT", 8000))  # Render предоставляет порт через переменные окружения
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://telegram-care-bot.onrender.com{WEBHOOK_PATH}"  # твой URL на Render

DATA_FILE = "user_data.json"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

ENCOURAGEMENT_PHRASES = [
    "Ты — самое прекрасное, что есть в этом мире! 💖",
    "Сегодня будет отличный день, я верю в тебя! ☀️",
    "Ты сильнее, чем думаешь. Всё получится! 💪",
    "Твоя улыбка делает мир ярче! 😊",
    "Даже в пасмурный день ты — как лучик солнца! 🌤→☀️",
    "Ты заслуживаешь счастья и любви! ❤️",
    "Каждый день — новый шанс стать счастливее. Сегодня твой день! ✨",
    "Ты — уникальна, и это прекрасно! 🌟"
]

# ===================== ЗАГРУЗКА/СОХРАНЕНИЕ ДАННЫХ =====================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=4)

user_data = load_data()

# ===================== FSM =====================
class AddTaskStates(StatesGroup):
    waiting_for_task_text = State()
    waiting_for_remind_time = State()
    waiting_for_advance_reminder = State()

# ===================== КЛАВИАТУРЫ =====================
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✨ Мне грустно")],
        [KeyboardButton(text="Добавить задачу ➕")],
        [KeyboardButton(text="Мои задачи 📋")],
        [KeyboardButton(text="Очистить задачи 🗑")],
        [KeyboardButton(text="Помощь ℹ️")]
    ],
    resize_keyboard=True
)

def cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Передумала / Назад")],
                  [KeyboardButton(text="Главное меню 🏠")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_advance_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="за 5 минут", callback_data="advance:5"),
         InlineKeyboardButton(text="за 10 минут", callback_data="advance:10")],
        [InlineKeyboardButton(text="за 30 минут", callback_data="advance:30"),
         InlineKeyboardButton(text="за 1 час", callback_data="advance:60")],
        [InlineKeyboardButton(text="без предварительного", callback_data="advance:0")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="advance:back")]
    ])

def get_tasks_keyboard(chat_id: str):
    tasks = user_data.get(chat_id, {}).get("tasks", [])
    buttons = []
    for i, task in enumerate(tasks):
        buttons.append([
            InlineKeyboardButton(text=f"{task['text']} ({task['time'] or 'без времени'})", callback_data=f"keep:{i}"),
            InlineKeyboardButton(text="✅ Готово", callback_data=f"done:{i}"),
            InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete:{i}")
        ])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="menu:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_water_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да ✅", callback_data="water:yes")],
        [InlineKeyboardButton(text="Нет ❌", callback_data="water:no")],
        [InlineKeyboardButton(text="Главное меню 🏠", callback_data="water:menu")]
    ])

# ===================== ИНИЦИАЛИЗАЦИЯ =====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)

# ===================== ХЕНДЛЕРЫ =====================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    chat_id = str(message.chat.id)
    if chat_id not in user_data:
        user_data[chat_id] = {"tasks": [], "water_count": 0, "last_greeting": None}
        save_data()
    await message.answer(
        "Привет, Кись! ☀️💕\n\n"
        "Я здесь, чтобы заботиться о тебе каждый день 🥰\n\n"
        "Выбери в меню ниже, что хочешь сделать ↓",
        reply_markup=main_menu
    )

# ===================== WEBHOOK HANDLER =====================
async def handle(request):
    try:
        update = await request.json()
        await dp.update_manager.feed_update(update)  # aiogram 3.x
    except Exception as e:
        logger.exception(e)
    return web.Response()

# ===================== MAIN =====================
async def on_startup():
    # запускаем scheduler внутри async функции
    scheduler.start()
    # устанавливаем webhook
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    print("Webhook set to:", WEBHOOK_URL)
    print("Scheduler started!")

async def main():
    await on_startup()
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Listening on port {PORT}...")
    # держим процесс живым
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
