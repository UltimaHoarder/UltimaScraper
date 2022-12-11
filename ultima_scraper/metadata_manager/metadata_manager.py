from pathlib import Path
from typing import Any
from sqlalchemy import inspect
from ultima_scraper_api.database.db_manager import DBManager,DBCollection
import ultima_scraper_api
api_types = ultima_scraper_api.api_types
user_types = ultima_scraper_api.user_types
class MetadataManager():
    def __init__(self,subscription:user_types,db_manager:DBManager|None=None) -> None:
        self.subscription = subscription
        self.db_manager = db_manager
        self.metadatas = self.find_metadatas()

    def find_metadatas(self):
        found_metadatas:list[Path] = []
        for file_ in self.subscription.file_manager.files:
            if file_.suffix in [".db",".json"]:
                found_metadatas.append(file_)
        return found_metadatas

    async def process_metadata(
        self,
        legacy_metadata_path: Path,
        new_metadata_object: list[dict[str, Any]],
        api_type: str,
        subscription: user_types,
        delete_metadatas: list[Path],
    ):
        if not self.db_manager:
            raise Exception("DBManager has not been assigned")
        from ultima_scraper_renamer import renamer
        api = subscription.get_api()
        site_settings = api.get_site_settings()
        config = api.config
        if not (config and site_settings):
            return
        settings = config.settings
        # We could put this in proccess_legacy_metadata
        legacy_db_manager = DBManager(legacy_metadata_path,api_type,legacy=True)
        final_result, delete_metadatas = await legacy_db_manager.legacy_sqlite_updater(
            legacy_metadata_path, api_type, subscription, delete_metadatas
        )
        new_metadata_object.extend(final_result)
        result = await self.db_manager.export_sqlite(self.db_manager.database_path, api_type, new_metadata_object)
        if not result:
            return
        Session, api_type, _folder = result
        if settings.helpers.renamer:
            print("Renaming files.")
            new_metadata_object = await renamer.start(
                subscription, api_type, Session, site_settings
            )
        for legacy_metadata in delete_metadatas:
            if site_settings.delete_legacy_metadata:
                legacy_metadata.unlink()
            else:
                if legacy_metadata.exists():
                    new_filepath = Path(
                        legacy_metadata.parent, "__legacy_metadata__", legacy_metadata.name
                    )
                    new_filepath.parent.mkdir(exist_ok=True)
                    legacy_metadata.rename(new_filepath)
    
    async def fix_archived_db(
        self,
    ):
        api = self.subscription.get_api()
        directory_manager = self.subscription.directory_manager
        for final_metadata in directory_manager.user.legacy_metadata_directories:
            archived_database_path = final_metadata.joinpath("Archived.db")
            if archived_database_path.exists():
                archived_db_manager = DBManager(archived_database_path,"",legacy=True)
                archived_database_session,archived_engine = await archived_db_manager.import_database()
                for api_type, _value in api.ContentTypes():
                    database_path = final_metadata.joinpath( f"{api_type}.db")
                    legacy_db_manager = DBManager(database_path,api_type,legacy=True)
                    database_name = api_type.lower()
                    result:bool = inspect(archived_engine).has_table(database_name)
                    if result:
                        archived_db_manager.alembic_directory=archived_db_manager.alembic_directory.parent.with_name(database_name).joinpath("alembic")
                        await archived_db_manager.run_migrations(
                        )
                        await legacy_db_manager.run_migrations()
                        db_manager = DBManager(database_path,api_type)

                        modern_database_session, _engine = await db_manager.import_database()
                        db_collection = DBCollection()
                        database = db_collection.database_picker("user_data")
                        if not database:
                            return
                        table_name = database.table_picker(api_type, True)
                        if not table_name:
                            return
                        archived_result = modern_database_session.query(table_name).all()
                        for item in archived_result:
                            result2 = (
                                modern_database_session.query(table_name)
                                .filter(table_name.post_id == item.post_id)
                                .first()
                            )
                            if not result2:
                                item2 = item.__dict__
                                item2.pop("id")
                                item2.pop("_sa_instance_state")
                                item = table_name(**item2)
                                item.archived = True
                                modern_database_session.add(item)
                        modern_database_session.commit()
                        modern_database_session.close()
                archived_database_session.commit()
                archived_database_session.close()
                new_filepath = Path(
                    archived_database_path.parent,
                    "__legacy_metadata__",
                    archived_database_path.name,
                )
                new_filepath.parent.mkdir(exist_ok=True)
                archived_database_path.rename(new_filepath)