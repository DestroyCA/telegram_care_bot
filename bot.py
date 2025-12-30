import os
import json
import logging
import random
from datetime import datetime
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, Update
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web
import pytz

# ===================== ЛОГИРОВАНИЕ =====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден!")

PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"https://telegram-care-bot.onrender.com{WEBHOOK_PATH}"

DATA_FILE = "user_data.json"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

# ===================== ДАННЫЕ =====================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=4)

user_data = load_data()

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

# ===================== ХЕНДЛЕРЫ =====================
@dp.message(Command("start"))
async def cmd_start(message: Message):
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

@dp.message()
async def handle_messages(message: Message):
    chat_id = str(message.chat.id)
    text = message.text

    if text == "✨ Мне грустно":
        phrase = random.choice(ENCOURAGEMENT_PHRASES)
        await message.answer(phrase)

    elif text == "Добавить задачу ➕":
        await message.answer("Напиши текст задачи:")

    elif text == "Мои задачи 📋":
        await message.answer("Твои задачи:", reply_markup=get_tasks_keyboard(chat_id))

    elif text == "Очистить задачи 🗑":
        user_data[chat_id]["tasks"] = []
        save_data()
        await message.answer("Все задачи удалены ✅")

    elif text == "Помощь ℹ️":
        await message.answer(
            "Я могу:\n"
            "- Подбадривать тебя, когда грустно ✨\n"
            "- Вести твои задачи 📋\n"
            "- Напоминать о воде 💧\n"
            "- И просто радовать тебя ❤️"
        )
    else:
        await message.answer("Я не понимаю эту команду. Выбери из меню ⬇️", reply_markup=main_menu)

# ===================== WEBHOOK =====================
async def handle(request: web.Request):
    data = await request.json()
    update = Update(**data)
    await dp.update_handler(update)
    return web.Response()

async def on_startup(app):
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook установлен на {WEBHOOK_URL}")

async def on_cleanup(app):
    await bot.delete_webhook()

app = web.Application()
app.router.add_post(WEBHOOK_PATH, handle)
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

if __name__ == "__main__":
    web.run_app(app, port=PORT)
