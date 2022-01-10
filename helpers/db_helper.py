import os
from pathlib import Path
from typing import Any, Literal
import sqlalchemy
from sqlalchemy.engine.base import Engine
from sqlalchemy.orm.session import Session, sessionmaker
from sqlalchemy.orm import scoped_session
from alembic.config import Config
from alembic import command
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.functions import func
from apis.onlyfans.classes.extras import media_types
from database.databases.user_data import user_database


async def import_database(database_path: Path):
    _Session, engine = create_database_session(database_path)
    database_session: Session = _Session()
    return database_session, engine


def create_database_session(
    connection_info: Path,
    connection_type: str = "sqlite:///",
    autocommit: bool = False,
    pool_size: int = 5,
) -> tuple[scoped_session, Engine]:
    kwargs = {}
    if connection_type == "mysql+mysqldb://":
        kwargs["pool_size"] = pool_size
        kwargs["pool_pre_ping"] = True
        kwargs["max_overflow"] = -1
        kwargs["isolation_level"] = "READ COMMITTED"

    engine = sqlalchemy.create_engine(
        f"{connection_type}{connection_info}?charset=utf8mb4", **kwargs
    )
    session_factory = sessionmaker(bind=engine, autocommit=autocommit)
    Session = scoped_session(session_factory)
    return Session, engine


def run_revisions(alembic_directory: str, database_path: str = ""):
    while True:
        try:
            ini_path = os.path.join(alembic_directory, "alembic.ini")
            script_location = os.path.join(alembic_directory, "alembic")
            full_database_path = f"sqlite:///{database_path}"
            alembic_cfg = Config(ini_path)
            alembic_cfg.set_main_option("script_location", script_location)
            alembic_cfg.set_main_option("sqlalchemy.url", full_database_path)
            command.upgrade(alembic_cfg, "head")
            command.revision(alembic_cfg, autogenerate=True, message="content")
            break
        except Exception as e:
            print(e)
            print


def run_migrations(alembic_directory: str, database_path: str) -> None:
    while True:
        try:
            ini_path = os.path.join(alembic_directory, "alembic.ini")
            script_location = os.path.join(alembic_directory, "alembic")
            full_database_path = f"sqlite:///{database_path}"
            alembic_cfg = Config(ini_path)
            alembic_cfg.set_main_option("script_location", script_location)
            alembic_cfg.set_main_option("sqlalchemy.url", full_database_path)
            command.upgrade(alembic_cfg, "head")
            break
        except Exception as e:
            print(e)
            print


class database_collection(object):
    def __init__(self) -> None:
        self.user_database = user_database

    def database_picker(self, database_name: Literal["user_data"]):
        if database_name == "user_data":
            database = self.user_database
        else:
            database = None
            print("Can't find database")
            input()
        return database


def create_auth_array(item):
    auth_array = item.__dict__
    auth_array["support_2fa"] = False
    return auth_array


def get_or_create(session: Session, model, defaults=None, fbkwargs: dict = {}):
    fbkwargs2 = fbkwargs.copy()
    instance = session.query(model).filter_by(**fbkwargs2).one_or_none()
    if instance:
        return instance, True
    else:
        fbkwargs2 |= defaults or {}
        instance = model(**fbkwargs2)
        try:
            session.add(instance)
            session.commit()
        except IntegrityError:
            session.rollback()
            instance = session.query(model).filter_by(**fbkwargs2).one()
            return instance, False
        else:
            return instance, True


def get_count(q):
    count_q = q.statement.with_only_columns([func.count()]).order_by(None)
    count = q.session.execute(count_q).scalar()
    return count
