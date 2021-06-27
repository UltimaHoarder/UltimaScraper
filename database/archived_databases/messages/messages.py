### messages.py ###

# type: ignore
from sqlalchemy.orm import declarative_base
from database.models.api_table import api_table
from database.models.media_table import template_media_table

Base = declarative_base()

class api_table(api_table,Base):
    api_table.__tablename__ = "messages"

class template_media_table(template_media_table,Base):
    pass