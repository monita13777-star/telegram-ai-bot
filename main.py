import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import BufferedInputFile
from openai import OpenAI
import base64

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)

user_photos = {}

MAX_PROMPT_LENGTH = 1500  # ограничение длины


@dp.message()
async def handle_message(message: types.Message):

    # Если пришло фото
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        downloaded_file = await bot.download_file(file.file_path)

        image_bytes = downloaded_file.read()
        user_photos[message.from_user.id] = image_bytes

        await message.answer("Фото получено 📸\nТеперь отправьте описание образа.")
        return

    # Если пришёл текст
    if message.text:
        prompt = message.text.strip()

        if len(prompt) > MAX_PROMPT_LENGTH:
            await message.answer("⚠️ Слишком длинное описание. Укоротите текст.")
            return

        user_id = message.from_user.id

        # Если есть фото → редактирование
        if user_id in user_photos:
            original_image = user_photos[user_id]

            # автоматически усиливаем сохранение лица
            safe_prompt = (
                f"{prompt}, preserve original facial features, "
                f"keep the same person, maintain exact face identity, "
                f"do not change facial structure"
            )

            result = client.images.generate(
                model="gpt-image-1",
                prompt=safe_prompt,
                input_image=original_image,
                size="1024x1024"
            )

            del user_photos[user_id]

        else:
            # обычная генерация
            result = client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size="1024x1024"
            )

        image_base64 = result.data[0].b64_json
        image_bytes = base64.b64decode(image_base64)

        photo = BufferedInputFile(image_bytes, filename="image.png")

        await message.answer_photo(photo)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
