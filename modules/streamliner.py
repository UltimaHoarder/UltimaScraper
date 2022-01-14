from __future__ import annotations

from itertools import product
from typing import Any

from sqlalchemy.exc import OperationalError

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

    async def start_datascraper(self, authed: auth_types, identifier: int | str):
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
            for key, _value in content_types:
                print(f"Type: {key}")
                await self.prepare_scraper(subscription, key)
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
        media_types = authed.api.Locations()
        media_types_keys = await media_types.get_keys()
        media_options = main_helper.OptionsFormat(
            media_types_keys, "medias", site_settings.auto_media_choice
        )
        for type_ in media_types_keys:
            if type_ not in media_options.final_choices:
                delattr(media_types, type_)
        return content_types, media_types

    # Downloads the model's avatar and header
    async def profile_scraper(self, subscription: user_types):
        authed = subscription.get_authed()
        site_settings = authed.api.get_site_settings()
        if not (subscription.directory_manager and site_settings):
            return
        subscription_directory_manager = subscription.directory_manager
        authed_username = authed.username
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
        p_r.profile_username = authed_username
        p_r.model_username = subscription_username
        p_r.date_format = site_settings.date_format
        p_r.text_length = site_settings.text_length
        p_r.api_type = "Profile"
        p_r.directory = subscription_directory_manager.root_download_directory

        file_directory_format = site_settings.file_directory_format.replace(
            "{value}", ""
        )
        directory = await p_r.reformat_2(file_directory_format)
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
        if not site_settings:
            return
        paid_contents = await authed.get_paid_content()
        if not authed.active or isinstance(paid_contents, error_types):
            return
        authed.subscriptions = authed.subscriptions
        for paid_content in paid_contents:
            author = None
            author = await paid_content.get_author()
            if not author:
                continue
            subscription = await authed.get_subscription(identifier=author.id)
            if not subscription:
                subscription = author
                authed.subscriptions.append(subscription)
            path_formats: dict[str, Any] = {}
            path_formats[
                "metadata_directory_format"
            ] = site_settings.metadata_directory_format
            path_formats["file_directory_format"] = site_settings.file_directory_format
            path_formats["filename_format"] = site_settings.filename_format
            subscription.create_directory_manager(path_formats=path_formats)
            if paid_content.responseType:
                api_type = paid_content.responseType.capitalize() + "s"
                api_media = getattr(subscription.temp_scraped, api_type)
                api_media.append(paid_content)
        count = 0
        max_count = len(authed.subscriptions)
        for subscription in authed.subscriptions:
            string = f"Scraping - {subscription.username} | {count+1} / {max_count}"
            print(string)
            subscription_directory_manager = subscription.directory_manager
            count += 1
            for api_type, paid_contents in subscription.temp_scraped:
                if api_type == "Archived":
                    continue
                if not paid_contents:
                    continue
                await main_helper.format_directories(
                    subscription_directory_manager,
                    subscription,
                )
                metadata_path = (
                    subscription_directory_manager.user.metadata_directory.joinpath(
                        subscription_directory_manager.user.metadata_directory,
                        "user_data.db",
                    )
                )
                pool = subscription.get_session_manager().pool
                tasks = pool.starmap(
                    self.datascraper.media_scraper,
                    product(
                        paid_contents,
                        [subscription],
                        [subscription_directory_manager.root_download_directory],
                        [api_type],
                    ),
                )
                settings = {"colour": "MAGENTA"}
                unrefined_set = await tqdm.gather(*tasks, **settings)
                new_metadata = main_helper.format_media_set(unrefined_set)
                new_metadata = new_metadata["content"]
                legacy_metadata_path = (
                    subscription_directory_manager.user.find_legacy_directory(
                        "metadata", api_type
                    ).with_suffix(".db")
                )
                if new_metadata:
                    old_metadata, delete_metadatas = await process_legacy_metadata(
                        subscription,
                        api_type,
                        metadata_path,
                        subscription_directory_manager
                    )
                    new_metadata.extend(old_metadata)
                    subscription.set_scraped(api_type, new_metadata)
                    await process_metadata(
                        metadata_path,
                        legacy_metadata_path,
                        new_metadata,
                        api_type,
                        subscription,
                        delete_metadatas,
                    )

    # Prepares the API links to be scraped

    async def prepare_scraper(self, subscription: user_types, content_type: str):
        authed = subscription.get_authed()
        subscription_directory_manager = subscription.directory_manager
        if not subscription_directory_manager:
            return
        formatted_metadata_directory = (
            subscription_directory_manager.user.metadata_directory
        )
        master_set: list[Any] = []
        pool = authed.pool
        match content_type:
            case "Stories":
                master_set.extend(await self.datascraper.get_all_stories(subscription))
            case "Posts":
                master_set = await subscription.get_posts()
                print(f"Type: Archived Posts")
                master_set += await subscription.get_archived_posts()
            case "Messages":
                unrefined_set = await subscription.get_messages()
                mass_messages = getattr(authed, "mass_messages")
                if subscription.is_me() and mass_messages:
                    mass_messages = getattr(authed, "mass_messages")
                    unrefined_set2 = await self.datascraper.process_mass_messages(
                        authed,
                        subscription,
                        formatted_metadata_directory,
                        mass_messages,
                    )
                    unrefined_set += unrefined_set2
                master_set = unrefined_set
            case "Products":
                if isinstance(subscription, create_user):
                    any = await subscription.get_medias()
                    if any:
                        master_set = any

        master_set2 = master_set
        unrefined_set = []
        if master_set2:
            print(f"Processing Scraped {content_type}")
            tasks = pool.starmap(
                self.datascraper.media_scraper,
                product(
                    master_set2,
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
            new_metadata = new_metadata + old_metadata
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
