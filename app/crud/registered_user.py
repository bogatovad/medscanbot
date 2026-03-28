from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RegisteredUser


class RegisteredUserRepository:
    """Репозиторий для учёта зарегистрированных в МИС пользователей (по id_max)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_max_id(self, id_max: int) -> RegisteredUser | None:
        """Получить данные пользователя по id в Max."""
        result = await self.session.scalars(
            select(RegisteredUser).where(RegisteredUser.id_max == id_max)
        )
        return result.one_or_none()

    async def get_by_login_and_password(self, login: str, password: str) -> RegisteredUser | None:
        """Получить данные пользователя по логину и паролю."""
        result = await self.session.scalars(
            select(RegisteredUser).where(
                RegisteredUser.cllogin == login,
                RegisteredUser.clpassword == password
            )
        )
        return result.one_or_none()

    async def save(
        self,
        *,
        id_max: int | None,
        pcode: str,
        lastname: str,
        firstname: str,
        midname: str | None,
        bdate: str,
        cllogin: str,
        clpassword: str,
    ) -> RegisteredUser:
        """Сохранить нового зарегистрированного пользователя."""
        user = RegisteredUser(
            id_max=id_max,
            pcode=pcode,
            lastname=lastname,
            firstname=firstname,
            midname=midname,
            bdate=bdate,
            cllogin=cllogin,
            clpassword=clpassword,
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def update(
        self,
        id_max: int,
        *,
        pcode: str | None = None,
        lastname: str | None = None,
        firstname: str | None = None,
        midname: str | None = None,
        bdate: str | None = None,
        cllogin: str | None = None,
        clpassword: str | None = None,
    ) -> RegisteredUser | None:
        """Обновить данные пользователя по id_max. Передаются только меняемые поля."""
        user = await self.get_by_max_id(id_max)
        if not user:
            return None
        if pcode is not None:
            user.pcode = pcode
        if lastname is not None:
            user.lastname = lastname
        if firstname is not None:
            user.firstname = firstname
        if midname is not None:
            user.midname = midname
        if bdate is not None:
            user.bdate = bdate
        if cllogin is not None:
            user.cllogin = cllogin
        if clpassword is not None:
            user.clpassword = clpassword
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def delete_by_max_id(self, id_max: int) -> bool:
        """Удалить пользователя по id в Max. Возвращает True, если запись была удалена."""
        user = await self.get_by_max_id(id_max)
        if not user:
            return False
        await self.session.delete(user)
        await self.session.flush()
        return True
