import os
import asyncio
import re
import time
import asyncpg
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "8707690675:AAGoLcN1fsuE3fbVqJloAG9EBzy3l8Vqj9Y")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_20wOVsdFEUmg@ep-delicate-sun-b1x8znjr-pooler.c-5.eu-central-1.aws.neon.tech/neondb?sslmode=require")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AdminAuth(StatesGroup):
    waiting_for_password = State()

async def get_db_pool():
    return await asyncpg.create_pool(dsn=DATABASE_URL)

async def setup_db(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_codes (code VARCHAR(6) PRIMARY KEY, uuid VARCHAR(36) NOT NULL, expires_at BIGINT NOT NULL);
            CREATE TABLE IF NOT EXISTS linked_players (uuid VARCHAR(36) PRIMARY KEY, telegram_id BIGINT NOT NULL, created_at BIGINT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings (key VARCHAR(50) PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS admins (telegram_id BIGINT PRIMARY KEY, created_at BIGINT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_messages (id SERIAL PRIMARY KEY, player_name VARCHAR(32) NOT NULL, message TEXT NOT NULL, sent INT DEFAULT 0);
            CREATE TABLE IF NOT EXISTS pending_commands (id SERIAL PRIMARY KEY, command TEXT NOT NULL);
        """)

async def chat_broadcaster(pool):
    while True:
        try:
            async with pool.acquire() as conn:
                messages = await conn.fetch("SELECT id, player_name, message FROM chat_messages WHERE sent = 0")
                if messages:
                    admins_rows = await conn.fetch("SELECT telegram_id FROM admins")
                    admins = [row['telegram_id'] for row in admins_rows]

                    for msg in messages:
                        if admins:
                            formatted_text = f"💬 **[MC] {msg['player_name']}**: {msg['message']}"
                            for admin_id in admins:
                                try:
                                    await bot.send_message(admin_id, formatted_text, parse_mode="Markdown")
                                except Exception:
                                    pass
                        await conn.execute("UPDATE chat_messages SET sent = 1 WHERE id = $1", msg['id'])
        except Exception as e:
            print(f"Ошибка трансляции чата: {e}")
        await asyncio.sleep(1)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer("Привет! Назови шестизначный код, который ты получил на сервере при вводе команды /link.")

@dp.message(Command("t0adp"))
async def cmd_set_password(message: types.Message):
    telegram_id = message.from_user.id
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        await message.answer("Использование: `/t0adp <ваш_новый_пароль>`", parse_mode="Markdown")
        return

    new_password = args[1].strip()
    pool = dp["db_pool"]

    async with pool.acquire() as conn:
        existing_pass = await conn.fetchrow("SELECT value FROM settings WHERE key = 'admin_password'")
        if existing_pass:
            is_admin = await conn.fetchrow("SELECT telegram_id FROM admins WHERE telegram_id = $1", telegram_id)
            if not is_admin:
                await message.answer("❌ Менять пароль могут только авторизованные администраторы.")
                return

        await conn.execute("INSERT INTO settings (key, value) VALUES ('admin_password', $1) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", new_password)
        await message.answer("✅ Пароль администратора успешно установлен!")

@dp.message(Command("t0ad"))
async def cmd_t0ad(message: types.Message, state: FSMContext):
    telegram_id = message.from_user.id
    pool = dp["db_pool"]

    async with pool.acquire() as conn:
        if await conn.fetchrow("SELECT telegram_id FROM admins WHERE telegram_id = $1", telegram_id):
            await message.answer("🔒 Вы уже авторизованы как администратор!\n\nВам доступен чат сервера и команда `/ban <ник> [причина]`.", parse_mode="Markdown")
            return
        if not await conn.fetchrow("SELECT value FROM settings WHERE key = 'admin_password'"):
            await message.answer("❌ Пароль еще не задан. Установите его командой `/t0adp <пароль>`.", parse_mode="Markdown")
            return

    await state.set_state(AdminAuth.waiting_for_password)
    await message.answer("🔑 Введите пароль администратора:")

@dp.message(AdminAuth.waiting_for_password)
async def process_admin_password(message: types.Message, state: FSMContext):
    password_input = message.text.strip()
    telegram_id = message.from_user.id
    pool = dp["db_pool"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'admin_password'")
        if row and password_input == row['value']:
            now = int(time.time())
            await conn.execute("INSERT INTO admins (telegram_id, created_at) VALUES ($1, $2) ON CONFLICT (telegram_id) DO NOTHING", telegram_id, now)
            await message.answer("✅ **Успешная авторизация!**\n\nТеперь вам транслируется чат сервера. Вы можете банить игроков командой:\n`/ban <ник> [причина]`", parse_mode="Markdown")
        else:
            await message.answer("❌ Неверный пароль. Доступ отклонен.")

    await state.clear()

@dp.message(Command("ban"))
async def cmd_ban(message: types.Message):
    telegram_id = message.from_user.id
    pool = dp["db_pool"]

    async with pool.acquire() as conn:
        if not await conn.fetchrow("SELECT telegram_id FROM admins WHERE telegram_id = $1", telegram_id):
            await message.answer("❌ У вас нет прав администратора. Авторизуйтесь через /t0ad.")
            return

    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("Использование: `/ban <ник_игрока> [причина]`", parse_mode="Markdown")
        return

    player_to_ban = args[1]
    reason = args[2] if len(args) > 2 else "Забанен через Telegram Admin Panel"
    command_to_execute = f"ban {player_to_ban} {reason}"

    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO pending_commands (command) VALUES ($1)", command_to_execute)

    await message.answer(f"🔨 Отправлена команда на бан игрока `{player_to_ban}`.\nПричина: _{reason}_", parse_mode="Markdown")

@dp.message(F.text.func(lambda text: bool(re.fullmatch(r'\d{6}', text.strip()))))
async def process_code(message: types.Message):
    code = message.text.strip()
    telegram_id = message.from_user.id
    now = int(time.time())
    pool = dp["db_pool"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT uuid FROM pending_codes WHERE code = $1 AND expires_at > $2", code, now)
        if not row:
            await message.answer("❌ Неверный или истекший код. Запросите новый код на сервере через /link.")
            return

        uuid = row['uuid']
        await conn.execute("INSERT INTO linked_players (uuid, telegram_id, created_at) VALUES ($1, $2, $3) ON CONFLICT (uuid) DO UPDATE SET telegram_id = EXCLUDED.telegram_id", uuid, telegram_id, now)
        await conn.execute("DELETE FROM pending_codes WHERE code = $1", code)

        await message.answer(f"✅ **Аккаунт успешно привязан!**\n\nВаш UUID: `{uuid}`", parse_mode="Markdown")

async def main():
    pool = await get_db_pool()
    dp["db_pool"] = pool
    await setup_db(pool)
    asyncio.create_task(chat_broadcaster(pool))
    print("Telegram бот запущен на облачном сервере...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())