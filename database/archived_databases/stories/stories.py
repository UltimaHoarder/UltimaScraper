# type: ignore
### posts.py ###

from sqlalchemy.orm import declarative_base
from database.databases.user_data.models.api_table import api_table
from database.databases.user_data.models.media_table import template_media_table

Base = declarative_base()


class api_table(api_table, Base):
    api_table.__tablename__ = "stories"


class template_media_table(template_media_table, Base):
    pass
