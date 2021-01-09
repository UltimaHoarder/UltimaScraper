
import os
import sqlalchemy
from sqlalchemy.orm.session import sessionmaker
from sqlalchemy.orm import scoped_session
from alembic.config import Config
from alembic import command
from database.databases.stories import stories
from database.databases.posts import posts
from database.databases.messages import messages


def create_database_session(metadata_path):
    engine = sqlalchemy.create_engine(f'sqlite:///{metadata_path}')
    session_factory = sessionmaker(bind=engine)
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
    print


def run_migrations(alembic_directory: str, database_path: str) -> None:
    ini_path = os.path.join(alembic_directory, "alembic.ini")
    script_location = os.path.join(alembic_directory, "alembic")
    full_database_path = f'sqlite:///{database_path}'
    alembic_cfg = Config(ini_path)
    alembic_cfg.set_main_option('script_location', script_location)
    alembic_cfg.set_main_option('sqlalchemy.url', full_database_path)
    x = command.upgrade(alembic_cfg, 'head')
    print


class database_collection(object):
    def __init__(self) -> None:
        self.stories_database = stories
        self.post_database = posts
        self.message_database = messages

    def chooser(self, database_name):
        database = None
        if database_name == "stories":
            database = self.stories_database
        elif database_name == "posts":
            database = self.post_database
        elif database_name == "messages":
            database = self.message_database
        else:
            print("ERROR")
            input()
        return database
