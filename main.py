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

    # 📸 Если пришло фото
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        downloaded_file = await bot.download_file(file.file_path)

        image_bytes = downloaded_file.read()
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        user_photos[message.from_user.id] = image_base64

        await message.answer("Фото получено 📸\nТеперь отправьте описание образа.")
        return

    # 📝 Если пришёл текст
    if message.text:
        prompt = message.text.strip()
        user_id = message.from_user.id

        # Если есть фото → редактируем через responses API
        if user_id in user_photos:

            base64_image = user_photos[user_id]

            response = client.responses.create(
                model="gpt-4.1",
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": f"{prompt}. Preserve original facial features and keep exact identity."
                            },
                            {
                                "type": "input_image",
                                "image_base64": base64_image,
                            },
                        ],
                    }
                ],
                tools=[{"type": "image_generation"}],
            )

            # извлекаем изображение
            for output in response.output:
                for content in output.content:
                    if content.type == "image_generation":
                        image_base64 = content.image_base64

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
