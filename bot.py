import asyncio
import json
import os
import random
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, Text
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    CallbackQuery,
    Update
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
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

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
if not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL не найден! Добавь его в переменные окружения Render.")

PORT = int(os.environ.get("PORT", 8000))
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

@dp.message(Text("✨ Мне грустно"))
async def sad(message: Message):
    phrase = random.choice(ENCOURAGEMENT_PHRASES)
    await message.answer(phrase)

@dp.message(Text("Добавить задачу ➕"))
async def add_task_start(message: Message, state: FSMContext):
    await state.set_state(AddTaskStates.waiting_for_task_text)
    await message.answer("Напиши текст задачи:", reply_markup=cancel_keyboard())

@dp.message(AddTaskStates.waiting_for_task_text)
async def add_task_text(message: Message, state: FSMContext):
    chat_id = str(message.chat.id)
    task_text = message.text
    await state.update_data(task_text=task_text)
    await state.set_state(AddTaskStates.waiting_for_remind_time)
    await message.answer("Когда напомнить? (например 18:30 или 'без времени')", reply_markup=cancel_keyboard())

@dp.message(AddTaskStates.waiting_for_remind_time)
async def add_task_time(message: Message, state: FSMContext):
    chat_id = str(message.chat.id)
    data = await state.get_data()
    task_text = data.get("task_text")
    task_time = message.text if message.text != "без времени" else None
    if chat_id not in user_data:
        user_data[chat_id] = {"tasks": [], "water_count": 0, "last_greeting": None}
    user_data[chat_id]["tasks"].append({"text": task_text, "time": task_time})
    save_data()
    await state.clear()
    await message.answer("Задача добавлена ✅", reply_markup=main_menu)

@dp.message(Text("Мои задачи 📋"))
async def list_tasks(message: Message):
    chat_id = str(message.chat.id)
    if chat_id not in user_data or not user_data[chat_id]["tasks"]:
        await message.answer("У тебя пока нет задач 😔", reply_markup=main_menu)
        return
    await message.answer("Вот твои задачи:", reply_markup=get_tasks_keyboard(chat_id))

@dp.callback_query(lambda c: c.data and c.data.startswith("done:"))
async def mark_done(callback: CallbackQuery):
    chat_id = str(callback.message.chat.id)
    index = int(callback.data.split(":")[1])
    task = user_data[chat_id]["tasks"].pop(index)
    save_data()
    await callback.message.edit_text(f"✅ Задача выполнена: {task['text']}", reply_markup=get_tasks_keyboard(chat_id))

@dp.callback_query(lambda c: c.data and c.data.startswith("delete:"))
async def delete_task(callback: CallbackQuery):
    chat_id = str(callback.message.chat.id)
    index = int(callback.data.split(":")[1])
    task = user_data[chat_id]["tasks"].pop(index)
    save_data()
    await callback.message.edit_text(f"❌ Задача удалена: {task['text']}", reply_markup=get_tasks_keyboard(chat_id))

@dp.message(Text("Очистить задачи 🗑"))
async def clear_tasks(message: Message):
    chat_id = str(message.chat.id)
    user_data[chat_id]["tasks"] = []
    save_data()
    await message.answer("Все задачи удалены 🗑", reply_markup=main_menu)

# ===================== WEBHOOK =====================
async def handle(request):
    data = await request.json()
    update = Update(**data)
    await dp.feed_update(update)
    return web.Response()

async def on_startup(app: web.Application):
    await bot.delete_webhook()
    await bot.set_webhook(WEBHOOK_URL)
    scheduler.start()

# ===================== ТОЧКА ВХОДА =====================
app = web.Application()
app.router.add_post("/webhook", handle)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, port=PORT)
