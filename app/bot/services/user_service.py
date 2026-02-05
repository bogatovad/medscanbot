"""
Сервис работы с зарегистрированными пользователями (БД).
"""
from app.config import settings
from app.crud.registered_user import RegisteredUserRepository
from app.db.base import DatabaseSessionManager
from app.db.models import RegisteredUser


async def get_user_by_max_id(id_max: int) -> RegisteredUser | None:
    """Получить пользователя по id в Max."""
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        return await repo.get_by_max_id(id_max)


async def is_registered(id_max: int) -> bool:
    """Проверить, зарегистрирован ли пользователь по id в Max."""
    user = await get_user_by_max_id(id_max)
    return user is not None


async def save_registered_user(
    *,
    id_max: int,
    pcode: str,
    lastname: str,
    firstname: str,
    midname: str | None,
    bdate: str,
    cllogin: str,
    clpassword: str,
) -> RegisteredUser:
    """Сохранить нового зарегистрированного пользователя. Вызывающий код должен коммитить при необходимости."""
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        user = await repo.save(
            id_max=id_max,
            pcode=pcode,
            lastname=lastname,
            firstname=firstname,
            midname=midname,
            bdate=bdate,
            cllogin=cllogin,
            clpassword=clpassword,
        )
        await session.commit()
        return user


async def update_user_credentials(id_max: int, *, cllogin: str, clpassword: str) -> RegisteredUser | None:
    """Обновить логин и пароль пользователя по id в Max."""
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        user = await repo.update(id_max, cllogin=cllogin, clpassword=clpassword)
        if user:
            await session.commit()
        return user


async def delete_user_by_max_id(id_max: int) -> bool:
    """Удалить пользователя по id в Max. Возвращает True, если запись была удалена."""
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        deleted = await repo.delete_by_max_id(id_max)
        if deleted:
            await session.commit()
        return deleted
