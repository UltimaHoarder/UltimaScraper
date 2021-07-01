### messages.py ###

# type: ignore
from database.databases.user_data.models.api_table import api_table
from database.databases.user_data.models.media_table import template_media_table
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class api_table(api_table, Base):
    api_table.__tablename__ = "messages"


class template_media_table(template_media_table, Base):
    pass
