from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateTable
from sqlmodel import select
from ultima_scraper_backend.api.routes.users import _paginate_user_query
from ultima_scraper_db_archive import UserInfoModel, UserModel


@pytest.mark.parametrize("descending", [True, False])
def test_narrow_page_preserves_filters_order_and_missing_info(descending):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(CreateTable(UserModel.__table__))
        conn.execute(CreateTable(UserInfoModel.__table__))
        conn.execute(
            UserModel.__table__.insert(),
            [
                {
                    "id": i,
                    "username": f"user{i}",
                    "active": i != 4,
                    "created_at": datetime(2026, 1, i, tzinfo=UTC),
                }
                for i in range(1, 5)
            ],
        )
        conn.execute(
            UserInfoModel.__table__.insert(),
            [{"id": i, "user_id": i, "price": float(i)} for i in (1, 3)],
        )
        sort = UserModel.created_at.desc() if descending else UserModel.created_at.asc()
        original = (
            select(UserModel, UserInfoModel)
            .outerjoin(UserInfoModel, UserModel.id == UserInfoModel.user_id)
            .where(UserModel.active.is_(True))
            .order_by(sort)
        )
        expected = conn.execute(original.offset(1).limit(2)).all()
        actual = conn.execute(_paginate_user_query(original, sort, 1, 2)).all()
        assert actual == expected
        assert len(actual) == 2
        assert any(row._mapping["user_id"] is None for row in actual)
    engine.dispose()
