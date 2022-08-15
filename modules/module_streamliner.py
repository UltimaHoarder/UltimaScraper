from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any, Optional

import apis.fansly.classes as fansly_classes
import apis.onlyfans.classes as onlyfans_classes
import apis.starsavn.classes as starsavn_classes
from apis.starsavn.classes.user_model import create_user
from classes.make_settings import SiteSettings
from classes.prepare_metadata import (
    prepare_reformat,
    process_legacy_metadata,
    process_metadata,
)
from helpers import db_helper, main_helper
from sqlalchemy.exc import OperationalError
from tqdm.asyncio import tqdm

auth_types = (
    onlyfans_classes.auth_model.create_auth
    | fansly_classes.auth_model.create_auth
    | starsavn_classes.auth_model.create_auth
)
user_types = (
    onlyfans_classes.user_model.create_user
    | fansly_classes.user_model.create_user
    | starsavn_classes.user_model.create_user
)
error_types = (
    onlyfans_classes.extras.ErrorDetails
    | fansly_classes.extras.ErrorDetails
    | starsavn_classes.extras.ErrorDetails
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.fansly import FanslyDataScraper
    from modules.onlyfans import OnlyFansDataScraper
    from modules.starsavn import StarsAVNDataScraper

    datascraper_types = OnlyFansDataScraper | FanslyDataScraper | StarsAVNDataScraper


class StreamlinedDatascraper:
    def __init__(self, datascraper: datascraper_types) -> None:
        self.datascraper = datascraper
        self.profile_options: Optional[main_helper.OptionsFormat] = None
        self.subscription_options: Optional[main_helper.OptionsFormat] = None
        self.content_options: Optional[main_helper.OptionsFormat] = None
        self.media_types = self.datascraper.api.ContentTypes()
        self.media_options: Optional[main_helper.OptionsFormat] = None
        self.media_types = self.datascraper.api.Locations()

    async def start_datascraper(
        self, authed: auth_types, identifier: int | str, whitelist: list[str] = []
    ):
        api = authed.api
        site_settings = api.get_site_settings()
        if not site_settings:
            return
        subscription = await authed.get_subscription(identifier=identifier)
        if not subscription:
            return [False, subscription]
        print("Scrape Processing")
        username = subscription.username
        print(f"Name: {username}")
        subscription_directory_manager = subscription.directory_manager
        if subscription_directory_manager:
            await main_helper.format_directories(
                subscription_directory_manager, subscription
            )
            await main_helper.fix_sqlite(api, subscription_directory_manager)
            content_types, _media_types = await self.scrape_choice(
                authed, site_settings
            )
            await self.profile_scraper(subscription)
            for content_type, _value in content_types:
                if whitelist and content_type not in whitelist:
                    continue
                print(f"Type: {content_type}")
                await self.prepare_scraper(subscription, content_type)
            print("Scrape Completed" + "\n")
            return True, subscription

    # Allows the user to choose which api they want to scrape
    async def scrape_choice(self, authed: auth_types, site_settings: SiteSettings):
        content_types = authed.api.ContentTypes()
        content_types_keys = await content_types.get_keys()
        content_options = main_helper.OptionsFormat(
            content_types_keys, "contents", site_settings.auto_api_choice
        )
        for type_ in content_types_keys:
            if type_ not in content_options.final_choices:
                delattr(content_types, type_)
        self.content_options = content_options
        self.content_types = content_types
        media_types = authed.api.Locations()
        media_types_keys = await media_types.get_keys()
        media_options = main_helper.OptionsFormat(
            media_types_keys, "medias", site_settings.auto_media_choice
        )
        for type_ in media_types_keys:
            if type_ not in media_options.final_choices:
                delattr(media_types, type_)
        self.media_options = media_options
        self.media_types = media_types
        return content_types, media_types

    # Downloads the model's avatar and header
    async def profile_scraper(self, subscription: user_types):
        authed = subscription.get_authed()
        site_settings = authed.api.get_site_settings()
        if not (subscription.directory_manager and site_settings):
            return
        subscription_directory_manager = subscription.directory_manager
        subscription_username = subscription.username
        site_name = authed.api.site_name
        authed = subscription.get_authed()
        override_media_types: list[list[Any]] = []
        avatar = subscription.avatar
        header = subscription.header
        override_media_types.extend([["Avatars", avatar], ["Headers", header]])
        session = await authed.session_manager.create_client_session()
        progress_bar = None
        p_r = prepare_reformat()
        p_r.site_name = site_name
        p_r.model_username = subscription_username
        p_r.api_type = "Profile"
        p_r.text_length = site_settings.text_length
        p_r.directory = subscription_directory_manager.root_download_directory
        directory = await p_r.remove_non_unique(
            subscription_directory_manager, "file_directory_format"
        )
        if not isinstance(directory, Path):
            return
        directory = directory.joinpath(p_r.api_type)
        for override_media_type in override_media_types:
            media_type = override_media_type[0]
            media_link = override_media_type[1]
            if not media_link:
                continue
            directory2 = directory.joinpath(media_type)
            directory2.mkdir(parents=True, exist_ok=True)
            download_path = directory2.joinpath(f"{media_link.split('/')[-2]}.jpg")
            if download_path.is_file():
                continue
            response = await authed.session_manager.json_request(
                media_link, method="HEAD"
            )
            if not response:
                continue
            if not progress_bar:
                progress_bar = main_helper.download_session()
                progress_bar.start(unit="B", unit_scale=True, miniters=1)
            progress_bar.update_total_size(response.content_length)
            response = await authed.session_manager.json_request(
                media_link,
                session,
                stream=True,
                json_format=False,
            )
            await main_helper.write_data(response, download_path, progress_bar)
        await session.close()
        if progress_bar:
            progress_bar.close()  # type: ignore

    # Move this to StreamlinedDatascraper
    async def paid_content_scraper(self, authed: auth_types):
        site_settings = authed.api.get_site_settings()
        if not site_settings or not authed.active:
            return
        paid_contents = await authed.get_paid_content()
        if isinstance(paid_contents, error_types):
            return
        for paid_content in paid_contents:
            author = await paid_content.get_author()
            if not author:
                continue
            if self.subscription_options and self.subscription_options.scrape_all():
                subscription = await authed.get_subscription(identifier=author.id)
                if not subscription:
                    if not author.username and author.name == "Deleted user":
                        author.username = "__deleted_users__"
                    subscription = author
                    authed.subscriptions.append(subscription)
                else:
                    author = subscription
            author.create_directory_manager()
            if paid_content.responseType:
                api_type = paid_content.responseType.capitalize() + "s"
                if api_type == "Posts" and paid_content.isArchived:
                    api_media = getattr(author.temp_scraped.Archived, api_type)
                else:
                    api_media = getattr(author.temp_scraped, api_type)
                api_media.append(paid_content)
        count = 0
        max_count = len(authed.subscriptions)
        for subscription in authed.subscriptions:
            string = f"Scraping - {subscription.username} | {count+1} / {max_count}"
            print(string)
            subscription_directory_manager = subscription.directory_manager
            count += 1
            await main_helper.format_directories(
                subscription_directory_manager,
                subscription,
            )
            for content_type, master_set in subscription.temp_scraped:
                if content_type == "Archived":
                    for content_type_2, master_set_2 in master_set:
                        await self.process_scraped_content(
                            master_set_2, content_type_2, subscription
                        )
                else:
                    await self.process_scraped_content(
                        master_set, content_type, subscription
                    )

    # Prepares the API links to be scraped

    async def prepare_scraper(self, subscription: user_types, content_type: str):
        authed = subscription.get_authed()
        subscription_directory_manager = subscription.directory_manager
        formatted_metadata_directory = (
            subscription_directory_manager.user.metadata_directory
        )
        master_set: list[Any] = []
        match content_type:
            case "Stories":
                master_set.extend(await self.datascraper.get_all_stories(subscription))
            case "Posts":
                master_set = await subscription.get_posts()
                print(f"Type: Archived Posts")
                if type(authed) == fansly_classes.auth_model.create_auth:
                    collections = await subscription.get_collections()
                    for collection in collections:
                        master_set.append(
                            await subscription.get_collection_content(collection)
                        )
                else:
                    master_set += await subscription.get_archived_posts()
            case "Messages":
                unrefined_set = await subscription.get_messages()
                mass_messages = getattr(authed, "mass_messages")
                if subscription.is_me() and mass_messages:
                    mass_messages = getattr(authed, "mass_messages")
                    unrefined_set2 = await self.datascraper.process_mass_messages(
                        authed,
                        mass_messages,
                    )
                    unrefined_set += unrefined_set2
                master_set = unrefined_set
            case "Products":
                if isinstance(subscription, create_user):
                    any = await subscription.get_medias()
                    if any:
                        master_set = any
        await self.process_scraped_content(master_set, content_type, subscription)

    async def process_scraped_content(
        self,
        master_set: list[dict[str, Any]],
        content_type: str,
        subscription: user_types,
    ):
        if not master_set:
            return False
        authed = subscription.get_authed()
        subscription_directory_manager = subscription.directory_manager
        formatted_metadata_directory = (
            subscription_directory_manager.user.metadata_directory
        )
        unrefined_set = []
        pool = authed.pool
        print(f"Processing Scraped {content_type}")
        tasks = pool.starmap(
            self.datascraper.media_scraper,
            product(
                master_set,
                [subscription],
                [subscription_directory_manager.root_download_directory],
                [content_type],
            ),
        )
        settings = {"colour": "MAGENTA"}
        unrefined_set = await tqdm.gather(*tasks, **settings)
        pass
        unrefined_set = [x for x in unrefined_set]
        new_metadata = main_helper.format_media_set(unrefined_set)
        metadata_path = formatted_metadata_directory.joinpath("user_data.db")
        legacy_metadata_path = formatted_metadata_directory.joinpath(
            content_type + ".db"
        )
        if new_metadata:
            new_metadata = new_metadata["content"]
            print("Processing metadata.")
            old_metadata, delete_metadatas = await process_legacy_metadata(
                subscription,
                content_type,
                metadata_path,
                subscription_directory_manager,
            )
            new_metadata.extend(old_metadata)
            subscription.set_scraped(content_type, new_metadata)
            await process_metadata(
                metadata_path,
                legacy_metadata_path,
                new_metadata,
                content_type,
                subscription,
                delete_metadatas,
            )
        else:
            print("No " + content_type + " Found.")
        return True

    # Downloads scraped content

    async def prepare_downloads(self, subscription: user_types):
        global_settings = subscription.get_api().get_global_settings()
        site_settings = subscription.get_api().get_site_settings()
        if not (global_settings and site_settings):
            return
        subscription_directory_manager = subscription.directory_manager
        directory = subscription_directory_manager.root_download_directory
        print
        for api_type, metadata_path in subscription.scraped.__dict__.items():
            metadata_path = (
                subscription_directory_manager.user.metadata_directory.joinpath(
                    "user_data.db"
                )
            )
            database_session, _engine = await db_helper.import_database(metadata_path)
            db_collection = db_helper.database_collection()
            database = db_collection.database_picker("user_data")
            if database:
                media_table = database.media_table
                overwrite_files = site_settings.overwrite_files
                if overwrite_files:
                    download_list: Any = (
                        database_session.query(media_table)
                        .filter(media_table.api_type == api_type)
                        .all()
                    )
                    media_set_count = len(download_list)
                else:
                    download_list: Any = (
                        database_session.query(media_table)
                        .filter(media_table.downloaded == False)
                        .filter(media_table.api_type == api_type)
                    )
                    media_set_count = db_helper.get_count(download_list)
                location = ""
                string = "Download Processing\n"
                string += f"Name: {subscription.username} | Type: {api_type} | Count: {media_set_count}{location} | Directory: {directory}\n"
                if media_set_count:
                    print(string)
                    await main_helper.async_downloads(
                        download_list, subscription, global_settings
                    )
                while True:
                    try:
                        database_session.commit()
                        break
                    except OperationalError:
                        database_session.rollback()
                database_session.close()

    async def manage_subscriptions(
        self,
        authed: auth_types,
        identifiers: list[int | str] = [],
        refresh: bool = True,
    ):
        temp_subscriptions: list[user_types] = []
        results = await self.datascraper.get_all_subscriptions(
            authed, identifiers, refresh
        )
        site_settings = authed.api.get_site_settings()
        if not site_settings:
            return temp_subscriptions
        blacklists = site_settings.blacklists
        ignore_type = site_settings.ignore_type
        if blacklists:
            remote_blacklists = await authed.get_lists()
            if remote_blacklists:
                for remote_blacklist in remote_blacklists:
                    for blacklist in blacklists:
                        if remote_blacklist["name"] == blacklist:
                            list_users = remote_blacklist["users"]
                            if remote_blacklist["usersCount"] > 2:
                                list_id = remote_blacklist["id"]
                                list_users = await authed.get_lists_users(list_id)
                            if list_users:
                                users = list_users
                                bl_ids = [x["username"] for x in users]
                                results2 = results.copy()
                                for result in results2:
                                    identifier = result.username
                                    if identifier in bl_ids:
                                        print(f"Blacklisted: {identifier}")
                                        results.remove(result)
            results2 = results.copy()
            for result in results2:
                identifier = result.username
                if identifier in blacklists:
                    print(f"Blacklisted: {identifier}")
                    results.remove(result)
        results.sort(key=lambda x: x.is_me(), reverse=True)
        for result in results:
            result.create_directory_manager()
            subscribePrice = result.subscribePrice
            if ignore_type in ["paid"]:
                if subscribePrice > 0:
                    continue
            if ignore_type in ["free"]:
                if subscribePrice == 0:
                    continue
            temp_subscriptions.append(result)
        authed.subscriptions = temp_subscriptions
        return authed.subscriptions
