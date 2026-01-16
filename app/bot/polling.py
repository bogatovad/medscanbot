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
async def on_bot_started():
    logging.info('Бот стартовал!')


@dp.bot_started()
async def handle_bot_started(event: BotStarted):
    await event.bot.send_message(
        chat_id=event.chat_id,
        text='Привет! Отправь мне /start'
    )


@dp.message_created(Command('clear'))
async def handle_clear_command(event: MessageCreated, context: MemoryContext):
    await context.clear()
    await event.message.answer("Ваш контекст был очищен!")


@dp.message_created(Command('data'))
async def handle_data_command(event: MessageCreated, context: MemoryContext):
    data = await context.get_data()
    await event.message.answer(f"Ваша контекстная память: {str(data)}")


@dp.message_created(Command('context'))
@dp.message_created(Command('state'))
async def handle_state_command(event: MessageCreated, context: MemoryContext):
    data = await context.get_state()
    await event.message.answer(f"Ваше контекстное состояние: {str(data)}")


@dp.message_created(Command('start'))
async def handle_start_command(event: MessageCreated):
    builder = InlineKeyboardBuilder()

    builder.row(
        CallbackButton(
            text='📅 Текущая запись',
            payload='btn_current_appointment'
        )
    )
    builder.row(
        CallbackButton(
            text='➕ Записаться на прием',
            payload='btn_make_appointment'
        )
    )
    builder.row(
        CallbackButton(
            text='ℹ️ Информация о Медскан',
            payload='btn_info'
        )
    )

    await event.message.answer(
        text=start_text,
        attachments=[
            builder.as_markup(),
        ]
    )


async def create_keyboard(event):
    builder = InlineKeyboardBuilder()

    builder.row(
        CallbackButton(
            text='📅 Текущая запись',
            payload='btn_current_appointment'
        )
    )
    builder.row(
        CallbackButton(
            text='➕ Записаться на прием',
            payload='btn_make_appointment'
        )
    )
    builder.row(
        CallbackButton(
            text='ℹ️ Информация о Медскан',
            payload='btn_info'
        )
    )

    await event.message.answer(
        text=start_text,
        attachments=[
            builder.as_markup(),
        ]
    )


@dp.message_callback(F.callback.payload == 'btn_info')
async def handle_info_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await event.message.answer(
        'АО «Медскан» – динамично развивающаяся группа компаний и один из лидеров '
        'негосударственного сектора здравоохранения в России. Медицинские '
        'учреждения холдинга предлагают полный спектр высокотехнологичной '
        'медицинской помощи по передовым мировым протоколам'
    )
    await create_keyboard(event)


@dp.message_callback(F.callback.payload == 'btn_current_appointment')
async def handle_current_appointment_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await event.message.answer('Функция "Текущая запись" в разработке')
    await create_keyboard(event)


@dp.message_callback(F.callback.payload == 'btn_make_appointment')
async def handle_make_appointment_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await event.message.answer('Функция "Записаться на прием" в разработке')
    await create_keyboard(event)


@dp.message_created(F.message.body.text, Form.name)
async def handle_name_input(event: MessageCreated, context: MemoryContext):
    await context.update_data(name=event.message.body.text)

    data = await context.get_data()

    await event.message.answer(f"Приятно познакомиться, {data['name'].title()}!")


@dp.message_created(F.message.body.text, Form.age)
async def handle_age_input(event: MessageCreated, context: MemoryContext):
    await context.update_data(age=event.message.body.text)

    await event.message.answer("Ого! А мне всего пару недель 😁")


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
