import asyncio
import json
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
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
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8000))
DATA_FILE = "user_data.json"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

if not BOT_TOKEN or not WEBHOOK_URL:
    raise RuntimeError("Не задан BOT_TOKEN или WEBHOOK_URL!")

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

# ===================== WEBHOOK =====================
async def handle_webhook(request: web.Request):
    try:
        data = await request.json()
        from aiogram.types import Update
        update = Update(**data)
        await dp.feed_update(update)
    except Exception as e:
        logger.error(f"Ошибка при обработке update: {e}")
    return web.Response(text="OK")

# ===================== ПЛАНИРОВЩИК =====================
async def scheduled_job():
    logger.info("Задача APScheduler выполнена!")

scheduler.add_job(scheduled_job, IntervalTrigger(seconds=60))

# ===================== СТАРТ И WEBHOOK =====================
async def on_startup(app: web.Application):
    await bot.delete_webhook()
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен: {WEBHOOK_URL}")
    scheduler.start()

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()

# ===================== ТОЧКА ВХОДА =====================
app = web.Application()
app.router.add_post("/webhook", handle_webhook)
app.on_startup.append(on_startup)
app.on_cleanup.append(on_shutdown)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
