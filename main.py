import asyncio
import os
import base64
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import BufferedInputFile
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)

user_photos: dict[int, str] = {}


def analyze_face(image_base64: str) -> str:
    """Детально анализируем лицо через gpt-4o vision"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Analyze this person's appearance in extreme detail for image generation. "
                                "Describe EXACTLY:\n"
                                "- Face shape (oval, round, square, heart, etc)\n"
                                "- Eye color, shape, and size\n"
                                "- Nose shape and size\n"
                                "- Lip shape and fullness\n"
                                "- Eyebrow shape and color\n"
                                "- Hair color (exact shade), length, texture, and style\n"
                                "- Skin tone (exact description)\n"
                                "- Any distinctive features (freckles, dimples, etc)\n"
                                "- Age appearance\n"
                                "- Gender\n"
                                "Be extremely precise. This will be used to recreate this exact person."
                            )
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=600,
        )
        description = response.choices[0].message.content.strip()
        logger.info(f"Анализ лица: {description}")
        return description
    except Exception as e:
        logger.warning(f"Анализ лица не удался: {e}")
        return ""


def translate_and_enhance(user_prompt: str) -> str:
    """Переводим и улучшаем промпт"""
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


def build_face_prompt(face_description: str, user_prompt: str) -> str:
    """Строим финальный промпт с максимальным сохранением лица"""
    translated = translate_and_enhance(user_prompt)
    return (
        f"A photorealistic portrait of a person with these EXACT features: {face_description}. "
        f"Scene and style: {translated}. "
        "CRITICAL: The person must have exactly the same face, eyes, nose, lips, hair color and skin tone "
        "as described above. Do not change any facial features. Ultra high quality, 8K, photorealistic."
    )


@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id

    if message.photo:
        try:
            await message.answer("📸 Анализирую фото, подождите...")
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            downloaded = await bot.download_file(file.file_path)
            image_bytes = downloaded.read()
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")

            # Сразу анализируем лицо и сохраняем описание
            face_description = analyze_face(image_base64)
            user_photos[user_id] = {
                "base64": image_base64,
                "face_description": face_description
            }

            await message.answer(
                "📸 Фото проанализировано!\n\nНапишите описание — как изменить образ.\n"
                "Можно на *русском* или *английском* 😊",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка сохранения фото: {e}")
            await message.answer("❌ Не удалось обработать фото. Попробуйте ещё раз.")
        return

    if message.text:
        prompt = message.text.strip()

        if prompt.startswith("/start") or prompt.startswith("/help"):
            await message.answer(
                "👋 Привет! Я генерирую изображения с помощью ИИ.\n\n"
                "🖼 *Просто напишите текст* — создам картинку.\n\n"
                "🧑‍🎨 *Чтобы изменить своё фото:*\n"
                "1. Отправьте фото\n"
                "2. Напишите, что хотите изменить\n\n"
                "Поддерживаю русский и английский языки!\n\n"
                "/reset — сбросить сохранённое фото",
                parse_mode="Markdown"
            )
            return

        if prompt.startswith("/reset"):
            user_photos.pop(user_id, None)
            await message.answer("🔄 Фото сброшено. Можете начать заново.")
            return

        await message.answer("⏳ Генерирую, подождите...")

        try:
            image_base64 = None

            if user_id in user_photos:
                saved = user_photos[user_id]
                face_description = saved["face_description"]
                final_prompt = build_face_prompt(face_description, prompt)
                logger.info(f"[{user_id}] Финальный промпт: {final_prompt}")

                result = client.images.generate(
                    model="gpt-image-1",
                    prompt=final_prompt,
                    size="1024x1024",
                    quality="high",
                )
                image_base64 = result.data[0].b64_json
                del user_photos[user_id]

            else:
                translated_prompt = translate_and_enhance(prompt)
                logger.info(f"[{user_id}] Генерация. Промпт: {translated_prompt}")

                result = client.images.generate(
                    model="gpt-image-1",
                    prompt=translated_prompt,
                    size="1024x1024",
                    quality="high",
                )
                image_base64 = result.data[0].b64_json

            if not image_base64:
                raise ValueError("Изображение не получено от API")

            image_bytes = base64.b64decode(image_base64)
            photo_file = BufferedInputFile(image_bytes, filename="image.png")
            await message.answer_photo(photo_file, caption="✅ Готово!")

        except Exception as e:
            logger.error(f"[{user_id}] Ошибка: {e}", exc_info=True)
            err = str(e)

            if "content_policy" in err.lower() or "safety" in err.lower():
                await message.answer("⚠️ Запрос нарушает правила контента. Попробуйте переформулировать.")
            elif "billing" in err.lower() or "quota" in err.lower():
                await message.answer("💳 Проблема с балансом OpenAI. Проверьте аккаунт.")
            else:
                await message.answer(f"❌ Ошибка:\n`{err[:300]}`", parse_mode="Markdown")


async def main():
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
