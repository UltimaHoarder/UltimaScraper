### api_table.py ###

from datetime import datetime
from typing import cast
import sqlalchemy


class template_media_table:
    __tablename__ = "medias"
    id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
    media_id = sqlalchemy.Column(sqlalchemy.Integer, unique=True)
    post_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
    link = cast(str, sqlalchemy.Column(sqlalchemy.String))
    directory = cast(str, sqlalchemy.Column(sqlalchemy.String))
    filename = cast(str, sqlalchemy.Column(sqlalchemy.String))
    size = cast(int, sqlalchemy.Column(sqlalchemy.Integer, default=None))
    api_type = cast(str, sqlalchemy.Column(sqlalchemy.String))
    media_type = sqlalchemy.Column(sqlalchemy.String)
    preview = sqlalchemy.Column(sqlalchemy.Integer, default=0)
    linked = sqlalchemy.Column(sqlalchemy.String, default=None)
    downloaded = cast(bool, sqlalchemy.Column(sqlalchemy.Integer, default=0))
    created_at = cast(datetime, sqlalchemy.Column(sqlalchemy.TIMESTAMP))

    def legacy(self, Base):
        class legacy_media_table(Base):
            __tablename__ = "medias"
            id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
            post_id = sqlalchemy.Column(sqlalchemy.Integer)
            link = sqlalchemy.Column(sqlalchemy.String)
            directory = sqlalchemy.Column(sqlalchemy.String)
            filename = sqlalchemy.Column(sqlalchemy.String)
            size = sqlalchemy.Column(sqlalchemy.Integer, default=None)
            media_type = sqlalchemy.Column(sqlalchemy.String)
            downloaded = sqlalchemy.Column(sqlalchemy.Integer, default=0)
            created_at = sqlalchemy.Column(sqlalchemy.DATETIME)

        return legacy_media_table

    def legacy_2(self, Base):
        class legacy_media_table(Base):
            __tablename__ = "medias"
            id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
            media_id = sqlalchemy.Column(sqlalchemy.Integer, unique=True)
            post_id = sqlalchemy.Column(sqlalchemy.Integer, nullable=False)
            link = cast(str, sqlalchemy.Column(sqlalchemy.String))
            directory = cast(str, sqlalchemy.Column(sqlalchemy.String))
            filename = cast(str, sqlalchemy.Column(sqlalchemy.String))
            size = cast(int, sqlalchemy.Column(sqlalchemy.Integer, default=None))
            media_type = sqlalchemy.Column(sqlalchemy.String)
            preview = sqlalchemy.Column(sqlalchemy.Integer, default=0)
            linked = sqlalchemy.Column(sqlalchemy.String, default=None)
            downloaded = cast(bool, sqlalchemy.Column(sqlalchemy.Integer, default=0))
            created_at = cast(datetime, sqlalchemy.Column(sqlalchemy.TIMESTAMP))

        return legacy_media_table
