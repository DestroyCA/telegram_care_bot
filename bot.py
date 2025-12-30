import asyncio
import json
import os
import random
from datetime import datetime, timedelta
import logging
from logging.handlers import RotatingFileHandler
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz
from aiohttp import web
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# ===================== ЛОГИРОВАНИЕ =====================
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

file_handler = RotatingFileHandler("bot.log", maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# ===================== КОНСТАНТЫ =====================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения!")

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
if not WEBHOOK_URL:
    raise ValueError("WEBHOOK_URL не задан! Добавьте в Render → Environment: https://telegram-care-bot.onrender.com/webhook")

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "super-secret-care-bot-token-2025")
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
    "Ты не одна — я всегда рядом! 🤗",
    "Маленькие шаги ведут к большим победам. Ты на правильном пути! 🛣️",
    "Ты — уникальна, и это прекрасно! 🌟"
]

# ===================== ЗАГРУЗКА/СОХРАНЕНИЕ ДАННЫХ =====================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки данных: {e}")
    return {}

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения данных: {e}")

user_data = load_data()

# ===================== FSM =====================
class AddTaskStates(StatesGroup):
    waiting_for_task_text = State()
    waiting_for_remind_time = State()
    waiting_for_advance_reminder = State()

# ===================== КЛАВИАТУРЫ =====================
main_menu = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="Добавить задачу ➕")],
        [types.KeyboardButton(text="Мои задачи 📋")],
        [types.KeyboardButton(text="Очистить задачи 🗑")],
        [types.KeyboardButton(text="Помощь ℹ️")],
        [types.KeyboardButton(text="✨ Мне грустно")]
    ],
    resize_keyboard=True
)

def get_tasks_keyboard(chat_id: str):
    tasks = user_data.get(chat_id, {}).get("tasks", [])
    buttons = []
    for i, task in enumerate(tasks):
        time_str = task['time'] if task['time'] else 'без времени'
        buttons.append([
            types.InlineKeyboardButton(text=f"{task['text']} ({time_str})", callback_data=f"keep:{i}"),
            types.InlineKeyboardButton(text="✅ Готово", callback_data=f"done:{i}"),
            types.InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete:{i}")
        ])
    buttons.append([types.InlineKeyboardButton(text="Назад в меню", callback_data="menu:back")])
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)

def get_advance_keyboard():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="за 5 минут", callback_data="advance:5"),
            types.InlineKeyboardButton(text="за 10 минут", callback_data="advance:10")
        ],
        [
            types.InlineKeyboardButton(text="за 30 минут", callback_data="advance:30"),
            types.InlineKeyboardButton(text="за 1 час", callback_data="advance:60")
        ],
        [types.InlineKeyboardButton(text="без предварительного", callback_data="advance:0")]
    ])

def get_water_keyboard():
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Да ✅", callback_data="water:yes")],
        [types.InlineKeyboardButton(text="Нет ❌", callback_data="water:no")],
        [types.InlineKeyboardButton(text="Главное меню 🏠", callback_data="water:menu")]
    ])

# ===================== ИНИЦИАЛИЗАЦИЯ =====================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)

# ===================== ХЕНДЛЕРЫ =====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    chat_id = str(message.chat.id)
    if chat_id not in user_data:
        user_data[chat_id] = {"tasks": [], "water_count": 0, "last_greeting": None}
        save_data(user_data)
    await message.answer("Привет, Кись! ☀️💕\nВыбирай в меню ниже:", reply_markup=main_menu)

# ======= Добавление задач =======
@dp.message(F.text == "Добавить задачу ➕")
async def add_task(message: types.Message, state: FSMContext):
    await message.answer("Напиши текст задачи:")
    await state.set_state(AddTaskStates.waiting_for_task_text)

@dp.message(AddTaskStates.waiting_for_task_text)
async def task_text_received(message: types.Message, state: FSMContext):
    await state.update_data(task_text=message.text)
    await message.answer("На какое время напомнить? (ЧЧ:ММ) или напиши «без времени»")
    await state.set_state(AddTaskStates.waiting_for_remind_time)

@dp.message(AddTaskStates.waiting_for_remind_time)
async def remind_time_received(message: types.Message, state: FSMContext):
    await state.update_data(remind_time=message.text.strip())
    await message.answer("За сколько минут напомнить заранее?", reply_markup=get_advance_keyboard())
    await state.set_state(AddTaskStates.waiting_for_advance_reminder)

@dp.callback_query(AddTaskStates.waiting_for_advance_reminder, F.data.startswith("advance:"))
async def advance_reminder_selected(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()  # Снимаем кружок загрузки сразу

    try:
        advance_min = int(callback.data.split(":")[1])
        chat_id = str(callback.message.chat.id)

        data = await state.get_data()
        task_text = data.get("task_text")
        remind_time = data.get("remind_time")
        if remind_time and remind_time.lower() == "без времени":
            remind_time = None

        if not task_text:
            await callback.message.edit_text("Ошибка: текст задачи потерялся. Начни добавление заново ➕")
            return

        if chat_id not in user_data:
            user_data[chat_id] = {"tasks": [], "water_count": 0, "last_greeting": None}

        user_data[chat_id]["tasks"].append({
            "text": task_text,
            "time": remind_time,
            "advance": advance_min if advance_min > 0 else 0
        })
        save_data(user_data)

        advance_text = f"{advance_min} минут" if advance_min > 0 else "без предварительного"
        time_text = remind_time or "без времени"

        await callback.message.edit_text(
            f"✅ Задача успешно добавлена!\n\n"
            f"{task_text}\n"
            f"Время напоминания: {time_text}\n"
            f"Предварительно: {advance_text}",
            reply_markup=None
        )

    except Exception as e:
        logger.error(f"Ошибка при финализации задачи от {chat_id}: {e}")
        try:
            await callback.message.edit_text("😔 Что-то пошло не так при добавлении задачи. Попробуй добавить заново ➕")
        except:
            pass  # если сообщение уже недоступно

    finally:
        await state.clear()

# ======= Задачи =======
@dp.message(F.text == "Мои задачи 📋")
async def show_tasks(message: types.Message):
    chat_id = str(message.chat.id)
    tasks = user_data.get(chat_id, {}).get("tasks", [])
    if not tasks:
        await message.answer("У тебя пока нет задач ✨", reply_markup=main_menu)
        return
    await message.answer("Твои задачи:", reply_markup=get_tasks_keyboard(chat_id))

@dp.callback_query(F.data.startswith("done:"))
async def task_done(callback: types.CallbackQuery):
    await callback.answer()
    try:
        chat_id = str(callback.message.chat.id)
        idx = int(callback.data.split(":")[1])
        if chat_id in user_data and 0 <= idx < len(user_data[chat_id]["tasks"]):
            task = user_data[chat_id]["tasks"].pop(idx)
            save_data(user_data)
            await callback.message.edit_text(f"✅ Выполнено!\n{task['text']}")
        else:
            await callback.message.edit_text("Задача уже выполнена или удалена ✨")
    except Exception as e:
        logger.error(f"Ошибка task_done: {e}")
        await callback.message.edit_text("Ошибка 😔")

@dp.callback_query(F.data.startswith("delete:"))
async def task_delete(callback: types.CallbackQuery):
    await callback.answer()
    try:
        chat_id = str(callback.message.chat.id)
        idx = int(callback.data.split(":")[1])
        if chat_id in user_data and 0 <= idx < len(user_data[chat_id]["tasks"]):
            task = user_data[chat_id]["tasks"].pop(idx)
            save_data(user_data)
            await callback.message.edit_text(f"❌ Удалено:\n{task['text']}")
        else:
            await callback.message.edit_text("Задача уже удалена ✨")
    except Exception as e:
        logger.error(f"Ошибка task_delete: {e}")
        await callback.message.edit_text("Ошибка 😔")

@dp.callback_query(F.data == "menu:back")
async def back_to_main(callback: types.CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text("Главное меню:", reply_markup=None)
        await callback.message.answer("Выбирай ниже 👇", reply_markup=main_menu)
    except Exception as e:
        logger.error(f"Ошибка back_to_main: {e}")

@dp.message(F.text == "Очистить задачи 🗑")
async def clear_tasks(message: types.Message):
    chat_id = str(message.chat.id)
    if chat_id in user_data:
        user_data[chat_id]["tasks"] = []
        save_data(user_data)
    await message.answer("Все задачи очищены! 🗑✨", reply_markup=main_menu)

# ======= Поддержка и вода =======
@dp.message(F.text == "✨ Мне грустно")
async def send_encouragement(message: types.Message):
    await message.answer(random.choice(ENCOURAGEMENT_PHRASES), reply_markup=main_menu)

@dp.callback_query(F.data == "water:yes")
async def water_yes(callback: types.CallbackQuery):
    await callback.answer()
    try:
        chat_id = str(callback.message.chat.id)
        if chat_id not in user_data:
            user_data[chat_id] = {"tasks": [], "water_count": 0, "last_greeting": None}
        user_data[chat_id]["water_count"] += 1
        save_data(user_data)
        await callback.message.edit_text("Молодец! Ты выпила воду 💧❤️")
    except Exception as e:
        logger.error(f"Ошибка water_yes: {e}")

@dp.callback_query(F.data == "water:no")
async def water_no(callback: types.CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text("Попробуй сейчас выпить стаканчик воды — станет легче 💧")
    except Exception as e:
        logger.error(f"Ошибка water_no: {e}")

@dp.callback_query(F.data == "water:menu")
async def water_menu(callback: types.CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text("Главное меню:", reply_markup=None)
        await callback.message.answer("Выбирай 👇", reply_markup=main_menu)
    except Exception as e:
        logger.error(f"Ошибка water_menu: {e}")

@dp.message(F.text == "Помощь ℹ️")
async def show_help(message: types.Message):
    await message.answer(
        "Я твой заботливый помощник 💕\n\n"
        "• Добавляй задачи\n"
        "• Получай напоминания о воде\n"
        "• Пиши «Мне грустно» — поддержу!\n"
        "• Утреннее приветствие каждый день ☀️",
        reply_markup=main_menu
    )

# ===================== ПЛАНИРОВЩИК =====================
async def morning_greeting():
    logger.info("Отправка утренних приветствий")
    for chat_id in list(user_data.keys()):
        try:
            await bot.send_message(chat_id, "Доброе утро, Кись! ☀️💕\nНовый день — новые возможности!", reply_markup=main_menu)
        except Exception as e:
            logger.error(f"Ошибка приветствия {chat_id}: {e}")

async def water_reminder():
    logger.info("Отправка напоминаний о воде")
    for chat_id in list(user_data.keys()):
        try:
            await bot.send_message(chat_id, "Не забудь выпить водички! 💧\nТы уже пила сегодня?", reply_markup=get_water_keyboard())
        except Exception as e:
            logger.error(f"Ошибка напоминания {chat_id}: {e}")

scheduler.add_job(morning_greeting, "cron", hour=8, minute=0, timezone=MOSCOW_TZ)
scheduler.add_job(water_reminder, "interval", hours=2, next_run_time=datetime.now(MOSCOW_TZ) + timedelta(hours=1))

# ===================== WEBHOOK =====================
async def handle_webhook(request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        return web.Response(status=403)
    try:
        data = await request.json()
        update = types.Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot=bot, update=update)
    except Exception as e:
        logger.error(f"Ошибка webhook: {e}")
        return web.Response(status=400)
    return web.Response()

async def health_check(request):
    return web.Response(text="OK")

async def on_startup(app: web.Application):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(url=WEBHOOK_URL, secret_token=WEBHOOK_SECRET)
    scheduler.start()
    logger.info(f"Бот запущен. Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    scheduler.shutdown()
    logger.info("Бот остановлен")

# ===================== ЗАПУСК =====================
app = web.Application()
app.router.add_get("/", health_check)
app.router.add_post("/webhook", handle_webhook)
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    logger.info("Запуск бота...")
    web.run_app(app, port=PORT)