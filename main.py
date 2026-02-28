import asyncio
import os
import base64
from aiogram import Bot, Dispatcher, types
from aiogram.types import BufferedInputFile
from openai import OpenAI

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

client = OpenAI(api_key=OPENAI_API_KEY)

# Сохраняем последнее фото пользователя
user_photos = {}


@dp.message()
async def handle_message(message: types.Message):

    # Если пользователь отправил фото
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_path = file.file_path

        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        user_photos[message.from_user.id] = file_url

        await message.answer("Фото получено 📸\nТеперь отправьте текст с описанием образа.")
        return

    # Если пользователь отправил текст
    if message.text:
        prompt = message.text
        user_id = message.from_user.id

        # Если есть сохранённое фото — делаем редактирование
        if user_id in user_photos:
            image_url = user_photos[user_id]

            result = client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                image=image_url,
                size="1024x1024"
            )

            del user_photos[user_id]

        else:
            # Обычная генерация
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
