import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import Session, User, Monster, Inventory
from config import TOKEN
import random

bot = telebot.TeleBot(TOKEN)

# Редкости с цветами
RARITIES = {
    "Обычный": "#808080",
    "Необычный": "#00FF00",
    "Редкий": "#0080FF",
    "Эпический": "#A020F0",
    "Легендарный": "#FF8C00",
    "Мифический": "#FF0000",
    "Божественный": "#FFD700"
}

# 7 юнитов (пример)
MONSTERS = [
    {"name": "Гоблин", "hp": 30, "attack": 5, "rarity": "Обычный"},
    {"name": "Скелет", "hp": 45, "attack": 8, "rarity": "Необычный"},
    {"name": "Волк", "hp": 60, "attack": 12, "rarity": "Редкий"},
    {"name": "Демон", "hp": 80, "attack": 18, "rarity": "Эпический"},
    {"name": "Дракон", "hp": 120, "attack": 25, "rarity": "Легендарный"},
    {"name": "Титан", "hp": 180, "attack": 35, "rarity": "Мифический"},
    {"name": "Ангел Смерти", "hp": 250, "attack": 50, "rarity": "Божественный"}
]

# --- Команды ---
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    # Создаем игрока в БД (если нет)
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📊 Индекс", callback_data="index"))
    markup.add(InlineKeyboardButton("⚔️ Данж", callback_data="dungeon"))
    markup.add(InlineKeyboardButton("🎒 Инвентарь", callback_data="inventory"))
    markup.add(InlineKeyboardButton("🏆 Топ", callback_data="top"))
    bot.send_message(message.chat.id, "Добро пожаловать в RPG!", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    if call.data == "index":
        # Показать статистику игрока
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "Твоя статистика: ...")
    elif call.data == "dungeon":
        # Бой с монстром
        monster = random.choice(MONSTERS)
        bot.send_message(call.message.chat.id, f"Ты встретил <b>{monster['name']}</b> ({monster['rarity']})", parse_mode="HTML")
    # ... остальные обработчики

bot.infinity_polling()