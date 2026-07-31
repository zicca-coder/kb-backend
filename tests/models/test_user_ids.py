from sqlalchemy import BigInteger, UniqueConstraint

from app.models.user import User
from app.models.user_agent import UserAgent


def test_user_id_is_non_autoincrement_bigint() -> None:
    column = User.__table__.c.id

    assert isinstance(column.type, BigInteger)
    assert column.primary_key is True
    assert column.autoincrement is False


def test_user_agent_user_id_is_bigint_foreign_key() -> None:
    column = UserAgent.__table__.c.user_id

    assert isinstance(column.type, BigInteger)
    assert {foreign_key.target_fullname for foreign_key in column.foreign_keys} == {
        "users.id",
    }


def test_user_agent_agent_id_unique_constraint_is_kept() -> None:
    constraints = [
        constraint
        for constraint in UserAgent.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert any(
        constraint.name == "uk_user_agents_agent_id"
        and [column.name for column in constraint.columns] == ["agent_id"]
        for constraint in constraints
    )


def test_user_agent_foreign_key_ondelete_behavior_is_unchanged() -> None:
    foreign_key = next(iter(UserAgent.__table__.c.user_id.foreign_keys))

    assert foreign_key.ondelete == "RESTRICT"
    assert foreign_key.onupdate == "RESTRICT"
