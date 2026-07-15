import os
import sqlite3
import random
import time
import html
import threading
from telebot import TeleBot, types
from telebot.apihelper import ApiTelegramException
from datetime import datetime, timedelta

# --- НАСТРОЙКИ БОТА ---
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 8363674343
ADMIN_ID_2 = 5341904332
BOT = TeleBot(TOKEN)
DB_NAME = "rpg_game_v3.db"

# --- ПУЛ СОЕДИНЕНИЙ ---
import queue
DB_POOL = queue.Queue(maxsize=10)

def get_db_connection():
    try:
        return DB_POOL.get_nowait()
    except queue.Empty:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def return_db_connection(conn):
    try:
        DB_POOL.put_nowait(conn)
    except queue.Full:
        conn.close()

for _ in range(5):
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    DB_POOL.put(conn)

# --- КЭШ ---
USER_CACHE = {}
CACHE_TTL = 30

def get_cached_user(user_id):
    if user_id in USER_CACHE:
        data, timestamp = USER_CACHE[user_id]
        if time.time() - timestamp < CACHE_TTL:
            return data.copy()
    return None

def set_cached_user(user_id, data):
    USER_CACHE[user_id] = (data.copy(), time.time())

def clear_user_cache(user_id):
    if user_id in USER_CACHE:
        del USER_CACHE[user_id]

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            gold INTEGER DEFAULT 500,
            exp INTEGER DEFAULT 0,
            trophies INTEGER DEFAULT 0,
            last_boss TEXT DEFAULT '0',
            pass_exp INTEGER DEFAULT 0,
            pass_lvl INTEGER DEFAULT 1,
            slots_unlocked INTEGER DEFAULT 3,
            mult_gold_lvl INTEGER DEFAULT 0,
            mult_atk_lvl INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            card_name TEXT,
            rarity TEXT,
            level INTEGER DEFAULT 1,
            hp INTEGER,
            atk INTEGER,
            is_equipped INTEGER DEFAULT 0,
            variant TEXT DEFAULT 'обычный'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leaderboard (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            trophies INTEGER DEFAULT 0,
            week_start TEXT
        )
    ''')
    
    # Миграции
    for col in ['pass_exp', 'pass_lvl', 'slots_unlocked', 'mult_gold_lvl', 'mult_atk_lvl']:
        try: cursor.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
    try: cursor.execute("ALTER TABLE inventory ADD COLUMN variant TEXT DEFAULT 'обычный'")
    except sqlite3.OperationalError: pass
        
    conn.commit()
    return_db_connection(conn)

def get_setting(key, default):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    return_db_connection(conn)
    return row[0] if row else default

def set_setting(key, value):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    return_db_connection(conn)

def notify_all_players(text):
    def send_notifications():
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
        return_db_connection(conn)
        for u in users:
            try:
                BOT.send_message(u[0], text, parse_mode="Markdown")
                time.sleep(0.05)
            except Exception:
                pass
    threading.Thread(target=send_notifications, daemon=True).start()

# --- СИСТЕМА ШАНСОВ ---
RARITIES = {
    "Обычная": {"chance": 0.50},
    "Необычная": {"chance": 0.25},
    "Редкая": {"chance": 0.15},
    "Эпическая": {"chance": 0.07},
    "Легендарная": {"chance": 0.025},
    "Мифическая": {"chance": 0.004},
    "Божественная": {"chance": 0.001}
}

RARITY_COLORS = {
    "Обычная": "⬜",
    "Необычная": "🟢",
    "Редкая": "🔵",
    "Эпическая": "🟣",
    "Легендарная": "🟠",
    "Мифическая": "🟡",
    "Божественная": "💠",
    "УЛЬТРА": "💀",
    "Эксклюзив": "👑"
}

# --- РЕЕСТР ЮНИТОВ (ФЭНТЕЗИ) ---
UNITS = {
    # Обычные (2)
    "Скелет-воин": {"rarity": "Обычная", "hp": 80, "atk": 10},
    "Гоблин-лутник": {"rarity": "Обычная", "hp": 70, "atk": 12},
    # Необычные (2)
    "Орк-берсерк": {"rarity": "Необычная", "hp": 120, "atk": 20},
    "Эльф-следопыт": {"rarity": "Необычная", "hp": 100, "atk": 22},
    # Редкие (2)
    "Рыцарь-паладин": {"rarity": "Редкая", "hp": 180, "atk": 35},
    "Маг-пиромант": {"rarity": "Редкая", "hp": 150, "atk": 40},
    # Эпические (2)
    "Дракон-страж": {"rarity": "Эпическая", "hp": 280, "atk": 65},
    "Демон-разрушитель": {"rarity": "Эпическая", "hp": 250, "atk": 70},
    # Легендарные (2)
    "Феникс": {"rarity": "Легендарная", "hp": 400, "atk": 110},
    "Титан-громовержец": {"rarity": "Легендарная", "hp": 450, "atk": 100},
    # Мифические (2)
    "Дракон-император": {"rarity": "Мифическая", "hp": 700, "atk": 180},
    "Архангел-мститель": {"rarity": "Мифическая", "hp": 750, "atk": 170},
    # Божественные (2)
    "Создатель миров": {"rarity": "Божественная", "hp": 1200, "atk": 300},
    "Вечный страж": {"rarity": "Божественная", "hp": 1100, "atk": 320},
    # УЛЬТРА (из кризиса)
    "Ультра-Некрос": {"rarity": "УЛЬТРА", "hp": 2500, "atk": 550},
    # Эксклюзив (из пасса)
    "Король-лич": {"rarity": "Эксклюзив", "hp": 1800, "atk": 450},
    # Крафтовый
    "Первородный хаос": {"rarity": "Эксклюзив", "hp": 3000, "atk": 700},
    # Пак
    "Небесный дракон": {"rarity": "Легендарная", "hp": 500, "atk": 130}
}

UNITS_LIST = list(UNITS.keys())
INDEX_UNITS = [u for u in UNITS_LIST if UNITS[u]["rarity"] not in ["УЛЬТРА", "Эксклюзив"]]

# --- ВАРИАНТЫ ЮНИТОВ ---
UNIT_VARIANTS = {
    "обычный": {"mult": 1.0, "label": ""},
    "золотой": {"mult": 1.2, "label": "⭐ ЗОЛОТОЙ"},
    "алмазный": {"mult": 1.5, "label": "💎 АЛМАЗНЫЙ"}
}

def get_unit_variant():
    roll = random.random()
    if roll < 0.02:
        return "алмазный"
    elif roll < 0.12:
        return "золотой"
    return "обычный"

# --- ПАК ---
PACK_UNITS = {
    "Небесный дракон": ("Легендарная", 30.0),
    "Феникс": ("Легендарная", 25.0),
    "Титан-громовержец": ("Легендарная", 25.0),
    "Дракон-император": ("Мифическая", 15.0),
    "Архангел-мститель": ("Мифическая", 5.0)
}

def roll_pack():
    names = list(PACK_UNITS.keys())
    chances = [PACK_UNITS[n][1] for n in names]
    return random.choices(names, weights=chances)[0]

# --- НАСТРОЙКИ СЛОЖНОСТИ ---
DIFFICULTIES = {
    "easy": {"name": "Легко", "mult": 0.5, "gold": (5, 15), "exp": 10, "enemies": 1},
    "normal": {"name": "Нормал", "mult": 1.0, "gold": (15, 30), "exp": 25, "enemies": 1},
    "hard": {"name": "Сложно", "mult": 1.8, "gold": (35, 65), "exp": 55, "enemies": 2},
    "nightmare": {"name": "Кошмар", "mult": 3.0, "gold": (80, 150), "exp": 120, "enemies": 2},
    "legendary": {"name": "Легендарная", "mult": 5.0, "gold": (200, 350), "exp": 350, "enemies": 2}
}

# --- БОЕВОЙ ПАСС ---
def get_pass_exp_required(level):
    if level >= 15:
        return float('inf')
    return int(80 + (level - 1) * 120)

PASS_REWARDS = {
    1: {"type": "gold", "amount": 100, "name": "100 Золота"},
    2: {"type": "gold", "amount": 150, "name": "150 Золота"},
    3: {"type": "gold", "amount": 200, "name": "200 Золота"},
    4: {"type": "gold", "amount": 250, "name": "250 Золота"},
    5: {"type": "gold", "amount": 300, "name": "300 Золота"},
    6: {"type": "gold", "amount": 400, "name": "400 Золота"},
    7: {"type": "gold", "amount": 500, "name": "500 Золота"},
    8: {"type": "pack", "amount": 1, "name": "1x Легендарный пак 📦"},
    9: {"type": "gold", "amount": 600, "name": "600 Золота"},
    10: {"type": "gold", "amount": 750, "name": "750 Золота"},
    11: {"type": "pack", "amount": 2, "name": "2x Легендарный пак 📦"},
    12: {"type": "gold", "amount": 900, "name": "900 Золота"},
    13: {"type": "pack", "amount": 3, "name": "3x Легендарный пак 📦"},
    14: {"type": "gold", "amount": 1100, "name": "1100 Золота"},
    15: {"type": "unit_rarity", "rarity": "Эксклюзив", "name": "ЭКСКЛЮЗИВНЫЙ ЮНИТ 👑 Король-лич"}
}

# --- ЛИДЕРБОРД ---
def init_leaderboard():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, trophies FROM users")
    for user in cursor.fetchall():
        cursor.execute("INSERT OR IGNORE INTO leaderboard (user_id, username, trophies, week_start) VALUES (?, ?, ?, datetime('now'))",
                      (user[0], user[1], user[2]))
    conn.commit()
    return_db_connection(conn)

def reset_leaderboard():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, trophies FROM leaderboard ORDER BY trophies DESC LIMIT 3")
    winners = cursor.fetchall()
    rewards = [{0: 150000, 1: 100000, 2: 50000}[i] for i in range(3)]
    for i, w in enumerate(winners):
        if i < 3:
            cursor.execute("UPDATE users SET gold = gold + ? WHERE user_id = ?", (rewards[i], w[0]))
            try:
                BOT.send_message(w[0], f"🏆 **ПОБЕДА В РЕЙТИНГЕ!**\nМесто: #{i+1}\n💰 Награда: {rewards[i]} золота", parse_mode="Markdown")
            except: pass
    cursor.execute("DELETE FROM leaderboard")
    cursor.execute("SELECT user_id, username, trophies FROM users")
    for user in cursor.fetchall():
        cursor.execute("INSERT INTO leaderboard (user_id, username, trophies, week_start) VALUES (?, ?, ?, datetime('now'))",
                      (user[0], user[1], user[2]))
    conn.commit()
    return_db_connection(conn)
    notify_all_players("🏆 **НЕДЕЛЬНЫЙ РЕЙТИНГ ОБНОВЛЕН!** Награды выданы! 🚀")

def get_week_time_left():
    now = datetime.now()
    days = (7 - now.weekday()) % 7 or 7
    next_monday = (now + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    diff = next_monday - now
    return f"{diff.days}д {diff.seconds//3600}ч {(diff.seconds%3600)//60}м"

# --- ОСНОВНЫЕ ФУНКЦИИ ---
def get_user(user_id, username="Игрок"):
    cached = get_cached_user(user_id)
    if cached:
        return cached
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        cursor.execute("INSERT INTO leaderboard (user_id, username, trophies, week_start) VALUES (?, ?, 0, datetime('now'))", (user_id, username))
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
    
    return_db_connection(conn)
    result = {"user_id": user[0], "username": user[1], "gold": user[2], "exp": user[3], "trophies": user[4],
              "last_boss": float(user[5] if user[5] else 0), "pass_exp": user[6] if len(user)>6 else 0,
              "pass_lvl": user[7] if len(user)>7 else 1, "slots_unlocked": user[8] if len(user)>8 else 3,
              "mult_gold_lvl": user[9] if len(user)>9 else 0, "mult_atk_lvl": user[10] if len(user)>10 else 0}
    set_cached_user(user_id, result)
    return result

def update_user_stats(user_id, gold=0, exp=0, trophies=0, last_boss=None, pass_exp=0):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET gold = MAX(0, gold+?), exp=exp+?, trophies=MAX(0, trophies+?), pass_exp=pass_exp+? WHERE user_id=?",
                  (gold, exp, trophies, pass_exp, user_id))
    if last_boss is not None:
        cursor.execute("UPDATE users SET last_boss = ? WHERE user_id = ?", (str(last_boss), user_id))
    
    cursor.execute("SELECT pass_lvl, pass_exp FROM users WHERE user_id = ?", (user_id,))
    u_pass = cursor.fetchone()
    if u_pass:
        c_lvl, c_exp = u_pass[0], u_pass[1]
        while c_lvl < 15:
            needed = get_pass_exp_required(c_lvl)
            if c_exp >= needed:
                c_exp -= needed
                c_lvl += 1
                give_pass_reward(user_id, c_lvl)
            else:
                break
        cursor.execute("UPDATE users SET pass_lvl = ?, pass_exp = ? WHERE user_id = ?", (c_lvl, c_exp, user_id))
    
    cursor.execute("UPDATE leaderboard SET trophies = MAX(0, trophies+?), username = (SELECT username FROM users WHERE user_id=?) WHERE user_id=?", 
                  (trophies, user_id, user_id))
    conn.commit()
    return_db_connection(conn)
    clear_user_cache(user_id)

def give_pass_reward(user_id, lvl):
    reward = PASS_REWARDS.get(lvl)
    if not reward: return
    conn = get_db_connection()
    cursor = conn.cursor()
    if reward["type"] == "gold":
        cursor.execute("UPDATE users SET gold = gold + ? WHERE user_id = ?", (reward["amount"], user_id))
    elif reward["type"] == "pack":
        for _ in range(reward["amount"]):
            card_name = roll_pack()
            unit = UNITS[card_name]
            variant = get_unit_variant()
            mult = UNIT_VARIANTS[variant]["mult"]
            cursor.execute("INSERT INTO inventory (user_id, card_name, rarity, level, hp, atk, variant) VALUES (?, ?, ?, 1, ?, ?, ?)",
                          (user_id, card_name, unit["rarity"], int(unit["hp"]*mult), int(unit["atk"]*mult), variant))
    elif reward["type"] == "unit_rarity":
        av_units = [n for n,u in UNITS.items() if u["rarity"] == reward["rarity"]]
        if av_units:
            u_name = random.choice(av_units)
            u_data = UNITS[u_name]
            cursor.execute("INSERT INTO inventory (user_id, card_name, rarity, level, hp, atk, variant) VALUES (?, ?, ?, 1, ?, ?, ?)",
                          (user_id, u_name, u_data["rarity"], u_data["hp"], u_data["atk"], "обычный"))
    conn.commit()
    return_db_connection(conn)
    clear_user_cache(user_id)
    try: BOT.send_message(user_id, f"🎁 **Награда пасса!** Уровень {lvl}: {reward['name']}!", parse_mode="Markdown")
    except: pass

def get_equipped_team(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, card_name, rarity, level, hp, atk, variant FROM inventory WHERE user_id = ? AND is_equipped = 1", (user_id,))
    cards = cursor.fetchall()
    return_db_connection(conn)
    return [{"id": c[0], "name": c[1], "rarity": c[2], "level": c[3], "hp": c[4], "atk": c[5], "variant": c[6]} for c in cards]

def generate_hp_bar(current, maximum, length=8):
    if maximum <= 0: return "░" * length
    filled = int(round(max(0, min(1, current/maximum)) * length))
    return "❤️" + "█" * filled + "░" * (length - filled)

def get_upgrade_cost(start_level, times):
    return sum(int(200 + (i ** 2) * 85) for i in range(start_level, start_level + times))

def calculate_stats(base_hp, base_atk, level, variant="обычный"):
    mult = UNIT_VARIANTS[variant]["mult"]
    base_mult = 1 + (level - 1) * 0.30
    return int(base_hp * mult * base_mult), int(base_atk * mult * base_mult)

def create_unit(user_id, card_name, variant=None):
    if variant is None:
        variant = get_unit_variant()
    unit = UNITS[card_name]
    mult = UNIT_VARIANTS[variant]["mult"]
    hp, atk = int(unit["hp"] * mult), int(unit["atk"] * mult)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO inventory (user_id, card_name, rarity, level, hp, atk, variant) VALUES (?, ?, ?, 1, ?, ?, ?)",
                  (user_id, card_name, unit["rarity"], hp, atk, variant))
    conn.commit()
    return_db_connection(conn)
    return variant, hp, atk

def consolidate_inventory(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT card_name, rarity, level, hp, atk, variant, COUNT(*), MIN(id) 
        FROM inventory WHERE user_id = ? 
        GROUP BY card_name, rarity, level, hp, atk, variant HAVING COUNT(*) > 1
    """, (user_id,))
    for dup in cursor.fetchall():
        cursor.execute("DELETE FROM inventory WHERE user_id = ? AND card_name = ? AND rarity = ? AND level = ? AND hp = ? AND atk = ? AND variant = ? AND id != ?",
                      (user_id, dup[0], dup[1], dup[2], dup[3], dup[4], dup[5], dup[7]))
    conn.commit()
    return_db_connection(conn)

# --- КЛАВИАТУРА ---
def main_keyboard(user_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("🎮 Игровой центр", "📊 Рейтинги", "📖 Индекс")
    if user_id in [ADMIN_ID, ADMIN_ID_2]:
        kb.add("👑 Админ Панель")
    return kb

@BOT.message_handler(func=lambda m: m.text == "🎮 Игровой центр")
def game_center(message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("👤 Профиль", "🎒 Инвентарь", "🔮 Призыв", "🏪 Магазин", "🏰 Данж", "👹 Босс", "🎫 Боевой Пасс", "🔧 Крафт", "⬅️ Назад")
    BOT.send_message(message.chat.id, "🎮 **Игровой центр**", reply_markup=kb)

@BOT.message_handler(func=lambda m: m.text == "📊 Рейтинги")
def ratings_menu(message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add("🏆 Топ", "⬅️ Назад")
    BOT.send_message(message.chat.id, "📊 **Рейтинги**", reply_markup=kb)

@BOT.message_handler(func=lambda m: m.text == "⬅️ Назад")
def back_to_main(message):
    BOT.send_message(message.chat.id, "⬅️ Возврат", reply_markup=main_keyboard(message.from_user.id))

@BOT.message_handler(commands=['start'])
def start_cmd(message):
    get_user(message.from_user.id, message.from_user.first_name)
    BOT.send_message(message.chat.id, "⚔️ **Фэнтези-RPG Бот запущен!**", reply_markup=main_keyboard(message.from_user.id))

# --- ПРОФИЛЬ ---
@BOT.message_handler(func=lambda m: m.text == "👤 Профиль")
def profile_menu(message):
    user = get_user(message.from_user.id, message.from_user.first_name)
    team = get_equipped_team(message.from_user.id)
    team_text = "\n".join([f" ▪️ {RARITY_COLORS.get(c['rarity'], '')} {c['name']} [Ур.{c['level']}] [⚔️{c['atk']}] {UNIT_VARIANTS.get(c.get('variant','обычный'),{}).get('label','')}" for c in team]) or " Отряд пуст."
    
    if user["pass_lvl"] < 15:
        needed = get_pass_exp_required(user["pass_lvl"])
        progress = f"{user['pass_exp']}/{needed} XP"
    else:
        progress = "МАКСИМУМ ✅"
    
    text = f"👤 **ПРОФИЛЬ:** {user['username']}\n\n🏆 Кубки: {user['trophies']}\n💰 Золото: {user['gold']}\n⭐ Опыт: {user['exp']}\n🎫 Боевой Пасс: {user['pass_lvl']}/15 ({progress})\n🔓 Слотов: {user['slots_unlocked']}/4\n📈 Множитель: Золото +{user['mult_gold_lvl']*25}% | Урон +{user['mult_atk_lvl']*15}%\n\n🛡 **Отряд:**\n{team_text}"
    BOT.send_message(message.chat.id, text, parse_mode="Markdown")

# --- ИНВЕНТАРЬ ---
def send_inventory(chat_id, user_id, page=0):
    consolidate_inventory(user_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, card_name, rarity, level, hp, atk, is_equipped, variant FROM inventory WHERE user_id = ?", (user_id,))
    cards = cursor.fetchall()
    return_db_connection(conn)
    if not cards:
        return BOT.send_message(chat_id, "🎒 Инвентарь пуст.")
    
    limit, total_pages = 10, (len(cards)+9)//10
    page = max(0, min(page, total_pages-1))
    start, end = page*limit, min((page+1)*limit, len(cards))
    
    text = f"🎒 **Инвентарь (Стр.{page+1}/{total_pages}):**"
    kb = types.InlineKeyboardMarkup(row_width=1)
    for c in cards[start:end]:
        status = "🛡 " if c[6] else ""
        variant_label = UNIT_VARIANTS.get(c[7] if len(c)>7 else "обычный", {}).get("label", "")
        kb.add(types.InlineKeyboardButton(f"{status}{RARITY_COLORS.get(c[2],'')} {c[1]} [{c[2]}] Ур.{c[3]} {variant_label}", 
                                         callback_data=f"inv_{c[0]}_{page}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"invpage_{page-1}"))
    if page < total_pages-1: nav.append(types.InlineKeyboardButton("➡️", callback_data=f"invpage_{page+1}"))
    if nav: kb.row(*nav)
    BOT.send_message(chat_id, text, reply_markup=kb)

@BOT.message_handler(func=lambda m: m.text == "🎒 Инвентарь")
def inventory_menu_msg(message):
    send_inventory(message.chat.id, message.from_user.id, 0)

@BOT.callback_query_handler(func=lambda c: c.data.startswith("invpage_"))
def inventory_page_cb(callback):
    page = int(callback.data.split("_")[1])
    try: BOT.delete_message(callback.message.chat.id, callback.message.message_id)
    except: pass
    send_inventory(callback.message.chat.id, callback.from_user.id, page)

@BOT.callback_query_handler(func=lambda c: c.data.startswith("inv_"))
def process_select_card(callback):
    _, card_id, from_page = callback.data.split("_")
    show_card_details(callback.message.chat.id, callback.message.message_id, int(card_id), int(from_page))

def show_card_details(chat_id, message_id, card_id, from_page):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, card_name, rarity, level, hp, atk, is_equipped, variant FROM inventory WHERE id = ?", (card_id,))
    card = cursor.fetchone()
    return_db_connection(conn)
    if not card: return

    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(types.InlineKeyboardButton("❌ Деактивировать" if card[6] else "🛡 Активировать", 
                                     callback_data=f"eq_{1 if not card[6] else 0}_{card_id}_{from_page}"))
    
    for opt in [1, 10, 25]:
        cost = get_upgrade_cost(card[3], opt)
        kb.add(types.InlineKeyboardButton(f"+{opt} (💰{cost})", callback_data=f"bulkup_{opt}_{card_id}_{from_page}"))
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"invpage_{from_page}"))
    
    variant_label = UNIT_VARIANTS.get(card[7] if len(card)>7 else "обычный", {}).get("label", "")
    text = f"🃏 **{card[1]}**\n📊 {RARITY_COLORS.get(card[2],'')} {card[2]}\n⭐ Ур.{card[3]}\n❤️ HP: {card[4]}\n⚔️ ATK: {card[5]}\n💎 {variant_label or 'Обычный'}"
    safe_edit(chat_id, message_id, text, reply_markup=kb)

@BOT.callback_query_handler(func=lambda c: c.data.startswith("bulkup_"))
def process_bulk_upgrade(callback):
    _, times, card_id, from_page = callback.data.split("_")
    times, card_id, from_page = int(times), int(card_id), int(from_page)
    user = get_user(callback.from_user.id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT level, card_name, variant FROM inventory WHERE id = ?", (card_id,))
    card = cursor.fetchone()
    if not card: return_db_connection(conn); return
    cost = get_upgrade_cost(card[0], times)
    if user["gold"] < cost:
        return_db_connection(conn)
        return BOT.answer_callback_query(callback.id, f"❌ Нужно: {cost} 💰", show_alert=True)
    new_level = card[0] + times
    base = UNITS.get(card[1], {"hp": 100, "atk": 10})
    new_hp, new_atk = calculate_stats(base["hp"], base["atk"], new_level, card[2] if len(card)>2 else "обычный")
    cursor.execute("UPDATE inventory SET level = ?, hp = ?, atk = ? WHERE id = ?", (new_level, new_hp, new_atk, card_id))
    conn.commit()
    return_db_connection(conn)
    update_user_stats(callback.from_user.id, gold=-cost)
    BOT.answer_callback_query(callback.id, f"🎉 +{times} уровней!\n❤️ {new_hp}\n⚔️ {new_atk}", show_alert=True)
    show_card_details(callback.message.chat.id, callback.message.message_id, card_id, from_page)

@BOT.callback_query_handler(func=lambda c: c.data.startswith("eq_"))
def process_equip(callback):
    _, action, card_id, from_page = callback.data.split("_")
    action, card_id, from_page = int(action), int(card_id), int(from_page)
    user = get_user(callback.from_user.id)
    if action == 1 and len(get_equipped_team(callback.from_user.id)) >= user["slots_unlocked"]:
        return BOT.answer_callback_query(callback.id, f"❌ Лимит отряда ({user['slots_unlocked']})!", show_alert=True)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE inventory SET is_equipped = ? WHERE id = ?", (action, card_id))
    conn.commit()
    return_db_connection(conn)
    clear_user_cache(callback.from_user.id)
    show_card_details(callback.message.chat.id, callback.message.message_id, card_id, from_page)

# --- ПРИЗЫВ ---
@BOT.message_handler(func=lambda m: m.text == "🔮 Призыв")
def summon_menu(message):
    user = get_user(message.from_user.id)
    luck = float(get_setting("luck_multiplier", "1.0"))
    text = f"🔮 **Призыв героев**\n💰 Золото: {user['gold']}\n🎟 Цена: 100 золота\n🔮 Удача: {luck}x"
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("1x 💰100", callback_data="buy_summon"),
        types.InlineKeyboardButton("5x 💰500", callback_data="multisummon_5"),
        types.InlineKeyboardButton("10x 💰1000", callback_data="multisummon_10")
    )
    BOT.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=kb)

@BOT.callback_query_handler(func=lambda c: c.data == "buy_summon")
def process_summon(callback):
    user = get_user(callback.from_user.id)
    if user["gold"] < 100:
        return BOT.answer_callback_query(callback.id, "❌ Не хватает золота!", show_alert=True)
    
    luck = float(get_setting("luck_multiplier", "1.0"))
    chances = {}
    total = 0.0
    for rarity, data in RARITIES.items():
        chance = data["chance"] * (luck if rarity != "Обычная" else 1.0)
        chances[rarity] = chance
        total += chance
    chances = {r: c/total for r,c in chances.items()}
    
    rand = random.random()
    cum = 0
    for rarity, chance in chances.items():
        cum += chance
        if rand <= cum:
            selected_rarity = rarity
            break
    else:
        selected_rarity = "Обычная"
    
    avail = [n for n,u in UNITS.items() if u["rarity"] == selected_rarity]
    if not avail:
        selected_rarity = "Обычная"
        avail = [n for n,u in UNITS.items() if u["rarity"] == "Обычная"]
    card_name = random.choice(avail)
    variant = get_unit_variant()
    variant_label = UNIT_VARIANTS[variant]["label"]
    
    update_user_stats(callback.from_user.id, gold=-100)
    variant, hp, atk = create_unit(callback.from_user.id, card_name, variant)
    consolidate_inventory(callback.from_user.id)
    
    safe_edit(callback.message.chat.id, callback.message.message_id,
              f"✨ **Призван:** {RARITY_COLORS.get(selected_rarity, '')} **{card_name}**\n📊 {selected_rarity}\n⭐ Ур.1\n❤️ HP: {hp} | ⚔️ ATK: {atk}\n{variant_label}")

@BOT.callback_query_handler(func=lambda c: c.data.startswith("multisummon_"))
def multi_summon(callback):
    amount = int(callback.data.split("_")[1])
    user = get_user(callback.from_user.id)
    cost = 100 * amount
    if user["gold"] < cost:
        return BOT.answer_callback_query(callback.id, f"❌ Нужно: {cost} 💰", show_alert=True)
    
    luck = float(get_setting("luck_multiplier", "1.0"))
    chances = {}
    total = 0.0
    for rarity, data in RARITIES.items():
        chance = data["chance"] * (luck if rarity != "Обычная" else 1.0)
        chances[rarity] = chance
        total += chance
    chances = {r: c/total for r,c in chances.items()}
    
    results = {}
    for _ in range(amount):
        rand = random.random()
        cum = 0
        for rarity, chance in chances.items():
            cum += chance
            if rand <= cum:
                selected_rarity = rarity
                break
        else:
            selected_rarity = "Обычная"
        avail = [n for n,u in UNITS.items() if u["rarity"] == selected_rarity] or [n for n,u in UNITS.items() if u["rarity"] == "Обычная"]
        card_name = random.choice(avail)
        results[card_name] = results.get(card_name, 0) + 1
    
    update_user_stats(callback.from_user.id, gold=-cost)
    for card_name, count in results.items():
        for _ in range(count):
            create_unit(callback.from_user.id, card_name, get_unit_variant())
    consolidate_inventory(callback.from_user.id)
    
    text = f"🔮 **МУЛЬТИ-ПРИЗЫВ** x{amount}\n\n"
    for card_name, count in sorted(results.items(), key=lambda x: x[1], reverse=True):
        unit = UNITS[card_name]
        text += f"▪️ {RARITY_COLORS.get(unit['rarity'], '')} {card_name} [{unit['rarity']}] x{count}\n"
    text += f"\n💰 Потрачено: {cost} золота"
    safe_edit(callback.message.chat.id, callback.message.message_id, text)

# --- МАГАЗИН ---
@BOT.message_handler(func=lambda m: m.text == "🏪 Магазин")
def shop_menu(message):
    user = get_user(message.from_user.id)
    text = f"🏪 **Магазин**\n💰 Золото: {user['gold']}"
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("📦 Легендарный пак (💰1500)", callback_data="buy_pack"),
        types.InlineKeyboardButton("⚡ Прокачка", callback_data="shop_upgrades")
    )
    BOT.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=kb)

@BOT.callback_query_handler(func=lambda c: c.data == "buy_pack")
def buy_pack(callback):
    user = get_user(callback.from_user.id)
    if user["gold"] < 1500:
        return BOT.answer_callback_query(callback.id, "❌ Нужно 1500 💰", show_alert=True)
    
    card_name = roll_pack()
    color = RARITY_COLORS.get(UNITS[card_name]['rarity'], '')
    update_user_stats(callback.from_user.id, gold=-1500)
    variant = get_unit_variant()
    variant_label = UNIT_VARIANTS[variant]["label"]
    variant, hp, atk = create_unit(callback.from_user.id, card_name, variant)
    consolidate_inventory(callback.from_user.id)
    
    safe_edit(callback.message.chat.id, callback.message.message_id,
              f"📦 **Легендарный пак открыт!**\n\n{color} **{card_name}**\n📊 {UNITS[card_name]['rarity']}\n❤️ HP: {hp} | ⚔️ ATK: {atk}\n{variant_label}")

@BOT.callback_query_handler(func=lambda c: c.data == "shop_upgrades")
def shop_upgrades(callback):
    user = get_user(callback.from_user.id)
    slot_cost = 6500
    gold_up = 1000 + user["mult_gold_lvl"] * 1200
    atk_up = 1500 + user["mult_atk_lvl"] * 1500
    
    text = f"⚡ **ПРОКАЧКА**\n💰 Золото: {user['gold']}\n\n▪️ Слотов: {user['slots_unlocked']}/4\n▪️ Бонус золота: +{user['mult_gold_lvl']*25}%\n▪️ Бонус урона: +{user['mult_atk_lvl']*15}%"
    kb = types.InlineKeyboardMarkup(row_width=1)
    if user["slots_unlocked"] < 4:
        kb.add(types.InlineKeyboardButton(f"🔓 4-й слот (💰{slot_cost})", callback_data="up_slot"))
    kb.add(types.InlineKeyboardButton(f"💰 +25% золота (💰{gold_up})", callback_data="up_gold"))
    kb.add(types.InlineKeyboardButton(f"⚔️ +15% урона (💰{atk_up})", callback_data="up_atk"))
    safe_edit(callback.message.chat.id, callback.message.message_id, text, reply_markup=kb)

@BOT.callback_query_handler(func=lambda c: c.data.startswith("up_"))
def process_upgrade(callback):
    user = get_user(callback.from_user.id)
    if callback.data == "up_slot":
        if user["slots_unlocked"] >= 4: return BOT.answer_callback_query(callback.id, "❌ Уже открыт!", show_alert=True)
        if user["gold"] < 6500: return BOT.answer_callback_query(callback.id, "❌ Нужно 6500 💰", show_alert=True)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET slots_unlocked = 4, gold = gold - 6500 WHERE user_id = ?", (callback.from_user.id,))
        conn.commit()
        return_db_connection(conn)
        clear_user_cache(callback.from_user.id)
        BOT.answer_callback_query(callback.id, "🎉 4-й слот открыт!", show_alert=True)
    elif callback.data == "up_gold":
        cost = 1000 + user["mult_gold_lvl"] * 1200
        if user["gold"] < cost: return BOT.answer_callback_query(callback.id, f"❌ Нужно {cost} 💰", show_alert=True)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET gold = gold - ?, mult_gold_lvl = mult_gold_lvl + 1 WHERE user_id = ?", (cost, callback.from_user.id))
        conn.commit()
        return_db_connection(conn)
        clear_user_cache(callback.from_user.id)
        BOT.answer_callback_query(callback.id, f"🎉 Уровень {user['mult_gold_lvl']+1}!", show_alert=True)
    elif callback.data == "up_atk":
        cost = 1500 + user["mult_atk_lvl"] * 1500
        if user["gold"] < cost: return BOT.answer_callback_query(callback.id, f"❌ Нужно {cost} 💰", show_alert=True)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET gold = gold - ?, mult_atk_lvl = mult_atk_lvl + 1 WHERE user_id = ?", (cost, callback.from_user.id))
        conn.commit()
        return_db_connection(conn)
        clear_user_cache(callback.from_user.id)
        BOT.answer_callback_query(callback.id, f"🎉 Уровень {user['mult_atk_lvl']+1}!", show_alert=True)
    shop_upgrades(callback)

# --- ДАНЖ ---
@BOT.message_handler(func=lambda m: m.text == "🏰 Данж")
def dungeon_menu(message):
    team = get_equipped_team(message.from_user.id)
    if not team:
        return BOT.send_message(message.chat.id, "❌ Отряд пуст!")
    kb = types.InlineKeyboardMarkup(row_width=2)
    for key, diff in DIFFICULTIES.items():
        kb.add(types.InlineKeyboardButton(f"{diff['name']} (x{diff['mult']})", callback_data=f"dng_{key}"))
    if get_setting("ultra_mode", "0") == "1":
        kb.add(types.InlineKeyboardButton("💀 УЛЬТРА-КРИЗИС", callback_data="dng_ultra"))
    BOT.send_message(message.chat.id, "🏰 **Выберите сложность:**", reply_markup=kb)

active_battles = {}

@BOT.callback_query_handler(func=lambda c: c.data.startswith("dng_"))
def fight_dungeon(callback):
    diff_key = callback.data.split("_")[1]
    user = get_user(callback.from_user.id)
    team = get_equipped_team(callback.from_user.id)
    if not team: return
    
    if diff_key == "ultra":
        diff = {"name": "УЛЬТРА-КРИЗИС 💀", "mult": 50.0, "gold": (1000, 2000), "exp": 2000, "enemies": 8, "pass_exp": 2000, "no_cups": True}
    else:
        diff = DIFFICULTIES[diff_key].copy()
        diff["pass_exp"] = 30
        diff["no_cups"] = False
    
    msg = BOT.send_message(callback.message.chat.id, "⚔️ *Бой начат...*")
    
    player_max_hp = sum(c['hp'] for c in team)
    player_atk = sum(c['atk'] for c in team) * (1 + user["mult_atk_lvl"] * 0.15)
    base_hp = 200 + user["trophies"] * 1.5
    base_atk = 20 + user["trophies"] * 0.25
    
    battle = {
        "chat_id": msg.chat.id, "message_id": msg.message_id, "user_id": callback.from_user.id,
        "player_hp": player_max_hp, "player_max_hp": player_max_hp, "final_player_atk": int(player_atk),
        "enemy_hp": int(base_hp * diff["mult"]), "enemy_max_hp": int(base_hp * diff["mult"]),
        "enemy_atk": int(base_atk * diff["mult"]), "current_enemy": 1, "total_enemies": diff["enemies"],
        "diff": diff, "hit_counter": 0
    }
    active_battles[msg.message_id] = battle
    process_battle_round(msg.message_id)

def process_battle_round(message_id):
    if message_id not in active_battles: return
    battle = active_battles[message_id]
    battle["hit_counter"] += 1
    damage = battle["final_player_atk"]
    
    has_ultra = any(c["name"] == "Ультра-Некрос" for c in get_equipped_team(battle["user_id"]))
    has_exclusive = any(c["name"] in ["Король-лич", "Первородный хаос"] for c in get_equipped_team(battle["user_id"]))
    
    if has_ultra and battle["hit_counter"] % 3 == 0:
        damage *= 5
    if has_exclusive:
        damage = int(damage * 1.5)
    
    battle["enemy_hp"] -= damage
    if battle["enemy_hp"] <= 0:
        battle["current_enemy"] += 1
        if battle["current_enemy"] > battle["total_enemies"]:
            finish_battle_victory(message_id)
            return
        battle["enemy_max_hp"] = int(battle["enemy_max_hp"] * 1.15)
        battle["enemy_hp"] = battle["enemy_max_hp"]
        battle["enemy_atk"] = int(battle["enemy_atk"] * 1.15)
    else:
        battle["player_hp"] -= battle["enemy_atk"]
        if battle["player_hp"] <= 0:
            finish_battle_defeat(message_id)
            return
    
    p_bar = generate_hp_bar(battle["player_hp"], battle["player_max_hp"])
    e_bar = generate_hp_bar(battle["enemy_hp"], battle["enemy_max_hp"])
    text = f"⚔️ **{battle['diff']['name']}** ({battle['current_enemy']}/{battle['total_enemies']})\n\n🛡 {battle['player_hp']}/{battle['player_max_hp']}\n{p_bar}\n\n👹 {battle['enemy_hp']}/{battle['enemy_max_hp']}\n{e_bar}\n⚔️ Урон: {battle['enemy_atk']}"
    try: BOT.edit_message_text(text, chat_id=battle["chat_id"], message_id=message_id, parse_mode="Markdown")
    except: pass
    threading.Timer(1.0, process_battle_round, args=[message_id]).start()

def finish_battle_victory(message_id):
    battle = active_battles[message_id]
    gold_mult = 1 + get_user(battle["user_id"])["mult_gold_lvl"] * 0.25
    gold = int(random.randint(battle["diff"]["gold"][0], battle["diff"]["gold"][1]) * gold_mult)
    cups = 0 if battle["diff"].get("no_cups") else random.randint(15, 35)
    update_user_stats(battle["user_id"], gold=gold, exp=battle["diff"]["exp"], trophies=cups, pass_exp=battle["diff"]["pass_exp"])
    text = f"🎉 **Победа!**\n💰 +{gold} золота\n🏆 +{cups} кубков" + ("" if not battle["diff"].get("no_cups") else "\n⚠️ Кубки не начислены")
    try: BOT.edit_message_text(text, chat_id=battle["chat_id"], message_id=message_id, parse_mode="Markdown")
    except: pass
    del active_battles[message_id]

def finish_battle_defeat(message_id):
    battle = active_battles[message_id]
    loss = -200 if battle["diff"].get("no_cups") else -20
    update_user_stats(battle["user_id"], trophies=loss)
    text = f"💀 **Поражение!** Потеряно {abs(loss)} кубков"
    try: BOT.edit_message_text(text, chat_id=battle["chat_id"], message_id=message_id, parse_mode="Markdown")
    except: pass
    del active_battles[message_id]

# --- БОСС ---
@BOT.message_handler(func=lambda m: m.text == "👹 Босс")
def boss_fight(message):
    user = get_user(message.from_user.id)
    team = get_equipped_team(message.from_user.id)
    if not team: return BOT.send_message(message.chat.id, "❌ Отряд пуст!")
    if time.time() - user["last_boss"] < 3600:
        rem = int(3600 - (time.time() - user["last_boss"]))
        return BOT.send_message(message.chat.id, f"⏳ {rem//60} мин до босса")
    
    msg = BOT.send_message(message.chat.id, "👹 *Босс пробуждается...*")
    player_max_hp = sum(c['hp'] for c in team)
    player_atk = sum(c['atk'] for c in team) * (1 + user["mult_atk_lvl"] * 0.15)
    boss_hp = int(player_max_hp * 1.5)
    boss_atk = int(player_atk * 0.3) or 5
    
    battle = {
        "chat_id": msg.chat.id, "message_id": msg.message_id, "user_id": message.from_user.id,
        "player_hp": player_max_hp, "player_max_hp": player_max_hp, "final_player_atk": int(player_atk),
        "boss_hp": boss_hp, "boss_max_hp": boss_hp, "boss_atk": boss_atk, "hit_counter": 0
    }
    active_battles[f"boss_{msg.message_id}"] = battle
    process_boss_round(f"boss_{msg.message_id}")

def process_boss_round(battle_id):
    if battle_id not in active_battles: return
    battle = active_battles[battle_id]
    battle["hit_counter"] += 1
    damage = battle["final_player_atk"]
    
    has_ultra = any(c["name"] == "Ультра-Некрос" for c in get_equipped_team(battle["user_id"]))
    has_exclusive = any(c["name"] in ["Король-лич", "Первородный хаос"] for c in get_equipped_team(battle["user_id"]))
    
    if has_ultra and battle["hit_counter"] % 3 == 0:
        damage *= 5
    if has_exclusive:
        damage = int(damage * 1.5)
    
    battle["boss_hp"] -= damage
    if battle["boss_hp"] <= 0:
        gold_mult = 1 + get_user(battle["user_id"])["mult_gold_lvl"] * 0.25
        gold = int(500 * gold_mult)
        update_user_stats(battle["user_id"], gold=gold, trophies=80, pass_exp=75, last_boss=time.time())
        text = f"🏆 **Босс повержен!**\n💰 +{gold} золота\n🏆 +80 кубков"
        try: BOT.edit_message_text(text, chat_id=battle["chat_id"], message_id=battle["message_id"], parse_mode="Markdown")
        except: pass
        del active_battles[battle_id]
        return
    
    battle["player_hp"] -= battle["boss_atk"]
    if battle["player_hp"] <= 0:
        update_user_stats(battle["user_id"], last_boss=time.time())
        text = "💥 **Поражение от босса!**"
        try: BOT.edit_message_text(text, chat_id=battle["chat_id"], message_id=battle["message_id"], parse_mode="Markdown")
        except: pass
        del active_battles[battle_id]
        return
    
    p_bar = generate_hp_bar(battle["player_hp"], battle["player_max_hp"])
    b_bar = generate_hp_bar(battle["boss_hp"], battle["boss_max_hp"])
    text = f"👹 **БОСС**\n\n🛡 {battle['player_hp']}/{battle['player_max_hp']}\n{p_bar}\n\n🔥 {battle['boss_hp']}/{battle['boss_max_hp']}\n{b_bar}\n⚔️ Урон: {battle['boss_atk']}"
    try: BOT.edit_message_text(text, chat_id=battle["chat_id"], message_id=battle["message_id"], parse_mode="Markdown")
    except: pass
    threading.Timer(1.0, process_boss_round, args=[battle_id]).start()

# --- БОЕВОЙ ПАСС ---
@BOT.message_handler(func=lambda m: m.text == "🎫 Боевой Пасс")
def view_battle_pass(message):
    user = get_user(message.from_user.id)
    needed = get_pass_exp_required(user["pass_lvl"])
    progress = f"{user['pass_exp']}/{needed} XP" if user["pass_lvl"] < 15 else "МАКСИМУМ ✅"
    text = f"🎫 **БОЕВОЙ ПАСС**\nУровень: {user['pass_lvl']}/15\nПрогресс: {progress}\n\n📜 Награды:\n"
    for lvl in range(1, 16):
        status = "✅" if user["pass_lvl"] >= lvl else f"🔒 {get_pass_exp_required(lvl)} XP"
        text += f"▪️ Ур.{lvl}: {PASS_REWARDS[lvl]['name']} — {status}\n"
    BOT.send_message(message.chat.id, text, parse_mode="Markdown")

# --- КРАФТ ---
@BOT.message_handler(func=lambda m: m.text == "🔧 Крафт")
def craft_menu(message):
    user = get_user(message.from_user.id)
    text = f"🔧 **КРАФТ: ПЕРВОРОДНЫЙ ХАОС**\n💰 Стоимость: 100000 золота\n\nТребуется:\n▪️ Ультра-Некрос (УЛЬТРА) x1\n▪️ 2 Божественных юнита\n▪️ 3 Мифических юнита"
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("⚡ КРАФТНУТЬ", callback_data="craft_chaos"))
    BOT.send_message(message.chat.id, text, parse_mode="Markdown", reply_markup=kb)

@BOT.callback_query_handler(func=lambda c: c.data == "craft_chaos")
def craft_chaos(callback):
    user = get_user(callback.from_user.id)
    if user["gold"] < 100000:
        return BOT.answer_callback_query(callback.id, "❌ Нужно 100000 золота!", show_alert=True)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Проверка Ультра-Некроса
    cursor.execute("SELECT COUNT(*) FROM inventory WHERE user_id = ? AND card_name = 'Ультра-Некрос' AND is_equipped = 0", (callback.from_user.id,))
    if cursor.fetchone()[0] < 1:
        return_db_connection(conn)
        return BOT.answer_callback_query(callback.id, "❌ Нет Ультра-Некроса!", show_alert=True)
    
    # Проверка божественных
    cursor.execute("SELECT COUNT(*) FROM inventory WHERE user_id = ? AND rarity = 'Божественная' AND is_equipped = 0", (callback.from_user.id,))
    if cursor.fetchone()[0] < 2:
        return_db_connection(conn)
        return BOT.answer_callback_query(callback.id, "❌ Нужно 2 Божественных юнита!", show_alert=True)
    
    # Проверка мифических
    cursor.execute("SELECT COUNT(*) FROM inventory WHERE user_id = ? AND rarity = 'Мифическая' AND is_equipped = 0", (callback.from_user.id,))
    if cursor.fetchone()[0] < 3:
        return_db_connection(conn)
        return BOT.answer_callback_query(callback.id, "❌ Нужно 3 Мифических юнита!", show_alert=True)
    
    # Тратим ресурсы
    cursor.execute("DELETE FROM inventory WHERE user_id = ? AND card_name = 'Ультра-Некрос' AND is_equipped = 0 LIMIT 1", (callback.from_user.id,))
    cursor.execute("DELETE FROM inventory WHERE user_id = ? AND rarity = 'Божественная' AND is_equipped = 0 LIMIT 2", (callback.from_user.id,))
    cursor.execute("DELETE FROM inventory WHERE user_id = ? AND rarity = 'Мифическая' AND is_equipped = 0 LIMIT 3", (callback.from_user.id,))
    cursor.execute("UPDATE users SET gold = gold - 100000 WHERE user_id = ?", (callback.from_user.id,))
    
    # Создаем
    unit = UNITS["Первородный хаос"]
    cursor.execute("INSERT INTO inventory (user_id, card_name, rarity, level, hp, atk, variant) VALUES (?, ?, ?, 1, ?, ?, ?)",
                  (callback.from_user.id, "Первородный хаос", "Эксклюзив", unit["hp"], unit["atk"], "обычный"))
    conn.commit()
    return_db_connection(conn)
    clear_user_cache(callback.from_user.id)
    
    BOT.answer_callback_query(callback.id, "👑 ПЕРВОРОДНЫЙ ХАОС СОЗДАН!", show_alert=True)
    BOT.send_message(callback.message.chat.id, 
                    f"👑 **КРАФТ УСПЕШЕН!**\nСоздан: Первородный хаос (Эксклюзив)\n❤️ HP: {unit['hp']}\n⚔️ ATK: {unit['atk']}")

# --- ИНДЕКС ---
@BOT.message_handler(func=lambda m: m.text == "📖 Индекс")
def index_msg(message):
    send_index(message.chat.id, 0)

def send_index(chat_id, page=0):
    limit, total_pages = 10, (len(INDEX_UNITS)+9)//10
    page = max(0, min(page, total_pages-1))
    start, end = page*limit, min((page+1)*limit, len(INDEX_UNITS))
    
    text = f"📖 **ИНДЕКС (Стр.{page+1}/{total_pages}):**"
    kb = types.InlineKeyboardMarkup(row_width=1)
    for u_name in INDEX_UNITS[start:end]:
        rar = UNITS[u_name]["rarity"]
        kb.add(types.InlineKeyboardButton(f"{RARITY_COLORS.get(rar,'')} [{rar}] {u_name}", callback_data=f"idxinfo_{UNITS_LIST.index(u_name)}_{page}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"idxpage_{page-1}"))
    if page < total_pages-1: nav.append(types.InlineKeyboardButton("➡️", callback_data=f"idxpage_{page+1}"))
    if nav: kb.row(*nav)
    BOT.send_message(chat_id, text, reply_markup=kb)

@BOT.callback_query_handler(func=lambda c: c.data.startswith("idxpage_"))
def index_page_cb(callback):
    page = int(callback.data.split("_")[1])
    try: BOT.delete_message(callback.message.chat.id, callback.message.message_id)
    except: pass
    send_index(callback.message.chat.id, page)

@BOT.callback_query_handler(func=lambda c: c.data.startswith("idxinfo_"))
def index_info_cb(callback):
    _, u_idx, from_page = callback.data.split("_")
    u_name = UNITS_LIST[int(u_idx)]
    unit = UNITS[u_name]
    text = f"🔬 **{RARITY_COLORS.get(unit['rarity'],'')} {u_name}**\n📊 {unit['rarity']}\n❤️ HP: {unit['hp']}\n⚔️ ATK: {unit['atk']}"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"idxpage_{from_page}"))
    safe_edit(callback.message.chat.id, callback.message.message_id, text, reply_markup=kb)

# --- ТОП ---
@BOT.message_handler(func=lambda m: m.text == "🏆 Топ")
def show_top(message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, trophies FROM leaderboard ORDER BY trophies DESC LIMIT 10")
    rows = cursor.fetchall()
    return_db_connection(conn)
    
    text = "🏆 **НЕДЕЛЬНЫЙ РЕЙТИНГ**\n\n"
    text += f"⏳ {get_week_time_left()}\n\n🏅 Награды: 150к/100к/50к золота\n\n📊 Топ:\n"
    for i, r in enumerate(rows, 1):
        medal = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
        text += f"{medal} {html.escape(r[0] or 'Unknown')} — {r[1]} 🏆\n"
    BOT.send_message(message.chat.id, text, parse_mode="HTML")

# --- АДМИН ПАНЕЛЬ ---
@BOT.message_handler(func=lambda m: m.text == "👑 Админ Панель" and m.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def admin_panel(message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("⚙️ Ресурсы", "🔮 Удача", "💀 Ультра-Кризис", "⏰ Босс Таймер", "🃏 Галерея", "🏆 Сброс Топа", "📢 Сообщение", "⬅️ Назад")
    BOT.send_message(message.chat.id, "👑 **Админ Панель**", reply_markup=kb)

@BOT.message_handler(func=lambda m: m.text == "⚙️ Ресурсы" and m.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def admin_resources(message):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("👤 Золото игроку", callback_data="wiz_gold"),
        types.InlineKeyboardButton("👤 Кубки игроку", callback_data="wiz_cups"),
        types.InlineKeyboardButton("📢 Золото ВСЕМ", callback_data="wiz_gold_all"),
        types.InlineKeyboardButton("📢 Кубки ВСЕМ", callback_data="wiz_cups_all")
    )
    BOT.send_message(message.chat.id, "🎛 **Ресурсы**", reply_markup=kb)

@BOT.message_handler(func=lambda m: m.text == "🔮 Удача" and m.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def admin_luck(message):
    luck = get_setting("luck_multiplier", "1.0")
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("⚙️ Задать", callback_data="luck_set"), types.InlineKeyboardButton("🔄 Сбросить", callback_data="luck_reset"))
    BOT.send_message(message.chat.id, f"🔮 Удача: {luck}x", reply_markup=kb)

@BOT.message_handler(func=lambda m: m.text == "💀 Ультра-Кризис" and m.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def admin_ultra(message):
    state = get_setting("ultra_mode", "0")
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🟢 Вкл", callback_data="ultra_on"),
        types.InlineKeyboardButton("🔴 Выкл", callback_data="ultra_off")
    )
    BOT.send_message(message.chat.id, f"💀 Ультра-Кризис: {'🟢 ВКЛ' if state=='1' else '🔴 ВЫКЛ'}", reply_markup=kb)

@BOT.message_handler(func=lambda m: m.text == "⏰ Босс Таймер" and m.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def admin_boss_timer(message):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("🕒 Сбросить СВОЙ", callback_data="boss_reset_self"),
        types.InlineKeyboardButton("🌍 Сбросить ВСЕМ", callback_data="boss_reset_all")
    )
    BOT.send_message(message.chat.id, "⏰ **Босс Таймер**", reply_markup=kb)

@BOT.message_handler(func=lambda m: m.text == "🃏 Галерея" and m.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def admin_gallery(message):
    render_gallery(message, 0)

def render_gallery(message, page):
    limit, total_pages = 8, (len(UNITS_LIST)+7)//8
    page = max(0, min(page, total_pages-1))
    start, end = page*limit, min((page+1)*limit, len(UNITS_LIST))
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    for u_name in UNITS_LIST[start:end]:
        u = UNITS[u_name]
        kb.add(types.InlineKeyboardButton(f"{RARITY_COLORS.get(u['rarity'],'')} [{u['rarity']}] {u_name}", 
                                         callback_data=f"give_{UNITS_LIST.index(u_name)}"))
    
    nav = []
    if page > 0: nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"galpage_{page-1}"))
    nav.append(types.InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="void"))
    if page < total_pages-1: nav.append(types.InlineKeyboardButton("➡️", callback_data=f"galpage_{page+1}"))
    kb.row(*nav)
    BOT.send_message(message.chat.id, "🃏 **Галерея**", reply_markup=kb)

@BOT.message_handler(func=lambda m: m.text == "🏆 Сброс Топа" and m.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def admin_reset_top(message):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🏆 Сбросить", callback_data="reset_top"))
    BOT.send_message(message.chat.id, "⚠️ Сбросить рейтинг?", reply_markup=kb)

@BOT.message_handler(func=lambda m: m.text == "📢 Сообщение" and m.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def admin_message(message):
    msg = BOT.send_message(message.chat.id, "📢 Введите сообщение:")
    BOT.register_next_step_handler(msg, admin_send_global)

# --- АДМИН КОЛБЭКИ ---
@BOT.callback_query_handler(func=lambda c: c.data == "wiz_gold" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def wiz_gold(callback):
    msg = BOT.send_message(callback.message.chat.id, "Введите ID игрока или 'я':")
    BOT.register_next_step_handler(msg, wiz_gold_step2)

def wiz_gold_step2(message):
    if message.from_user.id not in [ADMIN_ID, ADMIN_ID_2]: return
    try:
        pid = message.from_user.id if message.text.lower() == "я" else int(message.text)
        get_user(pid)
        msg = BOT.send_message(message.chat.id, f"Сколько золота для {pid}?")
        BOT.register_next_step_handler(msg, wiz_gold_final, pid)
    except: BOT.send_message(message.chat.id, "❌ Неверный ID")

def wiz_gold_final(message, pid):
    if message.from_user.id not in [ADMIN_ID, ADMIN_ID_2]: return
    try:
        val = int(message.text)
        update_user_stats(pid, gold=val)
        BOT.send_message(message.chat.id, f"✅ {pid} +{val} золота")
    except: BOT.send_message(message.chat.id, "❌ Неверное число")

@BOT.callback_query_handler(func=lambda c: c.data == "wiz_cups" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def wiz_cups(callback):
    msg = BOT.send_message(callback.message.chat.id, "Введите ID игрока или 'я':")
    BOT.register_next_step_handler(msg, wiz_cups_step2)

def wiz_cups_step2(message):
    if message.from_user.id not in [ADMIN_ID, ADMIN_ID_2]: return
    try:
        pid = message.from_user.id if message.text.lower() == "я" else int(message.text)
        get_user(pid)
        msg = BOT.send_message(message.chat.id, f"Сколько кубков для {pid}?")
        BOT.register_next_step_handler(msg, wiz_cups_final, pid)
    except: BOT.send_message(message.chat.id, "❌ Неверный ID")

def wiz_cups_final(message, pid):
    if message.from_user.id not in [ADMIN_ID, ADMIN_ID_2]: return
    try:
        val = int(message.text)
        update_user_stats(pid, trophies=val)
        BOT.send_message(message.chat.id, f"✅ {pid} +{val} кубков")
    except: BOT.send_message(message.chat.id, "❌ Неверное число")

@BOT.callback_query_handler(func=lambda c: c.data == "wiz_gold_all" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def wiz_gold_all(callback):
    msg = BOT.send_message(callback.message.chat.id, "Сколько золота ВСЕМ?")
    BOT.register_next_step_handler(msg, wiz_gold_all_final)

def wiz_gold_all_final(message):
    if message.from_user.id not in [ADMIN_ID, ADMIN_ID_2]: return
    try:
        val = int(message.text)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET gold = gold + ?", (val,))
        conn.commit()
        return_db_connection(conn)
        BOT.send_message(message.chat.id, f"✅ Всем +{val} золота")
        notify_all_players(f"💰 Админ выдал всем {val} золота!")
    except: BOT.send_message(message.chat.id, "❌ Неверное число")

@BOT.callback_query_handler(func=lambda c: c.data == "wiz_cups_all" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def wiz_cups_all(callback):
    msg = BOT.send_message(callback.message.chat.id, "Сколько кубков ВСЕМ?")
    BOT.register_next_step_handler(msg, wiz_cups_all_final)

def wiz_cups_all_final(message):
    if message.from_user.id not in [ADMIN_ID, ADMIN_ID_2]: return
    try:
        val = int(message.text)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET trophies = trophies + ?", (val,))
        conn.commit()
        return_db_connection(conn)
        BOT.send_message(message.chat.id, f"✅ Всем +{val} кубков")
        notify_all_players(f"🏆 Админ выдал всем {val} кубков!")
    except: BOT.send_message(message.chat.id, "❌ Неверное число")

@BOT.callback_query_handler(func=lambda c: c.data == "luck_set" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def luck_set(callback):
    msg = BOT.send_message(callback.message.chat.id, "Введите множитель удачи (например 2.0):")
    BOT.register_next_step_handler(msg, luck_set_final)

def luck_set_final(message):
    if message.from_user.id not in [ADMIN_ID, ADMIN_ID_2]: return
    try:
        val = float(message.text)
        if val <= 0: raise ValueError
        set_setting("luck_multiplier", str(val))
        BOT.send_message(message.chat.id, f"✅ Удача: {val}x")
        notify_all_players(f"🔮 Удача изменена на {val}x!")
    except: BOT.send_message(message.chat.id, "❌ Неверное значение")

@BOT.callback_query_handler(func=lambda c: c.data == "luck_reset" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def luck_reset(callback):
    set_setting("luck_multiplier", "1.0")
    BOT.answer_callback_query(callback.id, "✅ Удача сброшена до 1.0x", show_alert=True)
    notify_all_players("🔮 Удача сброшена до 1.0x")

@BOT.callback_query_handler(func=lambda c: c.data == "ultra_on" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def ultra_on(callback):
    set_setting("ultra_mode", "1")
    BOT.answer_callback_query(callback.id, "💀 Ультра-Кризис ВКЛ", show_alert=True)
    notify_all_players("💀 **АКТИВИРОВАН УЛЬТРА-КРИЗИС!**")

@BOT.callback_query_handler(func=lambda c: c.data == "ultra_off" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def ultra_off(callback):
    set_setting("ultra_mode", "0")
    BOT.answer_callback_query(callback.id, "💀 Ультра-Кризис ВЫКЛ", show_alert=True)
    notify_all_players("💀 Ультра-Кризис отключен")

@BOT.callback_query_handler(func=lambda c: c.data == "boss_reset_self" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def boss_reset_self(callback):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_boss = '0' WHERE user_id = ?", (callback.from_user.id,))
    conn.commit()
    return_db_connection(conn)
    clear_user_cache(callback.from_user.id)
    BOT.answer_callback_query(callback.id, "✅ Таймер сброшен", show_alert=True)

@BOT.callback_query_handler(func=lambda c: c.data == "boss_reset_all" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def boss_reset_all(callback):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_boss = '0'")
    conn.commit()
    return_db_connection(conn)
    BOT.answer_callback_query(callback.id, "✅ ВСЕМ сброшен", show_alert=True)
    notify_all_players("⏰ Админ сбросил таймер Босса!")

@BOT.callback_query_handler(func=lambda c: c.data == "reset_top" and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def reset_top(callback):
    reset_leaderboard()
    BOT.answer_callback_query(callback.id, "🏆 Рейтинг сброшен", show_alert=True)

@BOT.callback_query_handler(func=lambda c: c.data.startswith("give_") and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def give_unit(callback):
    idx = int(callback.data.split("_")[1])
    u_name = UNITS_LIST[idx]
    u_data = UNITS[u_name]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO inventory (user_id, card_name, rarity, level, hp, atk, variant) VALUES (?, ?, ?, 1, ?, ?, ?)",
                  (callback.from_user.id, u_name, u_data["rarity"], u_data["hp"], u_data["atk"], "обычный"))
    conn.commit()
    return_db_connection(conn)
    BOT.answer_callback_query(callback.id, f"✅ {u_name} получен!", show_alert=True)

@BOT.callback_query_handler(func=lambda c: c.data.startswith("galpage_") and c.from_user.id in [ADMIN_ID, ADMIN_ID_2])
def gallery_page(callback):
    page = int(callback.data.split("_")[1])
    try: BOT.delete_message(callback.message.chat.id, callback.message.message_id)
    except: pass
    render_gallery(callback.message, page)

@BOT.callback_query_handler(func=lambda c: c.data == "void")
def void(callback):
    BOT.answer_callback_query(callback.id)

def admin_send_global(message):
    if message.from_user.id not in [ADMIN_ID, ADMIN_ID_2]: return
    notify_all_players(f"📢 **ОБЪЯВЛЕНИЕ**\n{message.text}")

# --- ХЕЛПЕР ---
def safe_edit(chat_id, message_id, text, reply_markup=None):
    try:
        BOT.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown", reply_markup=reply_markup)
    except ApiTelegramException as e:
        if "message is not modified" not in str(e):
            pass

# --- ЗАПУСК ---
if __name__ == '__main__':
    init_db()
    init_leaderboard()
    print("=== [ФЭНТЕЗИ-RPG БОТ ЗАПУЩЕН] ===")
    print(f"=== [АДМИНЫ: {ADMIN_ID}, {ADMIN_ID_2}] ===")
    BOT.infinity_polling()