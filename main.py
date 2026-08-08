import asyncio
import os
import base64
import logging
import httpx
import asyncpg
from io import BytesIO
from PIL import Image
from aiogram import Bot, Dispatcher, types
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FAL_API_KEY = os.getenv("FAL_API_KEY")
PAYMENT_PHONE = os.getenv("PAYMENT_PHONE")
DATABASE_URL = os.getenv("DATABASE_PUBLIC_URL")
ADMIN_ID = 1991186266

TARIFFS = {
    "1": {"name": "1 фото", "count": 1, "price": 39},
    "10": {"name": "10 фото", "count": 10, "price": 199},
    "30": {"name": "30 фото", "count": 30, "price": 490},
    "100": {"name": "100 фото", "count": 100, "price": 1490},
}

FREE_CREDITS = 3

STYLE_TEMPLATES = {
    "paris_f": {"name": "🗼 Париж (жен)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A beautiful woman in Paris, standing near the Eiffel Tower at golden sunset. Wearing an elegant French-style midi dress, beret, and heels. Parisian café terrace in background, cobblestone streets, warm golden light, rose petals. Shot on Canon EOS R5, 85mm f/1.4, cinematic lighting, fashion magazine quality, 8K."},
    "paris_m": {"name": "🗼 Париж (муж)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A stylish man in Paris near the Eiffel Tower at golden sunset. Wearing a classic French-style blazer, scarf, and elegant trousers. Parisian café terrace in background, cobblestone streets, warm golden light. Shot on Canon EOS R5, 85mm f/1.4, cinematic lighting, editorial quality, 8K."},
    "newyork_f": {"name": "🌃 Нью-Йорк (жен)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A confident glamorous woman in New York City at night. Wearing a sleek black dress and stiletto heels, standing on a rooftop with Manhattan skyline and glowing skyscrapers behind her. Taxi lights, rain-wet streets below, dramatic city glow. Shot on Sony A7R IV, 35mm f/1.4, cinematic night lighting, Vogue magazine style, 8K."},
    "newyork_m": {"name": "🌃 Нью-Йорк (муж)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A confident stylish man in New York City at night. Wearing a sharp suit and long coat, standing on a rooftop with Manhattan skyline behind him. Glowing skyscrapers, rain-wet streets below, dramatic city atmosphere. Shot on Sony A7R IV, 35mm f/1.4, cinematic night lighting, GQ magazine style, 8K."},
    "mountains_f": {"name": "🏔️ Горы (жен)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A woman standing on a breathtaking mountain peak in the Alps. Wearing a stylish winter outfit — fitted ski jacket, warm scarf, gloves. Snow-covered peaks, dramatic clouds, vast panoramic view below, golden sunrise light. Shot on Canon EOS R5, 24mm f/2.8, epic landscape lighting, adventure photography, 8K."},
    "mountains_m": {"name": "🏔️ Горы (муж)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A man standing confidently on a breathtaking mountain peak in the Alps. Wearing a rugged winter jacket, scarf, and gloves. Snow-covered peaks, dramatic clouds, vast panoramic view, golden sunrise light. Shot on Canon EOS R5, 24mm f/2.8, epic landscape lighting, adventure photography, 8K."},
    "maldives_f": {"name": "🌊 Мальдивы (жен)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A woman relaxing at a luxurious overwater bungalow in the Maldives. Wearing an elegant resort dress, standing on a private deck above crystal-clear turquoise water. Tropical sunset, coral reef visible below, white sand island in distance, swaying palm trees. Shot on Sony A7R IV, 50mm f/1.8, golden hour tropical lighting, luxury travel magazine, 8K."},
    "maldives_m": {"name": "🌊 Мальдивы (муж)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A man relaxing at a luxurious overwater bungalow in the Maldives. Wearing elegant resort shorts and linen shirt, standing on a private deck above crystal-clear turquoise water. Tropical sunset, coral reef visible below, white sand island in distance. Shot on Sony A7R IV, 50mm f/1.8, golden hour tropical lighting, luxury travel magazine, 8K."},
    "jungle_f": {"name": "🌿 Тропики (жен)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A woman deep in a magical tropical rainforest. Wearing a light flowy boho dress, surrounded by giant ferns, exotic flowers, hanging vines. Mystical waterfall in background, shafts of golden light through dense jungle canopy, butterflies and exotic birds. Shot on Canon EOS R5, 50mm f/1.4, ethereal natural lighting, National Geographic style, 8K."},
    "jungle_m": {"name": "🌿 Тропики (муж)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A man deep in a magical tropical rainforest. Wearing adventure khaki outfit, surrounded by giant ferns, exotic flowers, hanging vines. Mystical waterfall in background, shafts of golden light through dense jungle canopy, exotic birds. Shot on Canon EOS R5, 50mm f/1.4, ethereal natural lighting, National Geographic style, 8K."},
    "rock_f": {"name": "🎸 Рок (жен)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A rock star woman performing on a massive concert stage. Wearing a leather jacket, fishnet stockings, boots, and rock accessories. Electric guitar in hand, dramatic stage lighting with red and purple spotlights, smoke machines, screaming crowd of thousands below, pyrotechnics exploding behind her. Shot on Canon EOS R3, 85mm f/1.4, dramatic concert lighting, Rolling Stone magazine style, 8K."},
    "rock_m": {"name": "🎸 Рок (муж)", "prompt": "The person from my photo without changing facial features, hair color or eye color. A rock star man performing on a massive concert stage. Wearing a leather jacket, ripped jeans, and rock accessories. Electric guitar in hand, dramatic stage lighting with red and purple spotlights, smoke machines, screaming crowd of thousands below, pyrotechnics exploding behind him. Shot on Canon EOS R3, 85mm f/1.4, dramatic concert lighting, Rolling Stone magazine style, 8K."},
}

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
client = OpenAI(api_key=OPENAI_API_KEY)

user_photos: dict[int, str] = {}
user_model: dict[int, str] = {}
db_pool = None


async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                credits INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
    logger.info("База данных инициализирована!")


async def get_credits(user_id: int) -> int:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT credits FROM users WHERE user_id = $1", user_id)
        return -1 if row is None else row["credits"]


async def init_user(user_id: int) -> bool:
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", user_id)
        if existing is None:
            await conn.execute("INSERT INTO users (user_id, credits) VALUES ($1, $2)", user_id, FREE_CREDITS)
            return True
        return False


async def add_credits(user_id: int, count: int):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, credits) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET credits = users.credits + $2
        """, user_id, count)


async def use_credit(user_id: int) -> bool:
    async with db_pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE users SET credits = credits - 1 WHERE user_id = $1 AND credits > 0
        """, user_id)
        return result == "UPDATE 1"


def compress_image(image_bytes: bytes, max_size: int = 1024) -> str:
    img = Image.open(BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def detect_image_size(prompt: str) -> tuple[str, str]:
    prompt_lower = prompt.lower()
    vertical_keywords = ["full body", "full-body", "standing", "walking", "в полный рост", "стоит", "идёт", "идет", "whole body", "весь рост"]
    landscape_keywords = ["landscape", "panorama", "wide", "city", "street", "nature", "ocean", "пейзаж", "панорама", "широкий", "горизонтальный", "город", "улица", "природа", "океан", "море", "beach", "пляж", "forest", "лес", "mountain", "гора", "sky", "небо"]
    portrait_keywords = ["portrait", "close-up", "closeup", "face", "headshot", "selfie", "портрет", "крупный план", "лицо", "вертикальный", "profile", "профиль"]
    for kw in vertical_keywords:
        if kw in prompt_lower:
            return "portrait_16_9", "1024x1536"
    for kw in landscape_keywords:
        if kw in prompt_lower:
            return "landscape_4_3", "1536x1024"
    for kw in portrait_keywords:
        if kw in prompt_lower:
            return "portrait_4_3", "1024x1536"
    return "square_hd", "1024x1024"


def model_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Flux PuLID — чёткое лицо", callback_data="model_flux")],
        [InlineKeyboardButton(text="🍌 Nano Banana — реалистичнее", callback_data="model_banana")],
    ])


def styles_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, t in STYLE_TEMPLATES.items():
        buttons.append([InlineKeyboardButton(text=t["name"], callback_data=f"style_{key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def tariff_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, t in TARIFFS.items():
        buttons.append([InlineKeyboardButton(text=f"{t['name']} — {t['price']}₽", callback_data=f"buy_{key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def translate_prompt(user_prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a professional image prompt translator. If the prompt is in Russian, translate it to English. If it is already in English, return it as-is. Do NOT summarize or shorten. Return ONLY the translated prompt."},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=800, temperature=0.3
        )
        translated = response.choices[0].message.content.strip()
        logger.info(f"Промпт переведён: '{user_prompt[:50]}...' -> '{translated[:50]}...'")
        return translated
    except Exception as e:
        logger.warning(f"Перевод не удался: {e}")
        return user_prompt


async def upload_to_fal(image_base64: str) -> str:
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.post(
            "https://rest.alpha.fal.ai/storage/upload/base64",
            headers={"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"},
            json={"file_name": "photo.jpg", "content_type": "image/jpeg", "data": image_base64}
        )
        if response.status_code != 200:
            return f"data:image/jpeg;base64,{image_base64}"
        result = response.json()
        return result.get("url", f"data:image/jpeg;base64,{image_base64}")


async def generate_with_flux_pulid(image_base64: str, prompt: str) -> bytes:
    fal_size, _ = detect_image_size(prompt)
    image_data_uri = f"data:image/jpeg;base64,{image_base64}"
    async with httpx.AsyncClient(timeout=180) as http:
        gen_response = await http.post(
            "https://fal.run/fal-ai/flux-pulid",
            headers={"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"},
            json={
                "prompt": prompt + ", photorealistic, RAW photo, 8K resolution, sharp focus, natural skin texture, professional photography, cinematic lighting, preserve exact body proportions and figure, same body type as reference photo, do not slim or alter body shape",
                "reference_image_url": image_data_uri,
                "num_inference_steps": 30,
                "guidance_scale": 7,
                "true_cfg": 1,
                "id_weight": 1.0,
                "image_size": fal_size,
                "num_images": 1,
            }
        )
        logger.info(f"Flux PuLID статус: {gen_response.status_code}")
        if gen_response.status_code == 500:
            raise ValueError("Сервер fal.ai временно недоступен. Попробуйте ещё раз через минуту.")
        try:
            gen_data = gen_response.json()
        except Exception:
            raise ValueError(f"Неожиданный ответ fal.ai: {gen_response.text[:200]}")
        if "images" not in gen_data:
            raise ValueError(f"Ошибка fal.ai: {gen_data}")
        result_url = gen_data["images"][0]["url"]
        img_response = await http.get(result_url)
        return img_response.content


async def generate_with_nano_banana(image_base64: str, prompt: str) -> bytes:
    image_url = await upload_to_fal(image_base64)
    async with httpx.AsyncClient(timeout=180) as http:
        gen_response = await http.post(
            "https://fal.run/fal-ai/nano-banana/edit",
            headers={"Authorization": f"Key {FAL_API_KEY}", "Content-Type": "application/json"},
            json={
                "prompt": prompt + ". Keep the exact face, age, and appearance of the person from the reference photo. Photorealistic, high quality.",
                "image_urls": [image_url],
                "num_images": 1,
                "aspect_ratio": "auto",
                "output_format": "png",
                "safety_tolerance": "4",
            }
        )
        logger.info(f"Nano Banana статус: {gen_response.status_code}")
        if gen_response.status_code == 500:
            raise ValueError("Сервер Nano Banana временно недоступен. Попробуйте ещё раз через минуту.")
        try:
            gen_data = gen_response.json()
        except Exception:
            raise ValueError(f"Неожиданный ответ Nano Banana: {gen_response.text[:200]}")
        if "images" not in gen_data:
            raise ValueError(f"Ошибка Nano Banana: {gen_data}")
        result_url = gen_data["images"][0]["url"]
        img_response = await http.get(result_url)
        return img_response.content


async def generate_text_only(prompt: str) -> bytes:
    translated_prompt = translate_prompt(prompt)
    _, openai_size = detect_image_size(prompt + " " + translated_prompt)
    result = client.images.generate(
        model="gpt-image-1",
        prompt=translated_prompt,
        size=openai_size,
        quality="high",
    )
    return base64.b64decode(result.data[0].b64_json)


async def process_generation(message: types.Message, user_id: int, prompt: str, is_template: bool = False):
    credits = await get_credits(user_id)
    if credits <= 0:
        await message.answer("💳 У тебя закончились генерации!\n\nПополни баланс командой /buy 😊")
        return

    model = user_model.get(user_id, "banana")
    model_name = "🍌 Nano Banana" if model == "banana" else "⚡ Flux PuLID"
    await message.answer(f"⏳ Генерирую [{model_name}]... подожди немного (осталось: {credits})")

    try:
        if user_id in user_photos:
            saved_base64 = user_photos[user_id]
            if model == "banana":
                image_bytes = await generate_with_nano_banana(saved_base64, prompt)
            else:
                image_bytes = await generate_with_flux_pulid(saved_base64, prompt)
            if not is_template:
                del user_photos[user_id]
        else:
            image_bytes = await generate_text_only(prompt)

        await use_credit(user_id)
        remaining = await get_credits(user_id)

        photo_file = BufferedInputFile(image_bytes, filename="image.png")
        await message.answer_photo(
            photo_file,
            caption=f"✅ Готово! Осталось: *{remaining} генераций*\n\n✨ Ещё образы — /styles",
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"[{user_id}] Ошибка: {e}", exc_info=True)
        err = str(e)
        if "no face detected" in err.lower() or "face" in err.lower():
            await message.answer("⚠️ Не удалось найти лицо на фото.\n\nПопробуйте другое фото — реальный портрет с чётким лицом 😊")
        elif "content_policy" in err.lower() or "safety" in err.lower():
            await message.answer("⚠️ Запрос нарушает правила контента. Попробуйте переформулировать.")
        elif "billing" in err.lower() or "quota" in err.lower():
            await message.answer("💳 Проблема с балансом. Проверьте аккаунт.")
        elif "временно недоступен" in err:
            await message.answer("⚠️ " + err)
        else:
            await message.answer(f"❌ Ошибка:\n`{err[:300]}`", parse_mode="Markdown")


class PaymentState(StatesGroup):
    waiting_receipt = State()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    is_new = await init_user(user_id)
    credits = await get_credits(user_id)
    if is_new:
        await message.answer(
            f"👋 Привет! Я генерирую изображения с помощью ИИ.\n\n"
            f"🎁 Тебе начислено *{FREE_CREDITS} бесплатных генерации* — попробуй!\n\n"
            "✨ *Готовые образы* — /styles\n\n"
            "🖼 *Без фото* — напиши текст, создам картинку.\n\n"
            "🧑‍🎨 *С твоим фото* — отправь фото + описание, перенесу тебя в новую сцену с сохранением лица.\n\n"
            "⚠️ Для генерации с фото:\n"
            "• Только реальные фото людей — рисунки и аниме не поддерживаются\n"
            "• На фото должен быть *один человек*\n\n"
            "💰 Купить генерации — /buy\n"
            "💳 Баланс — /balance",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"👋 Привет! Рада тебя видеть снова!\n\n"
            f"✨ Готовые образы — /styles\n\n"
            f"💳 У тебя: *{credits} генераций*\n\n"
            "💰 Купить генерации — /buy",
            parse_mode="Markdown"
        )


@dp.message(Command("styles"))
async def cmd_styles(message: types.Message):
    if message.from_user.id not in user_photos:
        await message.answer(
            "✨ *Готовые образы*\n\n"
            "Сначала отправь своё фото — я сохраню его и предложу стили 😊\n\n"
            "⚠️ Нужно реальное фото с одним человеком и чётким лицом.",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "✨ *Выбери образ:*",
            parse_mode="Markdown",
            reply_markup=styles_keyboard()
        )


@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    await message.answer("💳 Выбери пакет генераций:", reply_markup=tariff_keyboard())


@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    await init_user(message.from_user.id)
    credits = await get_credits(message.from_user.id)
    await message.answer(f"💳 У тебя *{credits} генераций*", parse_mode="Markdown")


@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    user_photos.pop(message.from_user.id, None)
    user_model.pop(message.from_user.id, None)
    await message.answer("🔄 Фото сброшено.")


@dp.callback_query(lambda c: c.data.startswith("model_"))
async def process_model_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    model = callback.data.split("_")[1]
    user_model[user_id] = model
    model_name = "🍌 Nano Banana" if model == "banana" else "⚡ Flux PuLID"
    await callback.message.edit_text(
        f"✅ Выбрана модель: *{model_name}*\n\n"
        "✨ Теперь выбери образ — /styles\n"
        "Или напиши своё описание 😊",
        parse_mode="Markdown"
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    tariff_key = callback.data.split("_")[1]
    tariff = TARIFFS.get(tariff_key)
    if not tariff:
        await callback.answer("Ошибка")
        return
    await callback.message.answer(
        f"💳 *{tariff['name']} — {tariff['price']}₽*\n\n"
        f"Переведи *{tariff['price']}₽* на Сбер:\n"
        f"📱 `{PAYMENT_PHONE}`\n\n"
        f"В комментарии укажи свой Telegram ID:\n"
        f"`{callback.from_user.id}`\n\n"
        f"После оплаты нажми кнопку ниже 👇",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил(а)", callback_data=f"paid_{tariff_key}")]
        ])
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("paid_"))
async def process_paid(callback: types.CallbackQuery, state: FSMContext):
    tariff_key = callback.data.split("_")[1]
    await state.set_state(PaymentState.waiting_receipt)
    await state.update_data(tariff_key=tariff_key)
    await callback.message.answer("📸 Отправь скриншот чека!")
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("style_"))
async def process_style_template(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    template_key = callback.data[6:]
    template = STYLE_TEMPLATES.get(template_key)
    if not template:
        await callback.answer("Ошибка")
        return
    if user_id not in user_photos:
        await callback.message.answer("⚠️ Сначала отправь своё фото! Без фото не могу создать образ 😊")
        await callback.answer()
        return
    await callback.answer()
    await process_generation(callback.message, user_id, template["prompt"], is_template=True)


@dp.message(PaymentState.waiting_receipt)
async def process_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    tariff_key = data.get("tariff_key")
    tariff = TARIFFS.get(tariff_key)
    user_id = message.from_user.id
    if message.photo:
        await message.answer("⏳ Чек получен! Проверяем оплату — обычно до 15 минут.\nУведомим тебя как только начислим генерации!")
        try:
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=(
                    f"💳 Новая оплата!\n"
                    f"👤 @{message.from_user.username} (ID: {user_id})\n"
                    f"📦 {tariff['name']} — {tariff['price']}₽\n"
                    f"➕ Начислить: /add_{user_id}_{tariff['count']}"
                )
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления: {e}")
        await state.clear()
    else:
        await message.answer("Пожалуйста, отправь именно фото чека.")


@dp.message(lambda m: m.text and m.text.startswith("/add_"))
async def cmd_add_credits(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        parts = message.text.split("_")
        target_id = int(parts[1])
        count = int(parts[2])
        await add_credits(target_id, count)
        credits = await get_credits(target_id)
        await message.answer(f"✅ Начислено {count} генераций пользователю {target_id}")
        await bot.send_message(
            target_id,
            f"✅ Оплата подтверждена!\nНачислено *{count} генераций*.\nТеперь у тебя: *{credits} генераций* 🎨",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка начисления: {e}")
        await message.answer("Ошибка. Формат: /add_USER_ID_COUNT")


@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    await init_user(user_id)

    if message.photo and not message.caption:
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            downloaded = await bot.download_file(file.file_path)
            image_bytes = downloaded.read()
            image_base64 = compress_image(image_bytes)
            user_photos[user_id] = image_base64

            await message.answer(
                "📸 Фото сохранено!\n\n"
                "Выбери модель генерации:\n\n"
                "⚡ *Flux PuLID* — точнее сохраняет черты лица\n"
                "🍌 *Nano Banana* — более реалистичный результат\n\n"
                "⚠️ *Важно:*\n"
                "• Только реальные фото людей — рисунки и аниме не поддерживаются\n"
                "• На фото должен быть *один человек*",
                parse_mode="Markdown",
                reply_markup=model_choice_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка фото: {e}")
            await message.answer("❌ Не удалось обработать фото.")
        return

    if message.text:
        prompt = message.text.strip()
        if prompt.startswith("/"):
            return
        await process_generation(message, user_id, translate_prompt(prompt))


async def main():
    await init_db()
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
