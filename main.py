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

user_photos = {}


@dp.message()
async def handle_message(message: types.Message):

    # Если пользователь отправил фото
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        downloaded_file = await bot.download_file(file.file_path)

        image_bytes = downloaded_file.read()
        user_photos[message.from_user.id] = image_bytes

        await message.answer("Фото получено 📸\nТеперь отправьте текст с описанием образа.")
        return

    # Если пользователь отправил текст
    if message.text:
        prompt = message.text
        user_id = message.from_user.id

        # Если есть фото — делаем редактирование
        if user_id in user_photos:
            original_image = user_photos[user_id]

            image_base64 = base64.b64encode(original_image).decode("utf-8")

            result = client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                image=image_base64,
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

        output_base64 = result.data[0].b64_json
        output_bytes = base64.b64decode(output_base64)

        photo = BufferedInputFile(output_bytes, filename="image.png")

        await message.answer_photo(photo)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
