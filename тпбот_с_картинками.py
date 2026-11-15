import asyncio
import html
import logging
from pathlib import Path
from urllib.parse import quote

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8150306808:AAGnk6RNgBee-FtLsndmGO4cptqFi0KOe-w"
ADMIN_CHAT_ID = 8727205564  # куда приходят заявки (твой id или id группы)

# Операторы поддержки: название кнопки -> ссылка или юз
OPERATORS = {
    "👩 Оператор (Анна)": "https://t.me/usupoq",
    "👨 Оператор (Иван)": "https://t.me/Noikss",
}

# Криптовалюты и сети (поменяй под себя)
CRYPTO = {
    "Биткоин": ["Bitcoin"],
    "Эфириум": ["ERC20", "Arbitrum", "Optimism"],
    "Юсдт": ["TRC20", "ERC20", "BEP20", "TON"],
    "Солано": ["Solana"],
    "Бимби": ["BEP20", "ERC20"],
}

BANKS = ["Дисконт", "Поалим", "Леуми"]

# True — дополнительно присылать каждую заявку в ADMIN_CHAT_ID
# False — бот только показывает пользователю текст для копирования
SEND_TO_ADMIN = False

# Реквизиты для ПОПОЛНЕНИЯ (то, что пользователь копирует одним нажатием)
DEP_CRYPTO = {  # (монета, сеть): адрес
    ("Биткоин", "Bitcoin"): "ВСТАВЬ_АДРЕС_BTC",
    ("Эфириум", "ERC20"): "ВСТАВЬ_АДРЕС_ETH",
    ("Эфириум", "Arbitrum"): "ВСТАВЬ_АДРЕС_ETH",
    ("Эфириум", "Optimism"): "ВСТАВЬ_АДРЕС_ETH",
    ("Юсдт", "TRC20"): "ВСТАВЬ_АДРЕС_USDT_TRC20",
    ("Юсдт", "ERC20"): "ВСТАВЬ_АДРЕС_USDT_ERC20",
    ("Юсдт", "BEP20"): "ВСТАВЬ_АДРЕС_USDT_BEP20",
    ("Юсдт", "TON"): "ВСТАВЬ_АДРЕС_USDT_TON",
    ("Солано", "Solana"): "ВСТАВЬ_АДРЕС_SOL",
    ("Бимби", "BEP20"): "ВСТАВЬ_АДРЕС",
    ("Бимби", "ERC20"): "ВСТАВЬ_АДРЕС",
}
DEP_PHONE = {"Бит": "+972XXXXXXXXX", "Эйбокс": "+972XXXXXXXXX"}
DEP_BANK = {  # банк: реквизиты
    "Дисконт": "ВСТАВЬ_РЕКВИЗИТЫ",
    "Поалим": "ВСТАВЬ_РЕКВИЗИТЫ",
    "Леуми": "ВСТАВЬ_РЕКВИЗИТЫ",
}
# ===============================================

logging.basicConfig(level=logging.INFO)
dp = Dispatcher(storage=MemoryStorage())

ASSET_DIR = Path(__file__).with_name("assets")
ASSETS = {
    "menu": ASSET_DIR / "menu.png",
    "withdraw": ASSET_DIR / "withdraw.png",
    "deposit": ASSET_DIR / "deposit.png",
    "register": ASSET_DIR / "register.png",
    "support": ASSET_DIR / "support.png",
}


class Form(StatesGroup):
    wallet = State()
    phone = State()
    address = State()


def code(x) -> str:
    """Моноширинный текст: при нажатии в Телеграме копируется целиком."""
    return f"<code>{html.escape(str(x))}</code>"


def kb(rows, back=None):
    """rows: список (текст, callback_data). По одной кнопке в ряд."""
    b = InlineKeyboardBuilder()
    for text, data in rows:
        b.button(text=text, callback_data=data)
    if back:
        b.button(text="⬅️ Назад", callback_data=back)
    b.adjust(1)
    return b.as_markup()


def prefilled_url(base: str, text: str) -> str:
    """Ссылка на чат с оператором, где текст уже вставлен в поле ввода."""
    if base.startswith("@"):
        base = "https://t.me/" + base[1:]
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}text={quote(text)}"


def result_kb(summary: str):
    """Кнопки операторов: открывают лс с уже вставленным текстом + в меню."""
    b = InlineKeyboardBuilder()
    for title, url in OPERATORS.items():
        b.button(text=title, url=prefilled_url(url, summary))
    b.button(text="🏠 В меню", callback_data="menu")
    b.adjust(1)
    return b.as_markup()


async def edit_content(message: Message, text: str, reply_markup=None):
    """Редактирует и обычное сообщение, и подпись под картинкой."""
    if message.photo:
        await message.edit_caption(caption=text, reply_markup=reply_markup)
    else:
        await message.edit_text(text, reply_markup=reply_markup)


async def set_content(c: CallbackQuery, text: str, reply_markup=None):
    """Обновляет текущий экран, сохраняя выбранную тематическую картинку."""
    await edit_content(c.message, text, reply_markup)


async def show_panel(c: CallbackQuery, asset: str, caption: str, reply_markup=None):
    """Показывает красивую картинку экрана без создания лишних сообщений."""
    path = ASSETS[asset]
    if not path.is_file():
        logging.warning("Не найдена картинка интерфейса: %s", path)
        await set_content(c, caption, reply_markup)
        return

    media = InputMediaPhoto(media=FSInputFile(path), caption=caption)
    if c.message.photo:
        await c.message.edit_media(media=media, reply_markup=reply_markup)
    else:
        await c.message.delete()
        await c.bot.send_photo(
            chat_id=c.message.chat.id,
            photo=FSInputFile(path),
            caption=caption,
            reply_markup=reply_markup,
        )


async def finish(target, user, bot: Bot, summary: str, edit: bool = False):
    """Итог + выбор оператора. Клик по оператору открывает лс с готовым текстом."""
    text = (
        "✅ <b>Готово!</b> Ваши данные собраны:\n\n"
        f"{code(summary)}\n\n"
        "Выберите оператора — откроется чат с уже вставленным сообщением, "
        "останется только нажать «Отправить»."
    )
    if SEND_TO_ADMIN:
        await send_to_admin(bot, user, code(summary))
    if edit:
        await edit_content(target, text, result_kb(summary))
    else:
        await target.answer(text, reply_markup=result_kb(summary))


def main_menu():
    return kb([
        ("💸 Вывод", "withdraw"),
        ("➕ Пополнение", "deposit"),
        ("📝 Регистрация", "register"),
        ("🛟 Поддержка", "support"),
    ])


def user_tag(obj) -> str:
    u = obj.from_user
    name = f"@{u.username}" if u.username else u.full_name
    return f"{name} (id {u.id})"


async def send_to_admin(bot: Bot, user, text: str):
    u = user
    name = f"@{u.username}" if u.username else u.full_name
    await bot.send_message(
        ADMIN_CHAT_ID,
        f"📥 Новая заявка\nОт: {html.escape(name)} (id {u.id})\n\n{text}",
    )


# ---------- /start и главное меню ----------
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer_photo(
        photo=FSInputFile(ASSETS["menu"]),
        caption="✨ <b>Добро пожаловать!</b>\n\nВыберите нужное действие:",
        reply_markup=main_menu(),
    )


@dp.callback_query(F.data == "menu")
async def menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_panel(
        c,
        "menu",
        "✨ <b>Главное меню</b>\n\nВыберите нужное действие:",
        main_menu(),
    )
    await c.answer()


# ---------- Вывод ----------
@dp.callback_query(F.data == "withdraw")
async def withdraw(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_panel(c, "withdraw", "💸 <b>Вывод средств</b>\n\nВыберите способ вывода:", kb([
        ("Криптовалюта", "w_crypto"),
        ("Бит", "w_bit"),
        ("Эйбокс", "w_abox"),
        ("Курьер", "w_courier"),
        ("Банковский код", "w_bank"),
    ], back="menu"))
    await c.answer()


# --- Криптовалюта ---
@dp.callback_query(F.data == "w_crypto")
async def w_crypto(c: CallbackQuery):
    rows = [(name, f"coin:{name}") for name in CRYPTO]
    await set_content(c, "Выберите криптовалюту:", kb(rows, back="withdraw"))
    await c.answer()


@dp.callback_query(F.data.startswith("coin:"))
async def coin_chosen(c: CallbackQuery, state: FSMContext):
    coin = c.data.split(":", 1)[1]
    await state.update_data(method="Криптовалюта", coin=coin)
    await state.set_state(Form.wallet)
    await set_content(c, f"Вы выбрали: {coin}\n\nВведите адрес кошелька:")
    await c.answer()


@dp.message(Form.wallet)
async def got_wallet(m: Message, state: FSMContext):
    await state.update_data(wallet=m.text.strip())
    data = await state.get_data()
    nets = CRYPTO[data["coin"]]
    rows = [(n, f"net:{i}") for i, n in enumerate(nets)]
    await m.answer("Выберите сеть:", reply_markup=kb(rows))


@dp.callback_query(F.data.startswith("net:"))
async def net_chosen(c: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if not data.get("coin"):
        await c.answer("Сессия устарела, начните заново: /start", show_alert=True)
        return
    net = CRYPTO[data["coin"]][int(c.data.split(":")[1])]
    summary = (f"Вывод: Криптовалюта\nМонета: {data['coin']}\n"
               f"Сеть: {net}\nКошелёк: {data['wallet']}")
    await state.clear()
    await finish(c.message, c.from_user, bot, summary, edit=True)
    await c.answer()


# --- Бит / Эйбокс (телефон) ---
@dp.callback_query(F.data.in_({"w_bit", "w_abox"}))
async def w_phone(c: CallbackQuery, state: FSMContext):
    method = "Бит" if c.data == "w_bit" else "Эйбокс"
    await state.update_data(method=method)
    await state.set_state(Form.phone)
    await set_content(c, f"Вывод: {method}\n\nВведите номер телефона:")
    await c.answer()


@dp.message(Form.phone)
async def got_phone(m: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    summary = f"Вывод: {data['method']}\nТелефон: {m.text.strip()}"
    await state.clear()
    await finish(m, m.from_user, bot, summary)


# --- Курьер (адрес) ---
@dp.callback_query(F.data == "w_courier")
async def w_courier(c: CallbackQuery, state: FSMContext):
    await state.update_data(method="Курьер")
    await state.set_state(Form.address)
    await set_content(c, "Вывод: Курьер\n\nВведите адрес:")
    await c.answer()


@dp.message(Form.address)
async def got_address(m: Message, state: FSMContext, bot: Bot):
    summary = f"Вывод: Курьер\nАдрес: {m.text.strip()}"
    await state.clear()
    await finish(m, m.from_user, bot, summary)


# --- Банковский код ---
@dp.callback_query(F.data == "w_bank")
async def w_bank(c: CallbackQuery):
    rows = [(b, f"bank:{i}") for i, b in enumerate(BANKS)]
    await set_content(c, "Выберите банк:", kb(rows, back="withdraw"))
    await c.answer()


@dp.callback_query(F.data.startswith("bank:"))
async def bank_chosen(c: CallbackQuery, bot: Bot):
    bank = BANKS[int(c.data.split(":")[1])]
    summary = f"Вывод: Банковский код\nБанк: {bank}"
    await finish(c.message, c.from_user, bot, summary, edit=True)
    await c.answer()


# ---------- Пополнение ----------
@dp.callback_query(F.data == "deposit")
async def deposit(c: CallbackQuery):
    await show_panel(c, "deposit", "➕ <b>Пополнение</b>\n\nВыберите способ пополнения:", kb([
        ("Криптовалюта", "d_crypto"),
        ("Бит", "d_bit"),
        ("Эйбокс", "d_abox"),
        ("Банковский код", "d_bank"),
    ], back="menu"))
    await c.answer()


@dp.callback_query(F.data == "d_crypto")
async def d_crypto(c: CallbackQuery):
    rows = [(name, f"dcoin:{i}") for i, name in enumerate(CRYPTO)]
    await set_content(c, "Выберите криптовалюту:", kb(rows, back="deposit"))
    await c.answer()


@dp.callback_query(F.data.startswith("dcoin:"))
async def d_coin(c: CallbackQuery):
    ci = int(c.data.split(":")[1])
    coin = list(CRYPTO)[ci]
    rows = [(n, f"dnet:{ci}:{ni}") for ni, n in enumerate(CRYPTO[coin])]
    await set_content(c, f"{coin}\n\nВыберите сеть:", kb(rows, back="d_crypto"))
    await c.answer()


@dp.callback_query(F.data.startswith("dnet:"))
async def d_net(c: CallbackQuery):
    _, ci, ni = c.data.split(":")
    coin = list(CRYPTO)[int(ci)]
    net = CRYPTO[coin][int(ni)]
    addr = DEP_CRYPTO.get((coin, net), "АДРЕС_НЕ_ЗАДАН")
    summary = f"Пополнение: Криптовалюта\nМонета: {coin}\nСеть: {net}"
    await set_content(
        c,
        f"Пополнение: {coin}\nСеть: {net}\n\nАдрес (нажмите, чтобы скопировать):\n{code(addr)}"
        "\n\nПосле оплаты напишите оператору — выберите его ниже, сообщение вставится само:",
        result_kb(summary),
    )
    await c.answer()


@dp.callback_query(F.data.in_({"d_bit", "d_abox"}))
async def d_phone(c: CallbackQuery):
    method = "Бит" if c.data == "d_bit" else "Эйбокс"
    summary = f"Пополнение: {method}"
    await set_content(
        c,
        f"Пополнение: {method}\n\nНомер (нажмите, чтобы скопировать):\n{code(DEP_PHONE[method])}"
        "\n\nПосле оплаты напишите оператору — выберите его ниже, сообщение вставится само:",
        result_kb(summary),
    )
    await c.answer()


@dp.callback_query(F.data == "d_bank")
async def d_bank(c: CallbackQuery):
    rows = [(b, f"dbank:{i}") for i, b in enumerate(BANKS)]
    await set_content(c, "Выберите банк:", kb(rows, back="deposit"))
    await c.answer()


@dp.callback_query(F.data.startswith("dbank:"))
async def d_bank_chosen(c: CallbackQuery):
    bank = BANKS[int(c.data.split(":")[1])]
    summary = f"Пополнение: Банковский код\nБанк: {bank}"
    await set_content(
        c,
        f"Пополнение: {bank}\n\nРеквизиты (нажмите, чтобы скопировать):\n{code(DEP_BANK[bank])}"
        "\n\nПосле оплаты напишите оператору — выберите его ниже, сообщение вставится само:",
        result_kb(summary),
    )
    await c.answer()


# ---------- Регистрация (в ТЗ не описана — заглушка) ----------
@dp.callback_query(F.data == "register")
async def register(c: CallbackQuery):
    await show_panel(
        c,
        "register",
        "📝 <b>Регистрация</b>\n\nРаздел находится в разработке.",
        kb([], back="menu"),
    )
    await c.answer()


# ---------- Поддержка ----------
@dp.callback_query(F.data == "support")
async def support(c: CallbackQuery):
    b = InlineKeyboardBuilder()
    for title, url in OPERATORS.items():
        b.button(text=title, url=url)  # открывает чат с оператором
    b.button(text="⬅️ Назад", callback_data="menu")
    b.adjust(1)
    await show_panel(
        c,
        "support",
        "🛟 <b>Поддержка</b>\n\nВыберите оператора:",
        b.as_markup(),
    )
    await c.answer()


async def main():
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
