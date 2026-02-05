from sqlalchemy import (
    Identity,
    func,
    Column,
    Integer,
    DateTime,
)
from sqlalchemy.orm import (
    declarative_base,
)
from sqlalchemy import String

Base = declarative_base()


class RegisteredUser(Base):
    """Зарегистрированные в МИС пользователи (учёт по id в Max)."""

    __tablename__ = "registered_users"

    id = Column(Integer, Identity(always=True), primary_key=True)
    id_max = Column(Integer(), nullable=False, index=True)  # id пользователя в Max
    pcode = Column(String(255), nullable=False)  # идентификатор пациента в ИК (из createPatients)
    lastname = Column(String(255), nullable=False)
    firstname = Column(String(255), nullable=False)
    midname = Column(String(255), nullable=True)
    bdate = Column(String(32), nullable=False)  # ГГГГ-ММ-ДД
    cllogin = Column(String(255), nullable=False)  # логин в ЛК (почта)
    clpassword = Column(String(255), nullable=False)  # пароль в ЛК (для синхронизации с МИС)
    registered_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)