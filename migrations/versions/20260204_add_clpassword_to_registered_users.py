"""add clpassword to registered_users

Revision ID: add_clpassword
Revises: 9d6b55dae54f
Create Date: 2026-02-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "add_clpassword"
down_revision: Union[str, Sequence[str], None] = "9d6b55dae54f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Добавляем колонку; существующим строкам проставляем Zima2026
    op.add_column(
        "registered_users",
        sa.Column("clpassword", sa.String(255), nullable=True),
    )
    op.alter_column(
        "registered_users",
        "clpassword",
        existing_type=sa.String(255),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("registered_users", "clpassword")
