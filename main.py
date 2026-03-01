import asyncio
import os
import base64
import logging
import httpx
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

# Тарифы: название, количество генераций, цена
TARIFFS = {
    "1": {"name": "1 фото", "count": 1, "price": 29},
    "10": {"name": "10 фото", "count": 10, "price": 199},
    "30": {"name": "30 фото", "count": 30, "price": 490},
    "100": {"name": "100 фото", "count": 100, "price": 1490},
}

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
client = OpenAI(api_key=OPENAI_API_KEY)

# user_id -> base64 фото
user_photos: dict[int, str] = {}
# user_id -> количество оставшихся генераций
user_credits: dict[int, int] = {}
# user_id -> ожидаемый тариф (для проверки оплаты)
user_pending: dict[int, dict] = {}


class PaymentState(StatesGroup):
    waiting_receipt = State()


def get_credits(user_id: int) -> int:
    return user_credits.get(user_id, 0)


def add_credits(user_id: int, count: int):
    user_credits[user_id] = user_credits.get(user_id, 0) + count


def use_credit(user_id: int) -> bool:
    if user_credits.get(user_id, 0) > 0:
        user_credits[user_id] -= 1
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


def translate_and_enhance(user_prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional image prompt translator and enhancer. "
                        "Translate the user's prompt to English if needed. "
                        "Then enhance it to be vivid and detailed for image generation. "
                        "Keep it under 150 words. Return ONLY the enhanced English prompt, nothing else."
                    )
                },
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=250,
            temperature=0.7
        )
        translated = response.choices[0].message.content.strip()
        logger.info(f"Промпт: '{user_prompt}' -> '{translated}'")
        return translated
    except Exception as e:
        logger.warning(f"Перевод не удался: {e}")
        return user_prompt


async def generate_with_flux_pulid(image_base64: str, prompt: str) -> bytes:
    translated_prompt = translate_and_enhance(prompt)
    image_data_uri = f"data:image/jpeg;base64,{image_base64}"

    async with httpx.AsyncClient(timeout=180) as http:
        gen_response = await http.post(
            "https://fal.run/fal-ai/flux-pulid",
            headers={
                "Authorization": f"Key {FAL_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "prompt": translated_prompt,
                "reference_image_url": image_data_uri,
                "num_inference_steps": 20,
                "guidance_scale": 4,
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


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    credits = get_credits(message.from_user.id)
    await message.answer(
        f"👋 Привет! Я генерирую изображения с помощью ИИ.\n\n"
        f"💳 У тебя сейчас: *{credits} генераций*\n\n"
        "🖼 *Без фото* — напиши текст, создам картинку.\n\n"
        "🧑‍🎨 *С твоим фото* — отправь фото + описание, перенесу тебя в новую сцену с сохранением лица.\n\n"
        "💰 Чтобы пополнить генерации — нажми /buy\n"
        "/reset — сбросить сохранённое фото",
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

    user_pending[callback.from_user.id] = tariff

    await callback.message.answer(
        f"💳 *{tariff['name']} — {tariff['price']}₽*\n\n"
        f"Переведи *{tariff['price']}₽* на Сбер:\n"
        f"📱 `{PAYMENT_PHONE}`\n\n"
        f"В комментарии к переводу укажи свой Telegram ID:\n"
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
    tariff = TARIFFS.get(tariff_key)
    user_id = callback.from_user.id

    await state.set_state(PaymentState.waiting_receipt)
    await state.update_data(tariff_key=tariff_key)

    await callback.message.answer(
        "📸 Отправь скриншот чека из Сбера — я проверю и начислю генерации!",
    )
    await callback.answer()


@dp.message(PaymentState.waiting_receipt)
async def process_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    tariff_key = data.get("tariff_key")
    tariff = TARIFFS.get(tariff_key)
    user_id = message.from_user.id

    if message.photo:
        # Уведомляем пользователя что чек получен
        await message.answer(
            "⏳ Чек получен! Проверяем оплату — обычно это занимает до 15 минут.\n"
            "Как только подтвердим — начислим генерации и уведомим тебя!"
        )

        # Отправляем себе чек для проверки
        admin_id = 1991186266  # твой Telegram ID
        try:
            await bot.send_photo(
                chat_id=admin_id,
                photo=message.photo[-1].file_id,
                caption=(
                    f"💳 Новая оплата!\n"
                    f"👤 Пользователь: @{message.from_user.username} (ID: {user_id})\n"
                    f"📦 Тариф: {tariff['name']} — {tariff['price']}₽\n"
                    f"➕ Начислить: /add_{user_id}_{tariff['count']}"
                )
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление: {e}")

        await state.clear()
    else:
        await message.answer("Пожалуйста, отправь именно скриншот (фото) чека.")


@dp.message(lambda m: m.text and m.text.startswith("/add_"))
async def cmd_add_credits(message: types.Message):
    # Команда для ручного начисления: /add_USER_ID_COUNT
    try:
        parts = message.text.split("_")
        target_id = int(parts[1])
        count = int(parts[2])
        add_credits(target_id, count)
        await message.answer(f"✅ Начислено {count} генераций пользователю {target_id}")
        await bot.send_message(
            target_id,
            f"✅ Оплата подтверждена! Начислено *{count} генераций*.\n"
            f"Теперь у тебя: *{get_credits(target_id)} генераций*\n\n"
            f"Отправь фото или напиши текст для генерации! 🎨",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка начисления: {e}")
        await message.answer("Ошибка. Формат: /add_USER_ID_COUNT")


@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id

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
            logger.error(f"Ошибка сохранения фото: {e}")
            await message.answer("❌ Не удалось обработать фото. Попробуйте ещё раз.")
        return

    if message.text:
        prompt = message.text.strip()

        # Проверяем баланс
        credits = get_credits(user_id)
        if credits <= 0:
            await message.answer(
                "💳 У тебя закончились генерации!\n\n"
                "Пополни баланс командой /buy 😊"
            )
            return

        await message.answer(f"⏳ Генерирую... (осталось генераций: {credits})")

        try:
            if user_id in user_photos:
                saved_base64 = user_photos[user_id]
                image_bytes = await generate_with_flux_pulid(saved_base64, prompt)
                del user_photos[user_id]
            else:
                translated_prompt = translate_and_enhance(prompt)
                result = client.images.generate(
                    model="gpt-image-1",
                    prompt=translated_prompt,
                    size="1024x1024",
                    quality="high",
                )
                image_base64 = result.data[0].b64_json
                image_bytes = base64.b64decode(image_base64)

            use_credit(user_id)
            remaining = get_credits(user_id)

            photo_file = BufferedInputFile(image_bytes, filename="image.png")
            await message.answer_photo(
                photo_file,
                caption=f"✅ Готово! Осталось генераций: *{remaining}*",
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
