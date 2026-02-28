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


@dp.message()
async def generate_image(message: types.Message):
    prompt = message.text

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
