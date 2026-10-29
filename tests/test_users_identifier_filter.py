import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects import postgresql
from ultima_scraper_backend.api.routes.users import _apply_identifier_filter
from ultima_scraper_db_archive import UserModel


@pytest.fixture
def connection():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, active BOOLEAN)"
            )
        )
        conn.execute(text("CREATE TABLE user_aliases (user_id INTEGER, username TEXT)"))
        conn.execute(
            text(
                "INSERT INTO users VALUES (1, 'SxnfulPrincess', 1), (2, 'renamed', 0), (3, NULL, 1), (123, 'numeric', 1), (4, 'user123', 1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO user_aliases VALUES (1, 'sxnfulprincess'), (2, 'SxnfulPrincess_old'), (2, 'sxnfulprincess_other'), (3, 'sxnfulprincess'), (99, 'sxnfulprincess'), (2, '123')"
            )
        )
        yield conn
    engine.dispose()


@pytest.mark.parametrize(
    "search, expected",
    [
        ("  SXNFULPRINCESS  ", [1, 2, 3]),
        ("00123", [123]),
        ("123", [2, 4, 123]),
        ("missing", []),
        (" ", [1, 2, 3, 4, 123]),
    ],
)
def test_identifier_matching_and_counts(connection, search, expected):
    query = _apply_identifier_filter(select(UserModel.id), search)
    assert connection.execute(query.order_by(UserModel.id)).scalars().all() == expected
    count = _apply_identifier_filter(
        select(func.count()).select_from(UserModel), search
    )
    assert connection.execute(count).scalar_one() == len(expected)


def test_identifier_filter_preserves_other_filters_and_pagination(connection):
    query = (
        _apply_identifier_filter(
            select(UserModel.id).where(UserModel.active.is_(True)), "sxnfulprincess"
        )
        .order_by(UserModel.id.desc())
        .limit(1)
        .offset(1)
    )
    assert connection.execute(query).scalars().all() == [1]


def test_identifier_search_uses_independent_indexable_branches():
    sql = str(
        _apply_identifier_filter(select(UserModel.id), "sxnfulprincess").compile(
            dialect=postgresql.dialect()
        )
    )
    assert "UNION" in sql
    assert "EXISTS" not in sql
    assert "users.username ILIKE" in sql
    assert "user_aliases.username ILIKE" in sql
