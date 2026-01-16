from app.bot import bot, dp

import asyncio
import logging

from maxapi import F
from maxapi.context import MemoryContext, State, StatesGroup
from maxapi.types import BotStarted, Command, MessageCreated, CallbackButton, MessageCallback, BotCommand
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from app.gateway.api import HttpClient

from app.bot.router import router

logging.basicConfig(level=logging.INFO)
dp.include_routers(router)


start_text = '''Чат-бота Medscan 💙'''


class Form(StatesGroup):
    name = State()
    age = State()


@dp.on_started()
async def _():
    logging.info('Бот стартовал!')


@dp.bot_started()
async def bot_started(event: BotStarted):
    await event.bot.send_message(
        chat_id=event.chat_id,
        text='Привет! Отправь мне /start'
    )


@dp.message_created(Command('clear'))
async def hello(event: MessageCreated, context: MemoryContext):
    await context.clear()
    await event.message.answer(f"Ваш контекст был очищен!")


@dp.message_created(Command('data'))
async def hello(event: MessageCreated, context: MemoryContext):
    data = await context.get_data()
    await event.message.answer(f"Ваша контекстная память: {str(data)}")


@dp.message_created(Command('context'))
@dp.message_created(Command('state'))
async def hello(event: MessageCreated, context: MemoryContext):
    data = await context.get_state()
    await event.message.answer(f"Ваше контекстное состояние: {str(data)}")


@dp.message_created(Command('start'))
async def hello(event: MessageCreated):
    builder = InlineKeyboardBuilder()

    builder.row(
        CallbackButton(
            text='Список отделений',
            payload='btn_1'
        ),
        CallbackButton(
            text='Список врачей',
            payload='btn_2'
        )
    )
    builder.row(
        CallbackButton(
            text='Филиалы',
            payload='btn_3'
        )
    )
    builder.row(
        CallbackButton(
            text='Информация о Медскан',
            payload='btn_4'
        )
    )

    await event.message.answer(
        text=start_text,
        attachments=[
            builder.as_markup(),
        ]
    )


@dp.message_callback(F.callback.payload == 'btn_1')
async def hello(event: MessageCallback, context: MemoryContext):
    client = HttpClient()
    data = await client.get("https://demo.infoclinica.ru/specialists/departments")
    departments = [dep.get("name") for dep in data.get("data")]
    await context.set_state(Form.name)
    await event.message.delete()
    await event.message.answer(f'{"\n".join(departments)}')

    await create_keyboard(event)


@dp.message_callback(F.callback.payload == 'btn_2')
async def hello(event: MessageCallback, context: MemoryContext):
    client = HttpClient()
    data = await client.get("https://demo.infoclinica.ru/specialists/doctors")
    docs = [f"{dep.get("name")}" for dep in data.get("data")]
    await context.set_state(Form.age)
    await event.message.delete()
    await event.message.answer(f'{"\n".join(docs)}')
    await create_keyboard(event)


@dp.message_callback(F.callback.payload == 'btn_3')
async def hello(event: MessageCallback, context: MemoryContext):
    client = HttpClient()
    data = await client.get("https://demo.infoclinica.ru/filials/list")
    fil = [f"{dep.get("name")}" for dep in data.get("data")]
    await event.message.delete()
    await event.message.answer(f'{"\n".join(fil)}')
    await create_keyboard(event)

async def create_keyboard(event):
    builder = InlineKeyboardBuilder()

    builder.row(
        CallbackButton(
            text='Список отделений',
            payload='btn_1'
        ),
        CallbackButton(
            text='Список врачей',
            payload='btn_2'
        )
    )
    builder.row(
        CallbackButton(
            text='Филиалы',
            payload='btn_3'
        )
    )
    builder.row(
        CallbackButton(
            text='Информация о Медскан',
            payload='btn_4'
        )
    )

    await event.message.answer(
        text=start_text,
        attachments=[
            builder.as_markup(),
        ]
    )

@dp.message_callback(F.callback.payload == 'btn_4')
async def hello(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await event.message.answer(f'АО «Медскан» – динамично развивающаяся группа компаний и один из лидеров негосударственного сектора здравоохранения в России. Медицинские учреждения холдинга предлагают полный спектр высокотехнологичной медицинской помощи по передовым мировым протоколам')
    await create_keyboard(event)

@dp.message_created(F.message.body.text, Form.name)
async def hello(event: MessageCreated, context: MemoryContext):
    await context.update_data(name=event.message.body.text)

    data = await context.get_data()

    await event.message.answer(f"Приятно познакомиться, {data['name'].title()}!")


@dp.message_created(F.message.body.text, Form.age)
async def hello(event: MessageCreated, context: MemoryContext):
    await context.update_data(age=event.message.body.text)

    await event.message.answer(f"Ого! А мне всего пару недель 😁")


async def main():
    await bot.set_my_commands(
        BotCommand(
            name='/start',
            description='Перезапустить бота'
        ),
        BotCommand(
            name='/clear',
            description='Очищает ваш контекст'
        ),
        BotCommand(
            name='/state',
            description='Показывают ваше контекстное состояние'
        ),
        BotCommand(
            name='/data',
            description='Показывает вашу контекстную память'
        ),
        BotCommand(
            name='/context',
            description='Показывают ваше контекстное состояние'
        )
    )
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())