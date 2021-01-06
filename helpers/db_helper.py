
import sqlalchemy
from sqlalchemy.orm.session import sessionmaker
from sqlalchemy.ext.declarative.api import declarative_base
from sqlalchemy.orm import scoped_session


def create_database_session(metadata_path):
    engine = sqlalchemy.create_engine(f'sqlite:///{metadata_path}')
    session_factory = sessionmaker(bind=engine)
    Session = scoped_session(session_factory)
    return Session, engine


class type_0(object):
    def __init__(self):
        base = declarative_base()
        self.api_table = base
        self.media_table = base


def create_api_table(Base, api_type, engine=None):
    class api_table(Base):
        __tablename__ = api_type.lower()
        id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
        text = sqlalchemy.Column(sqlalchemy.String)
        price = sqlalchemy.Column(sqlalchemy.Integer)
        paid = sqlalchemy.Column(sqlalchemy.Integer)
        created_at = sqlalchemy.Column(sqlalchemy.TIMESTAMP)
    return api_table


def create_media_table(Base, engine=None):
    class media_table(Base):
        __tablename__ = "medias"
        id = sqlalchemy.Column(sqlalchemy.Integer, primary_key=True)
        post_id = sqlalchemy.Column(sqlalchemy.Integer)
        link = sqlalchemy.Column(sqlalchemy.String)
        directory = sqlalchemy.Column(sqlalchemy.String)
        filename = sqlalchemy.Column(sqlalchemy.Integer)
        size = sqlalchemy.Column(sqlalchemy.Integer, default=None)
        media_type = sqlalchemy.Column(sqlalchemy.String)
        downloaded = sqlalchemy.Column(sqlalchemy.Integer, default=0)
        created_at = sqlalchemy.Column(sqlalchemy.TIMESTAMP)
    return media_table
