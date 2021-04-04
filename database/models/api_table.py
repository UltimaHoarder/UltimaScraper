### api_table.py ###

from datetime import datetime
from typing import cast
import sqlalchemy
from sqlalchemy.ext.declarative import declarative_base

class api_table():
    __tablename__ = ""
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    post_id = sqlalchemy.Column(sqlalchemy.Integer, unique=True, nullable=False)
    text = sqlalchemy.Column(sqlalchemy.String)
    price = sqlalchemy.Column(sqlalchemy.Integer)
    paid = sqlalchemy.Column(sqlalchemy.Integer)
    created_at = cast(datetime,sqlalchemy.Column(sqlalchemy.TIMESTAMP))

    def legacy(self,Base,table_name):
        class legacy_api_table(Base):
            __tablename__ = table_name
            id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
            text = sqlalchemy.Column(sqlalchemy.String)
            price = sqlalchemy.Column(sqlalchemy.Integer)
            paid = sqlalchemy.Column(sqlalchemy.Integer)
            created_at = sqlalchemy.Column(sqlalchemy.DATETIME)
        return legacy_api_table