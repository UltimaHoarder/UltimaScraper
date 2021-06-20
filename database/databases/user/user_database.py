### messages.py ###

from sqlalchemy.sql.schema import Column, ForeignKey, Table
from sqlalchemy.sql.sqltypes import Integer
from database.models.api_table import api_table
from database.models.media_table import media_table
from sqlalchemy.orm import declarative_base  # type: ignore

Base = declarative_base()


# class user_table(api_table,Base):
#     api_table.__tablename__ = "user_table"


class stories_table(api_table, Base):
    api_table.__tablename__ = "stories"


class posts_table(api_table, Base):
    api_table.__tablename__ = "posts"


class messages_table(api_table, Base):
    api_table.__tablename__ = "messages"


# class comments_table(api_table,Base):
#     api_table.__tablename__ = "comments"


class media_table(media_table, Base):
    pass
