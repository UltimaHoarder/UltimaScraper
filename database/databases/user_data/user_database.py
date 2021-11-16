### messages.py ###

import copy
import datetime
from typing import cast

import sqlalchemy
from database.databases.user_data.models.api_table import api_table
from database.databases.user_data.models.media_table import template_media_table
from sqlalchemy.orm.decl_api import declarative_base
from sqlalchemy.sql.schema import Column, ForeignKey, Table
from sqlalchemy.sql.sqltypes import Integer

Base = declarative_base()
LegacyBase = declarative_base()


# class user_table(api_table,Base):
#     api_table.__tablename__ = "user_table"


class stories_table(api_table, Base):
    api_table.__tablename__ = "stories"


class posts_table(api_table, Base):
    api_table.__tablename__ = "posts"


class messages_table(api_table, Base):
    api_table.__tablename__ = "messages"
    user_id = cast(int, sqlalchemy.Column(sqlalchemy.Integer))

    class api_legacy_table(api_table, LegacyBase):
        pass


class products_table(api_table, Base):
    api_table.__tablename__ = "products"


class others_table(api_table, Base):
    api_table.__tablename__ = "others"


# class comments_table(api_table,Base):
#     api_table.__tablename__ = "comments"


class media_table(template_media_table, Base):
    class media_legacy_table(template_media_table().legacy_2(LegacyBase), LegacyBase):
        pass


def table_picker(table_name:str, legacy:bool=False):
    if table_name == "Stories":
        table = stories_table
    elif table_name == "Posts":
        table = posts_table
    elif table_name == "Messages":
        table = messages_table if not legacy else messages_table().api_legacy_table
    elif table_name == "Products":
        table = products_table
    elif table_name == "Others":
        table = others_table
    else:
        table = None
        input("Can't find table")
    return table
