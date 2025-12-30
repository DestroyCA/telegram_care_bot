import asyncio
import json
import os
from datetime import datetime, timedelta
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

WEBHOOK_URL = "https://telegram-care-bot.onrender.com/webhook"  # <- твой URL Render
DATA_FILE = "user_data.json"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

# ===================== ФРАЗЫ ПОДДЕРЖКИ =====================
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

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⬅️ Передумала / Назад")],
              [KeyboardButton(text="Главное меню 🏠")]],
    resize_keyboard=True,
    one_time_keyboard=True
)

def get_time_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton("5 мин", callback_data="time:5"),
                InlineKeyboardButton("10 мин", callback_data="time:10"),
                InlineKeyboardButton("15 мин", callback_data="time:15")
            ],
            [
                InlineKeyboardButton("30 мин", callback_data="time:30"),
                InlineKeyboardButton("1 час", callback_data="time:60"),
                InlineKeyboardButton("Без времени", callback_data="time:0")
            ]
        ]
    )

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

# ===================== ИНИЦИАЛИЗАЦИЯ =====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)
scheduler.start()

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

@dp.message(F.text == "Добавить задачу ➕")
async def start_add_task(message: Message, state: FSMContext):
    await message.answer("Напиши текст задачи:", reply_markup=cancel_keyboard)
    await state.set_state(AddTaskStates.waiting_for_task_text)

@dp.message(AddTaskStates.waiting_for_task_text)
async def add_task_text(message: Message, state: FSMContext):
    await state.update_data(task_text=message.text)
    await message.answer("Выбери, через сколько минут напомнить о задаче:", reply_markup=get_time_keyboard())
    await state.set_state(AddTaskStates.waiting_for_remind_time)

@dp.callback_query(F.data.startswith("time:"))
async def choose_time(call: CallbackQuery, state: FSMContext):
    chat_id = str(call.message.chat.id)
    data = await state.get_data()
    task_text = data.get("task_text")
    
    minutes = int(call.data.split(":")[1])
    remind_time = None
    if minutes > 0:
        remind_time = datetime.now(MOSCOW_TZ) + timedelta(minutes=minutes)
        scheduler.add_job(
            lambda: asyncio.create_task(
                bot.send_message(chat_id, f"Напоминание о задаче: {task_text} ⏰")
            ),
            "date",
            run_date=remind_time
        )
    
    user_data[chat_id]["tasks"].append({
        "text": task_text,
        "time": remind_time.isoformat() if remind_time else None
    })
    save_data()
    await call.message.edit_text(f"Задача '{task_text}' добавлена ✅", reply_markup=main_menu)
    await state.clear()

# ===================== WEBHOOK =====================
async def handle(request):
    json_data = await request.json()
    update = F.update_from_dict(json_data)
    await dp.update_router.feed_update(update)
    return web.Response(text="ok")

app = web.Application()
app.router.add_post("/webhook", handle)

# ===================== ЗАПУСК =====================
if __name__ == "__main__":
    # Устанавливаем webhook при старте
    asyncio.run(bot.set_webhook(WEBHOOK_URL))
    web.run_app(app, port=int(os.environ.get("PORT", 10000)))
