from __future__ import annotations

import asyncio
import copy
from itertools import product
from pathlib import Path
from typing import Any, Optional

import ultima_scraper_api
import ultima_scraper_api.apis.fansly.classes as fansly_classes
import ultima_scraper_api.classes.make_settings as make_settings
from sqlalchemy.exc import OperationalError
from tqdm.asyncio import tqdm
from ultima_scraper_api.apis.dashboard_controller_api import DashboardControllerAPI
from ultima_scraper_api.apis.fansly import fansly as Fansly
from ultima_scraper_api.apis.onlyfans import onlyfans as OnlyFans
from ultima_scraper_api.classes.make_settings import SiteSettings
from ultima_scraper_api.database.db_manager import DBCollection, DBManager
from ultima_scraper_api.helpers import db_helper, main_helper
from ultima_scraper_api.managers.job_manager.jobs.custom_job import CustomJob
from ultima_scraper_api.managers.metadata_manager.metadata_manager import (
    MetadataManager,
)
from ultima_scraper_renamer import renamer

auth_types = ultima_scraper_api.auth_types
user_types = ultima_scraper_api.user_types
message_types = ultima_scraper_api.message_types
error_types = ultima_scraper_api.error_types

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ultima_scraper.modules.fansly import FanslyDataScraper
    from ultima_scraper.modules.onlyfans import OnlyFansDataScraper

    datascraper_types = OnlyFansDataScraper | FanslyDataScraper


class download_session(tqdm):
    def start(
        self,
        unit: str = "B",
        unit_scale: bool = True,
        miniters: int = 1,
        tsize: int = 0,
    ):
        self.unit = unit
        self.unit_scale = unit_scale
        self.miniters = miniters
        self.total = 0
        self.colour = "Green"
        if tsize:
            tsize = int(tsize)
            self.total += tsize

    def update_total_size(self, tsize: Optional[int]):
        if tsize:
            tsize = int(tsize)
            self.total += tsize


class StreamlinedDatascraper:
    def __init__(
        self,
        datascraper: datascraper_types,
        dashboard_controller_api: Optional[DashboardControllerAPI] = None,
    ) -> None:
        self.datascraper = datascraper
        self.profile_options: Optional[main_helper.OptionsFormat] = None
        self.subscription_options: Optional[main_helper.OptionsFormat] = None
        self.content_options: Optional[main_helper.OptionsFormat] = None
        self.content_types = self.datascraper.api.ContentTypes()
        self.media_options: Optional[main_helper.OptionsFormat] = None
        self.media_types = self.datascraper.api.Locations()
        self.dashboard_controller_api = dashboard_controller_api

    async def start_datascraper(self, job_user_list: list[user_types]):
        api = self.datascraper.api
        site_settings = api.get_site_settings()
        available_jobs = site_settings.jobs.scrape
        if not available_jobs.subscriptions:
            for authed in api.auths:
                authed.subscriptions = []
        if available_jobs.messages:
            chat_users = await self.get_chat_users()
            [user.scrape_whitelist.append("Messages") for user in chat_users]
            job_user_list.extend(chat_users)

        if available_jobs.paid_contents:
            for authed in self.datascraper.api.auths:
                paid_contents = await authed.get_paid_content()
                if not isinstance(paid_contents, error_types):
                    for paid_content in paid_contents:
                        author = await paid_content.get_author()
                        if author:
                            subscription = await authed.get_subscription(
                                identifier=author.id,
                                custom_list=job_user_list,
                            )
                            if not subscription:
                                subscription = author
                                job_user_list.append(subscription)
                            subscription.job_whitelist.append("PaidContents")
                            subscription.scrape_whitelist.clear()
        # job_user_list = [
        #     job_user
        #     for job_user in job_user_list
        #     if job_user.username in self.subscription_options.auto_choice
        # ]
        job_user_list = [
            job_user
            for job_user in job_user_list
            if job_user.username
            not in [blacklist for authed in api.auths for blacklist in authed.blacklist]
        ]

        await self.assign_jobs(job_user_list)
        await self.datascraper.api.job_manager.queue.join()

    async def assign_jobs(self, subscription_list: list[user_types]):
        datascraper = self.datascraper
        JBM = datascraper.api.job_manager
        site_settings = datascraper.api.get_site_settings()
        content_types = datascraper.api.ContentTypes()
        content_types_keys = await content_types.get_keys()
        media_types = datascraper.api.Locations()
        media_types_keys = await media_types.get_keys()

        for subscription in subscription_list:
            await subscription.create_directory_manager(user=True)
            await main_helper.format_directories(subscription)
            metadata_manager = MetadataManager(subscription)
            await metadata_manager.fix_archived_db()

            local_jobs: list[CustomJob] = []
            auto_api_choice = (
                site_settings.auto_api_choice
                if not subscription.scrape_whitelist
                else subscription.scrape_whitelist
            )
            content_options = await main_helper.OptionsFormat(
                content_types_keys,
                "contents",
                auto_api_choice,
                self.datascraper.api.dashboard_controller_api,
            ).formatter()
            jobs = JBM.create_jobs(
                "Scrape",
                content_options.final_choices,
                self.prepare_scraper,
                [subscription],
            )
            local_jobs.extend(jobs)
            jobs = JBM.create_jobs(
                "Download",
                content_options.final_choices,
                self.prepare_downloads,
                [subscription],
            )
            local_jobs.extend(jobs)

            subscription.jobs.extend(local_jobs)
            media_options = await main_helper.OptionsFormat(
                media_types_keys,
                "medias",
                site_settings.auto_media_choice,
                self.datascraper.api.dashboard_controller_api,
            ).formatter()
            JBM.add_media_type_to_jobs(media_options.final_choices)

            for local_job in local_jobs:
                JBM.queue.put_nowait(local_job)
            await asyncio.sleep(1)
        pass

    # Allows the user to choose which api they want to scrape
    async def scrape_choice(self, authed: auth_types, site_settings: SiteSettings):
        content_types = authed.api.ContentTypes()
        content_types_keys = await content_types.get_keys()
        content_options = await main_helper.OptionsFormat(
            content_types_keys,
            "contents",
            site_settings.auto_api_choice,
            self.datascraper.api.dashboard_controller_api,
        ).formatter()
        for type_ in content_types_keys:
            if type_ not in content_options.final_choices:
                delattr(content_types, type_)
        self.content_options = content_options
        self.content_types = content_types
        media_types = authed.api.Locations()
        media_types_keys = await media_types.get_keys()
        media_options = await main_helper.OptionsFormat(
            media_types_keys,
            "medias",
            site_settings.auto_media_choice,
            self.datascraper.api.dashboard_controller_api,
        ).formatter()
        for type_ in media_types_keys:
            if type_ not in media_options.final_choices:
                delattr(media_types, type_)
        self.media_options = media_options
        self.media_types = media_types
        return content_types, media_types

    # Downloads the model's avatar and header
    async def profile_scraper(self, subscription: user_types):
        from ultima_scraper_api.classes.prepare_metadata import prepare_reformat

        # download_job = subscription.get_job("download")
        # profile_task = download_job.create_task("profile")
        # This is all terrible, I need to redo this
        authed = subscription.get_authed()
        site_settings = authed.api.get_site_settings()
        if not (subscription.directory_manager and site_settings):
            return
        subscription_directory_manager = subscription.directory_manager
        subscription_username = subscription.username
        site_name = authed.api.site_name
        authed = subscription.get_authed()
        override_media_types: list[list[Any]] = []
        avatar = await subscription.get_avatar()
        header = await subscription.get_header()
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
                progress_bar = download_session()
                progress_bar.start(unit="B", unit_scale=True, miniters=1)
                progress_bar.update_total_size(response.content_length)
            response = await authed.session_manager.json_request(
                media_link,
                session,
                stream=True,
                json_format=False,
            )
            await main_helper.write_data(response, download_path)
        await session.close()
        if progress_bar:
            progress_bar.close()  # type: ignore

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
            # await author.create_directory_manager(user=False)
            if paid_content.responseType:
                api_type = paid_content.responseType.capitalize() + "s"
                # Needs an Isinstance of Posts to avoid create_message conflict
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
            count += 1
            await main_helper.format_directories(
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

    async def prepare_scraper(
        self, subscription: user_types, content_type: str, master_set: list[Any] = []
    ):
        authed = subscription.get_authed()
        current_job = subscription.get_current_job()
        temp_master_set: list[Any] = copy.copy(master_set)
        if not temp_master_set:
            match content_type:
                case "Stories":
                    temp_master_set.extend(
                        await self.datascraper.get_all_stories(subscription)
                    )
                case "Posts":
                    temp_master_set = await subscription.get_posts()
                    # Archived Posts
                    if isinstance(subscription, fansly_classes.user_model.create_user):
                        collections = await subscription.get_collections()
                        for collection in collections:
                            temp_master_set.append(
                                await subscription.get_collection_content(collection)
                            )
                        pass
                    else:
                        temp_master_set += await subscription.get_archived_posts()
                case "Messages":
                    unrefined_set: list[
                        message_types | Any
                    ] = await subscription.get_messages()
                    mass_messages = getattr(authed, "mass_messages")
                    if subscription.is_me() and mass_messages:
                        mass_messages = getattr(authed, "mass_messages")
                        # Need access to a creator's account to fix this
                        unrefined_set2 = await self.datascraper.process_mass_messages(
                            authed,
                            mass_messages,
                        )
                        unrefined_set += unrefined_set2
                    temp_master_set = unrefined_set
                case "Archived":
                    pass
                case "Chats":
                    pass
                case "Highlights":
                    pass
                case "MassMessages":
                    pass
                case _:
                    raise Exception(f"{content_type} is an invalid choice")
        await self.process_scraped_content(temp_master_set, content_type, subscription)
        current_job.done = True

    async def process_scraped_content(
        self,
        master_set: list[dict[str, Any]],
        api_type: str,
        subscription: user_types,
    ):
        if not master_set:
            return False

        from ultima_scraper_api.classes.prepare_metadata import process_legacy_metadata

        authed = subscription.get_authed()
        subscription_directory_manager = subscription.directory_manager
        formatted_metadata_directory = (
            subscription_directory_manager.user.metadata_directory
        )
        unrefined_set = []
        pool = authed.pool
        print(f"Processing Scraped {api_type}")
        tasks = pool.starmap(
            self.datascraper.media_scraper,
            product(
                master_set,
                [subscription],
                [subscription_directory_manager.root_download_directory],
                [api_type],
            ),
        )
        settings = {"colour": "MAGENTA"}
        unrefined_set: list[dict[str, Any]] = await tqdm.gather(*tasks, **settings)
        new_metadata: dict[str, Any] = await main_helper.format_media_set(unrefined_set)
        metadata_path = formatted_metadata_directory.joinpath("user_data.db")
        legacy_metadata_path = formatted_metadata_directory.joinpath(api_type + ".db")
        if new_metadata:
            new_metadata_content: list[dict[str, Any]] = new_metadata["content"]
            print("Processing metadata.")
            old_metadata, delete_metadatas = await process_legacy_metadata(
                subscription,
                api_type,
                metadata_path,
                subscription_directory_manager,
            )
            new_metadata_content.extend(old_metadata)
            subscription.set_scraped(api_type, new_metadata_content)
            db_manager = DBManager(metadata_path, api_type)
            metadata_manager = MetadataManager(subscription, db_manager)
            result = await metadata_manager.process_metadata(
                legacy_metadata_path,
                new_metadata_content,
                api_type,
                subscription,
                delete_metadatas,
            )
            if result:
                Session, api_type, _folder = result
                if authed.api.config.settings.helpers.renamer:
                    print("Renaming files.")
                    _new_metadata_object = await renamer.start(
                        subscription,
                        api_type,
                        Session,
                    )
                metadata_manager.delete_metadatas()
                pass
        else:
            print(f"No {api_type} found.")
        return True

    # Downloads scraped content

    async def prepare_downloads(self, subscription: user_types, api_type: str):
        global_settings = subscription.get_api().get_global_settings()
        site_settings = subscription.get_api().get_site_settings()
        if not (global_settings and site_settings):
            return
        subscription_directory_manager = subscription.directory_manager
        directory = subscription_directory_manager.root_download_directory
        current_job = subscription.get_current_job()

        metadata_path = subscription_directory_manager.user.metadata_directory.joinpath(
            "user_data.db"
        )
        db_manager = DBManager(metadata_path, api_type)
        if db_manager.database_path.exists():
            database_session, _engine = await db_manager.import_database()
            db_collection = DBCollection()
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
            current_job.done = True

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
        ignore_type = site_settings.ignore_type
        results.sort(key=lambda x: x.is_me(), reverse=True)
        for result in results:
            # await result.create_directory_manager(user=True)
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

    async def account_setup(
        self,
        auth: auth_types,
        datascraper: datascraper_types,
        site_settings: make_settings.SiteSettings,
        identifiers: list[int | str] | list[str] = [],
    ) -> tuple[bool, list[user_types]]:
        status = False
        subscriptions: list[user_types] = []
        authed = await auth.login()
        if authed.active and authed.directory_manager and site_settings:
            # metadata_filepath = (
            #     authed.directory_manager.profile.metadata_directory.joinpath(
            #         "Mass Messages.json"
            #     )
            # )
            # if authed.isPerformer:
            #     imported = main_helper.import_json(metadata_filepath)
            #     if "auth" in imported:
            #         imported = imported["auth"]
            #     mass_messages = await authed.get_mass_messages(resume=imported)
            #     if mass_messages:
            #         main_helper.export_json(mass_messages, metadata_filepath)
            authed.blacklist = await authed.get_blacklist(
                authed.api.get_site_settings().blacklists
            )
            if identifiers or site_settings.jobs.scrape.subscriptions:
                subscriptions.extend(
                    await datascraper.manage_subscriptions(
                        authed, identifiers=identifiers  # type: ignore
                    )
                )
            status = True
        elif (
            auth.auth_details.email
            and auth.auth_details.password
            and site_settings.browser.auth
        ):
            # domain = "https://onlyfans.com"
            # oflogin.login(auth, domain, auth.session_manager.get_proxy())
            pass
        return status, subscriptions

    async def process_jobs(
        self,
        datascraper: datascraper_types,
        subscription_list: list[user_types],
        site_settings: make_settings.SiteSettings,
    ):
        from ultima_scraper.modules.onlyfans import OnlyFansDataScraper

        api = datascraper.api
        if site_settings.jobs.scrape.subscriptions and api.has_active_auths():
            print("Scraping Subscriptions")
            for subscription in subscription_list:
                # Extra Auth Support
                authed = subscription.get_authed()
                await datascraper.start_datascraper([subscription])
                scrape_job = subscription.get_job("scrape.subscriptions")
                if scrape_job:
                    scrape_job.done = True
                pass
        if site_settings.jobs.scrape.paid_contents and api.has_active_auths():
            print("Scraping Paid Content")
            for authed in datascraper.api.auths:
                await datascraper.paid_content_scraper(authed)
        if (
            site_settings.jobs.scrape.messages
            and api.has_active_auths()
            and isinstance(datascraper, OnlyFansDataScraper)
        ):
            print("Scraping Message Content")
            for authed in datascraper.api.auths:
                chats = await authed.get_chats()
                for chat in chats:
                    username: str = chat["withUser"].username
                    subscription = await authed.get_subscription(identifier=username)
                    if not subscription:
                        subscription = chat["withUser"]
                        authed.subscriptions.append(subscription)
                    await datascraper.start_datascraper(
                        authed, username, whitelist=["Messages"]
                    )
        if not subscription_list:
            print("There's no subscriptions to scrape.")
        return subscription_list

    async def process_downloads(
        self,
        api: OnlyFans.start | Fansly.start,
        datascraper: datascraper_types,
        global_settings: make_settings.Settings,
    ):
        helpers = global_settings.helpers
        if helpers.downloader:
            for auth in api.auths:
                subscriptions = await auth.get_subscriptions(refresh=False)
                for subscription in subscriptions:
                    if not await subscription.if_scraped():
                        continue
                    await datascraper.prepare_downloads(subscription)
                    download_job = subscription.get_job("download")
                    if download_job:
                        download_job.done = True
                    if helpers.delete_empty_directories:
                        main_helper.delete_empty_directories(
                            subscription.directory_manager.user.download_directory
                        )

    async def get_chat_users(self):
        chat_users: list[user_types] = []
        for authed in self.datascraper.api.auths:
            chats = await authed.get_chats()
            for chat in chats:
                username: str = chat["withUser"].username
                subscription = await authed.get_subscription(identifier=username)
                if not subscription:
                    subscription = chat["withUser"]
                    chat_users.append(subscription)
        return chat_users
