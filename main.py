import asyncio
import os
import base64
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.types import BufferedInputFile
from openai import OpenAI

# Настройка логирования
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

# Хранилище фото пользователей
user_photos: dict[int, str] = {}
user_states: dict[int, str] = {}  # 'waiting_prompt'


def translate_to_english_prompt(user_prompt: str) -> str:
    """Переводим промпт на английский через GPT для лучшей генерации"""
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional image prompt translator and enhancer. "
                        "Translate the user's prompt to English if it's not already in English. "
                        "Then enhance it to be more detailed and vivid for image generation. "
                        "Keep it concise (max 200 words). Return ONLY the enhanced English prompt, nothing else."
                    )
                },
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=300,
            temperature=0.7
        )
        translated = response.choices[0].message.content.strip()
        logger.info(f"Промпт переведён: '{user_prompt}' → '{translated}'")
        return translated
    except Exception as e:
        logger.warning(f"Не удалось перевести промпт: {e}")
        return user_prompt  # fallback на оригинальный


def build_face_preservation_prompt(user_prompt: str) -> str:
    """Строим мощный промпт с сохранением черт лица"""
    translated = translate_to_english_prompt(user_prompt)
    return (
        f"{translated}. "
        "CRITICAL: Preserve the exact facial features, face shape, eyes, nose, mouth, skin tone, "
        "and overall identity of the person in the reference image. "
        "The person must be clearly recognizable as the same individual. "
        "High quality, photorealistic, 8K resolution."
    )


@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id

    # 📸 Если пришло фото
    if message.photo:
        try:
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            downloaded_file = await bot.download_file(file.file_path)
            image_bytes = downloaded_file.read()
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")

            user_photos[user_id] = image_base64
            user_states[user_id] = "waiting_prompt"

            await message.answer(
                "📸 Фото получено!\n\n"
                "Теперь напишите, что хотите изменить или как стилизовать образ.\n"
                "Можно писать на *русском* или *английском* — я разберусь 😊",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка при сохранении фото: {e}")
            await message.answer("❌ Не удалось обработать фото. Попробуйте ещё раз.")
        return

    # 📝 Если пришёл текст
    if message.text:
        prompt = message.text.strip()

        # Команда /start или /help
        if prompt.startswith("/start") or prompt.startswith("/help"):
            await message.answer(
                "👋 Привет! Я бот для генерации изображений.\n\n"
                "🖼 *Генерация по описанию:*\n"
                "Просто напишите текст — и я создам картинку.\n\n"
                "🧑‍🎨 *Редактирование с сохранением лица:*\n"
                "1. Отправьте фото\n"
                "2. Напишите, как изменить образ\n\n"
                "Поддерживаю русский и английский языки!",
                parse_mode="Markdown"
            )
            return

        # Команда /reset
        if prompt.startswith("/reset"):
            user_photos.pop(user_id, None)
            user_states.pop(user_id, None)
            await message.answer("🔄 Фото сброшено. Начните заново.")
            return

        await message.answer("⏳ Генерирую изображение, подождите...")

        try:
            # Если есть сохранённое фото → редактируем с сохранением лица
            if user_id in user_photos:
                base64_image = user_photos[user_id]
                enhanced_prompt = build_face_preservation_prompt(prompt)

                logger.info(f"Редактирование фото для user {user_id}, промпт: {enhanced_prompt}")

                response = client.responses.create(
                    model="gpt-4.1",
                    input=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": enhanced_prompt
                                },
                                {
                                    "type": "input_image",
                                    "image_base64": base64_image,
                                },
                            ],
                        }
                    ],
                    tools=[{"type": "image_generation",
                            "quality": "high",
                            "size": "1024x1024"}],
                )

                # Извлекаем изображение из ответа
                image_base64 = None
                for output in response.output:
                    if hasattr(output, 'content'):
                        for content in output.content:
                            if hasattr(content, 'type') and content.type == "image_generation_call":
                                image_base64 = content.result
                                break
                    if image_base64:
                        break

                # Альтернативный способ извлечения
                if not image_base64:
                    for item in response.output:
                        if hasattr(item, 'type') and item.type == "image_generation_call":
                            image_base64 = item.result
                            break

                if not image_base64:
                    raise ValueError("Не удалось извлечь изображение из ответа API")

                # Очищаем фото после использования
                del user_photos[user_id]
                user_states.pop(user_id, None)

            else:
                # Обычная генерация без фото
                translated_prompt = translate_to_english_prompt(prompt)
                logger.info(f"Генерация для user {user_id}, промпт: {translated_prompt}")

                result = client.images.generate(
                    model="gpt-image-1",
                    prompt=translated_prompt,
                    size="1024x1024",
                    quality="high",
                )
                image_base64 = result.data[0].b64_json

            # Отправляем изображение
            image_bytes = base64.b64decode(image_base64)
            photo_file = BufferedInputFile(image_bytes, filename="image.png")
            await message.answer_photo(
                photo_file,
                caption="✅ Готово!"
            )

        except Exception as e:
            logger.error(f"Ошибка генерации для user {user_id}: {e}", exc_info=True)
            error_msg = str(e)

            if "content_policy" in error_msg.lower() or "safety" in error_msg.lower():
                await message.answer(
                    "⚠️ Запрос нарушает правила контента. "
                    "Попробуйте переформулировать описание."
                )
            elif "billing" in error_msg.lower() or "quota" in error_msg.lower():
                await message.answer(
                    "💳 Проблема с балансом OpenAI API. "
                    "Проверьте настройки аккаунта."
                )
            else:
                await message.answer(
                    f"❌ Ошибка при генерации:\n`{error_msg[:200]}`\n\nПопробуйте ещё раз.",
                    parse_mode="Markdown"
                )


async def main():
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
