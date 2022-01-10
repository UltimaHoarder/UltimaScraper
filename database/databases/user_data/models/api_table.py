### api_table.py ###

from datetime import datetime
from typing import cast

import sqlalchemy
from sqlalchemy.orm import declarative_base  # type: ignore

LegacyBase = declarative_base()


class api_table:
    __tablename__ = ""
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    post_id = sqlalchemy.Column(sqlalchemy.Integer, unique=True, nullable=False)
    text = sqlalchemy.Column(sqlalchemy.String)
    price = cast(int, sqlalchemy.Column(sqlalchemy.Integer))
    paid = sqlalchemy.Column(sqlalchemy.Integer)
    archived = cast(bool, sqlalchemy.Column(sqlalchemy.Boolean, default=False))
    created_at = cast(datetime, sqlalchemy.Column(sqlalchemy.TIMESTAMP))

    def legacy(self, table_name):
        class legacy_api_table(LegacyBase):
            __tablename__ = table_name
            id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
            text = sqlalchemy.Column(sqlalchemy.String)
            price = sqlalchemy.Column(sqlalchemy.Integer)
            paid = sqlalchemy.Column(sqlalchemy.Integer)
            created_at = sqlalchemy.Column(sqlalchemy.DATETIME)

        return legacy_api_table

    def convert(self):
        item = self.__dict__
        item.pop("_sa_instance_state")
        return item
