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

# Менеджеры: (текст кнопки, ссылка или @юз)
OPERATORS = [
    ("סוכנת אנה 🦸‍♀️", "https://t.me/usupoq"),
    ("סוכן ניר 🦸‍♂️", "https://t.me/Noikss"),
]

# Монеты и сети (названия на иврите — их видит клиент)
CRYPTO = {
    "ביטקוין": ["Bitcoin"],
    "אתריום": ["ERC20"],
    "USDT": ["TRC20", "ERC20", "BEP20", "TON"],
    "סולאנה": ["Solana"],
    "BNB": ["BEP20"],
}

BANKS = ["דיסקונט", "פועלים", "לאומי"]

# Реквизиты для ПОПОЛНЕНИЯ (копируются нажатием)
DEP_CRYPTO = {  # (монета, сеть): адрес
    ("ביטקוין", "Bitcoin"): "ВСТАВЬ_АДРЕС_BTC",
    ("אתריום", "ERC20"): "ВСТАВЬ_АДРЕС_ETH",
    ("USDT", "TRC20"): "ВСТАВЬ_АДРЕС_USDT_TRC20",
    ("USDT", "ERC20"): "ВСТАВЬ_АДРЕС_USDT_ERC20",
    ("USDT", "BEP20"): "ВСТАВЬ_АДРЕС_USDT_BEP20",
    ("USDT", "TON"): "ВСТАВЬ_АДРЕС_USDT_TON",
    ("סולאנה", "Solana"): "ВСТАВЬ_АДРЕС_SOL",
    ("BNB", "BEP20"): "ВСТАВЬ_АДРЕС",
}
DEP_PHONE = {"ביט": "+972XXXXXXXXX", "פייבוקס": "+972XXXXXXXXX"}

# Пополнение через банк: какие поля просить у клиента (по порядку)
BANK_FIELDS = {
    "פועלים": ["code", "amount", "date"],
    "לאומי": ["code", "amount", "id"],
    "דיסקונט": ["code", "amount"],
}
FIELD_PROMPT = {  # что спрашиваем
    "code": "הקלד קוד",
    "amount": "הזינו סכום",
    "date": "הזינו תאריך",
    "id": "הזינו ת״ז",
}
FIELD_LABEL = {  # как подписываем в итоговом сообщении
    "code": "קוד",
    "amount": "סכום",
    "date": "תאריך",
    "id": "ת״ז",
}

# Приветствие на /start (идёт вместе с кнопками и картинкой, лимит подписи 1024 символа)
WELCOME = (
    "⚡ <b>ברוכים הבאים ל-Flash Bet!</b> ⚡\n"
    "המקום שבו המשחק מתחיל וההזדמנויות לא מחכות.\n\n"
    "כאן בבוט הכל קורה במהירות הבזק, בצורה מאובטחת ובלי כאבי ראש. "
    "מכאן אתם שולטים בהכל בלחיצת כפתור:\n"
    "💰 הפקדה מהירה – טעינת יתרה תוך שניות.\n"
    "💸 משיכת רווחים – קבלת הכסף שלכם בקלות ובמהירות.\n"
    "🎧 תמיכה 24/7 – צוות השירות שלנו זמין לכל שאלה או עזרה."
)

# Описание бота — под "Что умеет этот бот?" (до 512 символов)
BOT_DESCRIPTION = (
    "הימורי ספורט & קזינו\n"
    "בית ההימורים הגדול בישראל\n"
    "זכיות ומשיכות תוך חצי שעה\n"
    "סוכנים ותיקים 20 שנה בתחום\n"
    "יחס אישי לכל לקוח\n"
    "פעילות 24/7"
)
# Короткое описание в профиле бота (до 120 символов)
BOT_SHORT_DESCRIPTION = "הימורי ספורט & קזינו | בית ההימורים הגדול בישראל | זכיות ומשיכות תוך חצי שעה | 24/7"
# ===============================================

BACK = "⬅️ חזרה"
TO_MENU = "🏠 תפריט ראשי"
PAY_HINT = "\n\nלאחר התשלום פנו לסוכן – ההודעה תוכנס אוטומטית:"
COPY = "לחצו להעתקה"

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
    city = State()
    bank_input = State()


# ---------- помощники ----------
def code(x) -> str:
    """Моноширинный текст — копируется нажатием."""
    return f"<code>{html.escape(str(x))}</code>"


def kb(rows, back=None):
    """rows: список (текст, callback_data). По одной кнопке в ряд."""
    b = InlineKeyboardBuilder()
    for text, data in rows:
        b.button(text=text, callback_data=data)
    if back:
        b.button(text=BACK, callback_data=back)
    b.adjust(1)
    return b.as_markup()


def prefilled_url(base: str, text: str) -> str:
    """Ссылка на чат с менеджером, где текст уже вставлен в поле ввода."""
    if base.startswith("@"):
        base = "https://t.me/" + base[1:]
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}text={quote(text)}"


def operators_kb(summary: str | None = None, back: str | None = None, to_menu: bool = False):
    """Кнопки менеджеров. Если есть summary — чат откроется с готовым текстом."""
    b = InlineKeyboardBuilder()
    for title, url in OPERATORS:
        b.button(text=title, url=prefilled_url(url, summary) if summary else url)
    if to_menu:
        b.button(text=TO_MENU, callback_data="menu")
    if back:
        b.button(text=BACK, callback_data=back)
    b.adjust(1)
    return b.as_markup()


async def edit_content(message: Message, text: str, reply_markup=None):
    """Редактирует и обычное сообщение, и подпись под картинкой."""
    if message.photo:
        await message.edit_caption(caption=text, reply_markup=reply_markup)
    else:
        await message.edit_text(text, reply_markup=reply_markup)


async def show_panel(c: CallbackQuery, asset: str, caption: str, reply_markup=None):
    """Экран с картинкой (если файла нет — просто текст)."""
    path = ASSETS[asset]
    if not path.is_file():
        logging.warning("Не найдена картинка: %s", path)
        await edit_content(c.message, caption, reply_markup)
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


async def finish(target, summary: str, edit: bool = False):
    """Итог цепочки + выбор менеджера: чат откроется с уже вставленным текстом."""
    text = (
        "✅ <b>הכל מוכן!</b>\n\n"
        f"{code(summary)}\n\n"
        "בחרו סוכן – ייפתח צ'אט עם הודעה מוכנה, נשאר רק ללחוץ על שליחה."
    )
    kbd = operators_kb(summary, to_menu=True)
    if edit:
        await edit_content(target, text, kbd)
    else:
        await target.answer(text, reply_markup=kbd)


# ---------- меню ----------
def main_menu():
    return kb([
        ("💸 משיכה", "withdraw"),
        ("➕ הפקדה", "deposit"),
        ("📝 הרשמה לאתר", "register"),
        ("🛟 תמיכה", "support"),
    ])


@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    path = ASSETS["menu"]
    if path.is_file():
        await m.answer_photo(photo=FSInputFile(path), caption=WELCOME, reply_markup=main_menu())
    else:
        await m.answer(WELCOME, reply_markup=main_menu())


@dp.callback_query(F.data == "menu")
async def menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_panel(c, "menu", WELCOME, main_menu())
    await c.answer()


# ---------- משיכה (Вывод) ----------
@dp.callback_query(F.data == "withdraw")
async def withdraw(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_panel(c, "withdraw", "💸 <b>משיכה</b>\nבחרו שיטת משיכה:", kb([
        ("מטבע דיגיטלי", "w_crypto"),
        ("ביט", "w_bit"),
        ("פייבוקס", "w_pbox"),
        ("שליח", "w_courier"),
        ("קוד משיכה", "w_bank"),
    ], back="menu"))
    await c.answer()


# --- מטבע דיגיטלי ---
@dp.callback_query(F.data == "w_crypto")
async def w_crypto(c: CallbackQuery):
    rows = [(name, f"coin:{i}") for i, name in enumerate(CRYPTO)]
    await edit_content(c.message, "בחרו מטבע:", kb(rows, back="withdraw"))
    await c.answer()


async def ask_wallet(message: Message, state: FSMContext, coin: str, net: str):
    await state.update_data(coin=coin, net=net)
    await state.set_state(Form.wallet)
    await edit_content(message, f"{coin} | {net}\n\nהזינו כתובת ארנק:")


@dp.callback_query(F.data.startswith("coin:"))
async def coin_chosen(c: CallbackQuery, state: FSMContext):
    ci = int(c.data.split(":")[1])
    coin = list(CRYPTO)[ci]
    nets = CRYPTO[coin]
    if len(nets) == 1:  # сеть одна — сразу просим адрес
        await ask_wallet(c.message, state, coin, nets[0])
    else:
        rows = [(n, f"net:{ci}:{ni}") for ni, n in enumerate(nets)]
        await edit_content(c.message, f"בחרתם: {coin}\n\nבחרו רשת:", kb(rows, back="w_crypto"))
    await c.answer()


@dp.callback_query(F.data.startswith("net:"))
async def net_chosen(c: CallbackQuery, state: FSMContext):
    _, ci, ni = c.data.split(":")
    coin = list(CRYPTO)[int(ci)]
    await ask_wallet(c.message, state, coin, CRYPTO[coin][int(ni)])
    await c.answer()


@dp.message(Form.wallet, F.text)
async def got_wallet(m: Message, state: FSMContext):
    data = await state.get_data()
    summary = (
        "משיכה: מטבע דיגיטלי\n"
        f"מטבע: {data['coin']}\n"
        f"רשת: {data['net']}\n"
        f"כתובת ארנק: {m.text.strip()}"
    )
    await state.clear()
    await finish(m, summary)


# --- ביט / פייבוקס (телефон) ---
@dp.callback_query(F.data.in_({"w_bit", "w_pbox"}))
async def w_phone(c: CallbackQuery, state: FSMContext):
    method = "ביט" if c.data == "w_bit" else "פייבוקס"
    await state.update_data(method=method)
    await state.set_state(Form.phone)
    await edit_content(c.message, f"משיכה: {method}\n\nהזינו מספר טלפון:")
    await c.answer()


@dp.message(Form.phone, F.text)
async def got_phone(m: Message, state: FSMContext):
    data = await state.get_data()
    summary = f"משיכה: {data['method']}\nטלפון: {m.text.strip()}"
    await state.clear()
    await finish(m, summary)


# --- שליח (сначала город, потом адрес) ---
@dp.callback_query(F.data == "w_courier")
async def w_courier(c: CallbackQuery, state: FSMContext):
    await state.set_state(Form.city)
    await edit_content(c.message, "משיכה: שליח\n\nהזינו עיר:")
    await c.answer()


@dp.message(Form.city, F.text)
async def got_city(m: Message, state: FSMContext):
    await state.update_data(city=m.text.strip())
    await state.set_state(Form.address)
    await m.answer("הזינו כתובת:")


@dp.message(Form.address, F.text)
async def got_address(m: Message, state: FSMContext):
    data = await state.get_data()
    summary = (
        "משיכה: שליח\n"
        f"עיר: {data['city']}\n"
        f"כתובת: {m.text.strip()}"
    )
    await state.clear()
    await finish(m, summary)


# --- קוד משיכה (банковский код) ---
@dp.callback_query(F.data == "w_bank")
async def w_bank(c: CallbackQuery):
    rows = [(b, f"bank:{i}") for i, b in enumerate(BANKS)]
    await edit_content(c.message, "בחרו בנק:", kb(rows, back="withdraw"))
    await c.answer()


@dp.callback_query(F.data.startswith("bank:"))
async def bank_chosen(c: CallbackQuery):
    bank = BANKS[int(c.data.split(":")[1])]
    summary = f"משיכה: קוד משיכה\nבנק: {bank}"
    await finish(c.message, summary, edit=True)
    await c.answer()


# ---------- הפקדה (Пополнение) ----------
@dp.callback_query(F.data == "deposit")
async def deposit(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_panel(c, "deposit", "➕ <b>הפקדה</b>\nבחרו שיטת הפקדה:", kb([
        ("מטבע דיגיטלי", "d_crypto"),
        ("ביט", "d_bit"),
        ("פייבוקס", "d_pbox"),
        ("קוד משיכה", "d_bank"),
    ], back="menu"))
    await c.answer()


@dp.callback_query(F.data == "d_crypto")
async def d_crypto(c: CallbackQuery):
    rows = [(name, f"dcoin:{i}") for i, name in enumerate(CRYPTO)]
    await edit_content(c.message, "בחרו מטבע:", kb(rows, back="deposit"))
    await c.answer()


async def show_deposit_address(message: Message, coin: str, net: str):
    addr = DEP_CRYPTO.get((coin, net), "ADDRESS_NOT_SET")
    summary = f"הפקדה: מטבע דיגיטלי\nמטבע: {coin}\nרשת: {net}"
    await edit_content(
        message,
        f"{coin} | {net}\n\nכתובת ({COPY}):\n{code(addr)}{PAY_HINT}",
        operators_kb(summary, to_menu=True),
    )


@dp.callback_query(F.data.startswith("dcoin:"))
async def d_coin(c: CallbackQuery):
    ci = int(c.data.split(":")[1])
    coin = list(CRYPTO)[ci]
    nets = CRYPTO[coin]
    if len(nets) == 1:  # сеть одна — сразу показываем адрес
        await show_deposit_address(c.message, coin, nets[0])
    else:
        rows = [(n, f"dnet:{ci}:{ni}") for ni, n in enumerate(nets)]
        await edit_content(c.message, f"{coin}\n\nבחרו רשת:", kb(rows, back="d_crypto"))
    await c.answer()


@dp.callback_query(F.data.startswith("dnet:"))
async def d_net(c: CallbackQuery):
    _, ci, ni = c.data.split(":")
    coin = list(CRYPTO)[int(ci)]
    await show_deposit_address(c.message, coin, CRYPTO[coin][int(ni)])
    await c.answer()


@dp.callback_query(F.data.in_({"d_bit", "d_pbox"}))
async def d_phone(c: CallbackQuery):
    method = "ביט" if c.data == "d_bit" else "פייבוקס"
    summary = f"הפקדה: {method}"
    await edit_content(
        c.message,
        f"{method}\n\nמספר ({COPY}):\n{code(DEP_PHONE[method])}{PAY_HINT}",
        operators_kb(summary, to_menu=True),
    )
    await c.answer()


# --- הפקדה через банк: код / сумма / дата или ת״ז (набор полей зависит от банка) ---
@dp.callback_query(F.data == "d_bank")
async def d_bank(c: CallbackQuery):
    rows = [(b, f"dbank:{i}") for i, b in enumerate(BANKS)]
    await edit_content(c.message, "בחרו בנק:", kb(rows, back="deposit"))
    await c.answer()


async def ask_bank_field(target: Message, bank: str, step: int, edit: bool = False):
    text = f"{bank}\n\n{FIELD_PROMPT[BANK_FIELDS[bank][step]]}:"
    if edit:
        await edit_content(target, text)
    else:
        await target.answer(text)


@dp.callback_query(F.data.startswith("dbank:"))
async def d_bank_chosen(c: CallbackQuery, state: FSMContext):
    bank = BANKS[int(c.data.split(":")[1])]
    await state.update_data(bank=bank, step=0, answers={})
    await state.set_state(Form.bank_input)
    await ask_bank_field(c.message, bank, 0, edit=True)
    await c.answer()


@dp.message(Form.bank_input, F.text)
async def got_bank_field(m: Message, state: FSMContext):
    data = await state.get_data()
    bank, step = data["bank"], data["step"]
    fields = BANK_FIELDS[bank]
    answers = {**data["answers"], fields[step]: m.text.strip()}
    step += 1
    if step < len(fields):
        await state.update_data(step=step, answers=answers)
        await ask_bank_field(m, bank, step)
        return
    lines = ["הפקדה: קוד משיכה", f"בנק: {bank}"]
    lines += [f"{FIELD_LABEL[k]}: {answers[k]}" for k in fields]
    await state.clear()
    await finish(m, "\n".join(lines))


# ---------- הרשמה לאתר: только выбор менеджера ----------
@dp.callback_query(F.data == "register")
async def register(c: CallbackQuery):
    await show_panel(
        c,
        "register",
        "📝 <b>הרשמה לאתר</b>\nבחרו סוכן:",
        operators_kb("הרשמה לאתר", back="menu"),
    )
    await c.answer()


# ---------- תמיכה ----------
@dp.callback_query(F.data == "support")
async def support(c: CallbackQuery):
    await show_panel(
        c,
        "support",
        "🛟 <b>תמיכה</b>\nבחרו סוכן:",
        operators_kb(back="menu"),
    )
    await c.answer()


async def main():
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # описание бота ("Что умеет этот бот?") и короткое описание в профиле
    try:
        await bot.set_my_description(description=BOT_DESCRIPTION)
        await bot.set_my_short_description(short_description=BOT_SHORT_DESCRIPTION)
    except Exception as e:
        logging.warning("Не удалось выставить описание бота: %s", e)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
