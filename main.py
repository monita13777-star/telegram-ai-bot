import asyncio
import os
import base64
import logging
import httpx
import json
from aiogram import Bot, Dispatcher, types
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FAL_API_KEY = os.getenv("FAL_API_KEY")
PAYMENT_PHONE = os.getenv("PAYMENT_PHONE")
ADMIN_ID = 1991186266

TARIFFS = {
    "1": {"name": "1 фото", "count": 1, "price": 29},
    "10": {"name": "10 фото", "count": 10, "price": 199},
    "30": {"name": "30 фото", "count": 30, "price": 490},
    "100": {"name": "100 фото", "count": 100, "price": 1490},
}

CREDITS_FILE = "/tmp/credits.json"
FREE_CREDITS = 3

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
client = OpenAI(api_key=OPENAI_API_KEY)

user_photos: dict[int, str] = {}


def load_credits() -> dict:
    try:
        if os.path.exists(CREDITS_FILE):
            with open(CREDITS_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки кредитов: {e}")
    return {}


def save_credits(data: dict):
    try:
        with open(CREDITS_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Ошибка сохранения кредитов: {e}")


credits_db: dict = load_credits()


def get_credits(user_id: int) -> int:
    return credits_db.get(str(user_id), -1)


def add_credits(user_id: int, count: int):
    key = str(user_id)
    current = credits_db.get(key, 0)
    if current == -1:
        current = 0
    credits_db[key] = current + count
    save_credits(credits_db)


def init_user(user_id: int):
    key = str(user_id)
    if key not in credits_db:
        credits_db[key] = FREE_CREDITS
        save_credits(credits_db)
        return True
    return False


def use_credit(user_id: int) -> bool:
    key = str(user_id)
    if credits_db.get(key, 0) > 0:
        credits_db[key] -= 1
        save_credits(credits_db)
        return True
    return False


def tariff_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, t in TARIFFS.items():
        buttons.append([InlineKeyboardButton(
            text=f"{t['name']} — {t['price']}₽",
            callback_data=f"buy_{key}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def translate_prompt(user_prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional image prompt translator. "
                        "If the prompt is in Russian, translate it to English. "
                        "If it is already in English, return it as-is without changes. "
                        "Do NOT summarize, shorten, or lose any details. "
                        "Preserve ALL objects, accessories, clothing, atmosphere, and scene details exactly. "
                        "Return ONLY the translated prompt, nothing else."
                    )
                },
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=800,
            temperature=0.3
        )
        translated = response.choices[0].message.content.strip()
        logger.info(f"Промпт переведён: '{user_prompt[:50]}...' -> '{translated[:50]}...'")
        return translated
    except Exception as e:
        logger.warning(f"Перевод не удался: {e}")
        return user_prompt


async def generate_with_flux_pulid(image_base64: str, prompt: str) -> bytes:
    translated_prompt = translate_prompt(prompt)
    image_data_uri = f"data:image/jpeg;base64,{image_base64}"

    async with httpx.AsyncClient(timeout=180) as http:
        gen_response = await http.post(
            "https://fal.run/fal-ai/flux-pulid",
            headers={
                "Authorization": f"Key {FAL_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "prompt": translated_prompt + ", photorealistic, RAW photo, 8K resolution, sharp focus, natural skin texture, professional photography, cinematic lighting",
                "reference_image_url": image_data_uri,
                "num_inference_steps": 30,
                "guidance_scale": 7,
                "true_cfg": 1,
                "id_weight": 1.0,
                "image_size": "square_hd",
                "num_images": 1,
            }
        )
        gen_data = gen_response.json()
        logger.info(f"Ответ fal.ai: {gen_data}")

        if "images" not in gen_data:
            raise ValueError(f"Ошибка fal.ai: {gen_data}")

        result_url = gen_data["images"][0]["url"]
        img_response = await http.get(result_url)
        return img_response.content


async def generate_text_only(prompt: str) -> bytes:
    translated_prompt = translate_prompt(prompt)
    result = client.images.generate(
        model="gpt-image-1",
        prompt=translated_prompt,
        size="1024x1024",
        quality="high",
    )
    image_base64 = result.data[0].b64_json
    return base64.b64decode(image_base64)


class PaymentState(StatesGroup):
    waiting_receipt = State()


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    is_new = init_user(user_id)
    credits = get_credits(user_id)

    if is_new:
        await message.answer(
            f"👋 Привет! Я генерирую изображения с помощью ИИ.\n\n"
            f"🎁 Тебе начислено *{FREE_CREDITS} бесплатные генерации* — попробуй!\n\n"
            "🖼 *Без фото* — напиши текст, создам картинку.\n\n"
            "🧑‍🎨 *С твоим фото* — отправь фото + описание, перенесу тебя в новую сцену с сохранением лица.\n\n"
            "💰 Купить генерации — /buy\n"
            "💳 Баланс — /balance",
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            f"👋 Привет! Рада тебя видеть снова!\n\n"
            f"💳 У тебя: *{credits} генераций*\n\n"
            "💰 Купить генерации — /buy\n"
            "💳 Баланс — /balance",
            parse_mode="Markdown"
        )


@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    await message.answer(
        "💳 Выбери пакет генераций:",
        reply_markup=tariff_keyboard()
    )


@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    init_user(message.from_user.id)
    credits = get_credits(message.from_user.id)
    await message.answer(f"💳 У тебя *{credits} генераций*", parse_mode="Markdown")


@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    user_photos.pop(message.from_user.id, None)
    await message.answer("🔄 Фото сброшено.")


@dp.callback_query(lambda c: c.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery, state: FSMContext):
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


@dp.message(PaymentState.waiting_receipt)
async def process_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    tariff_key = data.get("tariff_key")
    tariff = TARIFFS.get(tariff_key)
    user_id = message.from_user.id

    if message.photo:
        await message.answer(
            "⏳ Чек получен! Проверяем оплату — обычно до 15 минут.\n"
            "Уведомим тебя как только начислим генерации!"
        )
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
        add_credits(target_id, count)
        await message.answer(f"✅ Начислено {count} генераций пользователю {target_id}")
        await bot.send_message(
            target_id,
            f"✅ Оплата подтверждена!\n"
            f"Начислено *{count} генераций*.\n"
            f"Теперь у тебя: *{get_credits(target_id)} генераций* 🎨",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка начисления: {e}")
        await message.answer("Ошибка. Формат: /add_USER_ID_COUNT")


@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    init_user(user_id)

    if message.photo and not message.caption:
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            downloaded = await bot.download_file(file.file_path)
            image_bytes = downloaded.read()
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            user_photos[user_id] = image_base64
            await message.answer(
                "📸 Фото сохранено!\n\nНапишите описание — как изменить образ.\n"
                "Можно на *русском* или *английском* 😊",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка фото: {e}")
            await message.answer("❌ Не удалось обработать фото.")
        return

    if message.text:
        prompt = message.text.strip()
        credits = get_credits(user_id)

        if credits <= 0:
            await message.answer(
                "💳 У тебя закончились генерации!\n\n"
                "Пополни баланс командой /buy 😊"
            )
            return

        await message.answer(f"⏳ Генерирую... (осталось: {credits})")

        try:
            if user_id in user_photos:
                saved_base64 = user_photos[user_id]
                image_bytes = await generate_with_flux_pulid(saved_base64, prompt)
                del user_photos[user_id]
            else:
                image_bytes = await generate_text_only(prompt)

            use_credit(user_id)
            remaining = get_credits(user_id)

            photo_file = BufferedInputFile(image_bytes, filename="image.png")
            await message.answer_photo(
                photo_file,
                caption=f"✅ Готово! Осталось: *{remaining} генераций*",
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка: {e}", exc_info=True)
            err = str(e)
            if "content_policy" in err.lower() or "safety" in err.lower():
                await message.answer("⚠️ Запрос нарушает правила контента. Попробуйте переформулировать.")
            elif "billing" in err.lower() or "quota" in err.lower():
                await message.answer("💳 Проблема с балансом. Проверьте аккаунт.")
            else:
                await message.answer(f"❌ Ошибка:\n`{err[:300]}`", parse_mode="Markdown")


async def main():
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
