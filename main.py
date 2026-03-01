import asyncio
import os
import base64
import logging
import httpx
import io
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
FAL_API_KEY = os.getenv("FAL_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)

user_photos: dict[int, str] = {}


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


async def upload_to_fal(image_bytes: bytes) -> str:
    """Загружаем фото на fal.ai через правильный endpoint"""
    async with httpx.AsyncClient(timeout=60) as http:
        response = await http.post(
            "https://fal.run/fal-ai/imageutils/resize",
            headers={"Authorization": f"Key {FAL_API_KEY}"},
            files={"image": ("image.jpg", image_bytes, "image/jpeg")},
            data={"width": "1024", "height": "1024"}
        )
        logger.info(f"Upload: {response.status_code} {response.text[:200]}")

        if response.status_code != 200:
            raise ValueError(f"Ошибка загрузки: {response.text[:200]}")

        data = response.json()
        return data.get("image", {}).get("url") or data.get("url")


async def generate_with_flux_pulid(image_base64: str, prompt: str) -> bytes:
    """Генерация через Flux PuLID — лучшее сохранение лица"""
    translated_prompt = translate_and_enhance(prompt)
    image_bytes = base64.b64decode(image_base64)

    async with httpx.AsyncClient(timeout=180) as http:
        # Сначала загружаем через fal storage
        upload_response = await http.put(
            "https://fal.run/files/upload",
            headers={
                "Authorization": f"Key {FAL_API_KEY}",
                "Content-Type": "image/jpeg",
                "X-Fal-File-Name": "photo.jpg"
            },
            content=image_bytes
        )
        logger.info(f"Upload: {upload_response.status_code} {upload_response.text[:300]}")

        if upload_response.status_code not in (200, 201):
            raise ValueError(f"Ошибка загрузки фото: {upload_response.text[:200]}")

        upload_data = upload_response.json()
        image_url = upload_data.get("url") or upload_data.get("access_url")
        logger.info(f"Фото загружено: {image_url}")

        if not image_url:
            raise ValueError("URL фото не получен")

        # Генерируем с Flux PuLID
        gen_response = await http.post(
            "https://fal.run/fal-ai/flux-pulid",
            headers={
                "Authorization": f"Key {FAL_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "prompt": translated_prompt,
                "reference_image_url": image_url,
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
            raise ValueError(f"Ошибка генерации: {gen_data}")

        result_url = gen_data["images"][0]["url"]
        img_response = await http.get(result_url)
        return img_response.content


@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id

    if message.photo:
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
            if user_id in user_photos:
                saved_base64 = user_photos[user_id]
                image_bytes = await generate_with_flux_pulid(saved_base64, prompt)
                del user_photos[user_id]

                photo_file = BufferedInputFile(image_bytes, filename="image.png")
                await message.answer_photo(photo_file, caption="✅ Готово!")

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
                image_bytes = base64.b64decode(image_base64)
                photo_file = BufferedInputFile(image_bytes, filename="image.png")
                await message.answer_photo(photo_file, caption="✅ Готово!")

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
