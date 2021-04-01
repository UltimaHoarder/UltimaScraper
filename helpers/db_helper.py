import os
import sqlalchemy
from sqlalchemy.engine.base import Engine
from sqlalchemy.orm.session import sessionmaker
from sqlalchemy.orm import scoped_session
from alembic.config import Config
from alembic import command
from sqlalchemy.exc import IntegrityError
from database.databases.stories import stories
from database.databases.posts import posts
from database.databases.messages import messages


def create_database_session(connection_info, connection_type="sqlite:///", autocommit=False, pool_size=5) -> tuple[scoped_session, Engine]:
    kwargs = {}
    if connection_type == "mysql+mysqldb://":
        kwargs["pool_size"] = pool_size
        kwargs["pool_pre_ping"] = True
        kwargs["max_overflow"] = -1

    engine = sqlalchemy.create_engine(
        f'{connection_type}{connection_info}?charset=utf8mb4', **kwargs)
    session_factory = sessionmaker(bind=engine, autocommit=autocommit)
    Session = scoped_session(session_factory)
    return Session, engine


def run_revisions(alembic_directory: str, database_path: str = ""):
    ini_path = os.path.join(alembic_directory, "alembic.ini")
    script_location = os.path.join(alembic_directory, "alembic")
    full_database_path = f'sqlite:///{database_path}'
    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option('script_location', script_location)
    alembic_cfg.set_main_option('sqlalchemy.url', full_database_path)
    x = command.upgrade(alembic_cfg, 'head')
    x = command.revision(alembic_cfg, autogenerate=True, message="content")


def run_migrations(alembic_directory: str, database_path: str, api) -> None:
    ini_path = os.path.join(alembic_directory, "alembic.ini")
    script_location = os.path.join(alembic_directory, "alembic")
    full_database_path = f'sqlite:///{database_path}'
    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option('script_location', script_location)
    alembic_cfg.set_main_option('sqlalchemy.url', full_database_path)
    x = command.upgrade(alembic_cfg, 'head')


class database_collection(object):
    def __init__(self) -> None:
        self.stories_database = stories
        self.post_database = posts
        self.message_database = messages

    def chooser(self, database_name):
        if database_name == "stories":
            database = self.stories_database
        elif database_name == "posts":
            database = self.post_database
        elif database_name == "messages":
            database = self.message_database
        else:
            database = None
            print("DB CHOOSER ERROR")
            input()
        return database


def create_auth_array(item):
    auth_array = dict(item)
    auth_array["support_2fa"] = False
    return auth_array


def get_or_create(session, model, defaults=None, fbkwargs={}):
    instance = session.query(model).filter_by(**fbkwargs).one_or_none()
    if instance:
        return instance, True
    else:
        fbkwargs |= defaults or {}
        instance = model(**fbkwargs)
        try:
            session.add(instance)
            session.flush()
        except IntegrityError:
            session.rollback()
            instance = session.query(model).filter_by(**fbkwargs).one()
            return instance, False
        else:
            return instance, True
