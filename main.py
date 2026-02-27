import asyncio
import os
from aiogram import Bot, Dispatcher, types
from openai import OpenAI

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = OpenAI(api_key=OPENAI_API_KEY)

@dp.message()
async def generate_image(message: types.Message):
    prompt = message.text

    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024"
    )

    image_url = response.data[0].url
    await message.answer_photo(image_url)

async def main():
    await dp.start_polling(bot)

asyncio.run(main())
