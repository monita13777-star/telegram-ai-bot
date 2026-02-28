@dp.message()
async def generate_image(message: types.Message):
    prompt = message.text

    result = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024"
    )

    image_base64 = result.data[0].b64_json

    from aiogram.types import BufferedInputFile
    import base64

    image_bytes = base64.b64decode(image_base64)

    photo = BufferedInputFile(image_bytes, filename="image.png")

    await message.answer_photo(photo)
