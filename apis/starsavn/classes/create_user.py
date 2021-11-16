from datetime import datetime
import math
from itertools import chain
from typing import Any, Optional, Union
from urllib import parse

from dateutil.relativedelta import relativedelta

import apis.starsavn.classes.create_message as create_message
from apis import api_helper
from apis.starsavn.classes import create_auth
from apis.starsavn.classes.create_highlight import create_highlight
from apis.starsavn.classes.create_post import create_post
from apis.starsavn.classes.create_product import create_product
from apis.starsavn.classes.create_story import create_story
from apis.starsavn.classes.extras import (
    content_types,
    endpoint_links,
    error_details,
    handle_refresh,
    remove_errors,
)


class create_user:
    def __init__(self, option={}, subscriber: create_auth = None) -> None:
        self.view: str = option.get("view")
        self.avatar: Any = option.get("avatar")
        self.avatarThumbs: Any = option.get("avatarThumbs")
        self.header: Any = option.get("header")
        self.headerSize: Any = option.get("headerSize")
        self.headerThumbs: Any = option.get("headerThumbs")
        self.id: int = option.get("id")
        self.name: str = option.get("name")
        self.username: str = option.get("username")
        self.canLookStory: bool = option.get("canLookStory")
        self.canCommentStory: bool = option.get("canCommentStory")
        self.hasNotViewedStory: bool = option.get("hasNotViewedStory")
        self.isVerified: bool = option.get("isVerified")
        self.canPayInternal: bool = option.get("canPayInternal")
        self.hasScheduledStream: bool = option.get("hasScheduledStream")
        self.hasStream: bool = option.get("hasStream")
        self.hasStories: bool = option.get("hasStories")
        self.tipsEnabled: bool = option.get("tipsEnabled")
        self.tipsTextEnabled: bool = option.get("tipsTextEnabled")
        self.tipsMin: int = option.get("tipsMin")
        self.tipsMax: int = option.get("tipsMax")
        self.canEarn: bool = option.get("canEarn")
        self.canAddSubscriber: bool = option.get("canAddSubscriber")
        self.subscribePrice: int = option.get("subscribePrice")
        self.hasStripe: bool = option.get("hasStripe")
        self.isStripeExist: bool = option.get("isStripeExist")
        self.subscriptionBundles: list = option.get("subscriptionBundles")
        self.canSendChatToAll: bool = option.get("canSendChatToAll")
        self.creditsMin: int = option.get("creditsMin")
        self.creditsMax: int = option.get("creditsMax")
        self.isPaywallRestriction: bool = option.get("isPaywallRestriction")
        self.unprofitable: bool = option.get("unprofitable")
        self.listsSort: str = option.get("listsSort")
        self.listsSortOrder: str = option.get("listsSortOrder")
        self.canCreateLists: bool = option.get("canCreateLists")
        self.joinDate: str = option.get("joinDate")
        self.isReferrerAllowed: bool = option.get("isReferrerAllowed")
        self.about: str = option.get("about")
        self.rawAbout: str = option.get("rawAbout")
        self.website: str = option.get("website")
        self.wishlist: str = option.get("wishlist")
        self.location: str = option.get("location")
        self.postsCount: int = option.get("postsCount")
        self.archivedPostsCount: int = option.get("archivedPostsCount")
        self.photosCount: int = option.get("photosCount")
        self.videosCount: int = option.get("videosCount")
        self.audiosCount: int = option.get("audiosCount")
        self.mediasCount: dict[str,int] = option.get("mediaCount",{})
        self.promotions: list = option.get("promotions")
        self.lastSeen: Any = option.get("lastSeen")
        self.favoritesCount: int = option.get("favoritesCount")
        self.favoritedCount: int = option.get("favoritedCount")
        self.showPostsInFeed: bool = option.get("showPostsInFeed")
        self.canReceiveChatMessage: bool = option.get("canReceiveChatMessage")
        self.isPerformer: bool = option.get("isPerformer")
        self.isRealPerformer: bool = option.get("isRealPerformer")
        self.isSpotifyConnected: bool = option.get("isSpotifyConnected")
        self.subscribersCount: int = option.get("subscribersCount")
        self.hasPinnedPosts: bool = option.get("hasPinnedPosts")
        self.canChat: bool = option.get("canChat")
        self.callPrice: int = option.get("callPrice")
        self.isPrivateRestriction: bool = option.get("isPrivateRestriction")
        self.showSubscribersCount: bool = option.get("showSubscribersCount")
        self.showMediaCount: bool = option.get("showMediaCount")
        self.subscribedByData: Any = option.get("subscribedByData")
        self.subscribedOnData: Any = option.get("subscribedOnData")
        self.canPromotion: bool = option.get("canPromotion")
        self.canCreatePromotion: bool = option.get("canCreatePromotion")
        self.canCreateTrial: bool = option.get("canCreateTrial")
        self.isAdultContent: bool = option.get("isAdultContent")
        self.isBlocked: bool = option.get("isBlocked")
        self.canTrialSend: bool = option.get("canTrialSend")
        self.canAddPhone: bool = option.get("canAddPhone")
        self.phoneLast4: Any = option.get("phoneLast4")
        self.phoneMask: Any = option.get("phoneMask")
        self.hasNewTicketReplies: dict = option.get("hasNewTicketReplies")
        self.hasInternalPayments: bool = option.get("hasInternalPayments")
        self.isCreditsEnabled: bool = option.get("isCreditsEnabled")
        self.creditBalance: float = option.get("creditBalance")
        self.isMakePayment: bool = option.get("isMakePayment")
        self.isOtpEnabled: bool = option.get("isOtpEnabled")
        self.email: str = option.get("email")
        self.isEmailChecked: bool = option.get("isEmailChecked")
        self.isLegalApprovedAllowed: bool = option.get("isLegalApprovedAllowed")
        self.isTwitterConnected: bool = option.get("isTwitterConnected")
        self.twitterUsername: Any = option.get("twitterUsername")
        self.isAllowTweets: bool = option.get("isAllowTweets")
        self.isPaymentCardConnected: bool = option.get("isPaymentCardConnected")
        self.referalUrl: str = option.get("referalUrl")
        self.isVisibleOnline: bool = option.get("isVisibleOnline")
        self.subscribesCount: int = option.get("subscribesCount")
        self.canPinPost: bool = option.get("canPinPost")
        self.hasNewAlerts: bool = option.get("hasNewAlerts")
        self.hasNewHints: bool = option.get("hasNewHints")
        self.hasNewChangedPriceSubscriptions: bool = option.get(
            "hasNewChangedPriceSubscriptions"
        )
        self.notificationsCount: int = option.get("notificationsCount")
        self.chatMessagesCount: int = option.get("chatMessagesCount")
        self.isWantComments: bool = option.get("isWantComments")
        self.watermarkText: str = option.get("watermarkText")
        self.customWatermarkText: Any = option.get("customWatermarkText")
        self.hasWatermarkPhoto: bool = option.get("hasWatermarkPhoto")
        self.hasWatermarkVideo: bool = option.get("hasWatermarkVideo")
        self.canDelete: bool = option.get("canDelete")
        self.isTelegramConnected: bool = option.get("isTelegramConnected")
        self.advBlock: list = option.get("advBlock")
        self.hasPurchasedPosts: bool = option.get("hasPurchasedPosts")
        self.isEmailRequired: bool = option.get("isEmailRequired")
        self.isPayoutLegalApproved: bool = option.get("isPayoutLegalApproved")
        self.payoutLegalApproveState: str = option.get("payoutLegalApproveState")
        self.payoutLegalApproveRejectReason: Any = option.get(
            "payoutLegalApproveRejectReason"
        )
        self.enabledImageEditorForChat: bool = option.get("enabledImageEditorForChat")
        self.shouldReceiveLessNotifications: bool = option.get(
            "shouldReceiveLessNotifications"
        )
        self.canCalling: bool = option.get("canCalling")
        self.paidFeed: bool = option.get("paidFeed")
        self.canSendSms: bool = option.get("canSendSms")
        self.canAddFriends: bool = option.get("canAddFriends")
        self.isRealCardConnected: bool = option.get("isRealCardConnected")
        self.countPriorityChat: int = option.get("countPriorityChat")
        self.hasScenario: bool = option.get("hasScenario")
        self.isWalletAutorecharge: bool = option.get("isWalletAutorecharge")
        self.walletAutorechargeAmount: int = option.get("walletAutorechargeAmount")
        self.walletAutorechargeMin: int = option.get("walletAutorechargeMin")
        self.walletFirstRebills: bool = option.get("walletFirstRebills")
        self.closeFriends: int = option.get("closeFriends")
        self.canAlternativeWalletTopUp: bool = option.get("canAlternativeWalletTopUp")
        self.needIVApprove: bool = option.get("needIVApprove")
        self.ivStatus: Any = option.get("ivStatus")
        self.ivFailReason: Any = option.get("ivFailReason")
        self.canCheckDocsOnAddCard: bool = option.get("canCheckDocsOnAddCard")
        self.faceIdAvailable: bool = option.get("faceIdAvailable")
        self.ivCountry: Any = option.get("ivCountry")
        self.ivForcedVerified: bool = option.get("ivForcedVerified")
        self.ivFlow: str = option.get("ivFlow")
        self.isVerifiedReason: bool = option.get("isVerifiedReason")
        self.canReceiveManualPayout: bool = option.get("canReceiveManualPayout")
        self.canReceiveStripePayout: bool = option.get("canReceiveStripePayout")
        self.manualPayoutPendingDays: int = option.get("manualPayoutPendingDays")
        self.isNeedConfirmPayout: bool = option.get("isNeedConfirmPayout")
        self.canStreaming: bool = option.get("canStreaming")
        self.isScheduledStreamsAllowed: bool = option.get("isScheduledStreamsAllowed")
        self.canMakeExpirePosts: bool = option.get("canMakeExpirePosts")
        self.trialMaxDays: int = option.get("trialMaxDays")
        self.trialMaxExpiresDays: int = option.get("trialMaxExpiresDays")
        self.messageMinPrice: int = option.get("messageMinPrice")
        self.messageMaxPrice: int = option.get("messageMaxPrice")
        self.postMinPrice: int = option.get("postMinPrice")
        self.postMaxPrice: int = option.get("postMaxPrice")
        self.streamMinPrice: int = option.get("streamMinPrice")
        self.streamMaxPrice: int = option.get("streamMaxPrice")
        self.canCreatePaidStream: bool = option.get("canCreatePaidStream")
        self.callMinPrice: int = option.get("callMinPrice")
        self.callMaxPrice: int = option.get("callMaxPrice")
        self.subscribeMinPrice: float = option.get("subscribeMinPrice")
        self.subscribeMaxPrice: int = option.get("subscribeMaxPrice")
        self.bundleMaxPrice: int = option.get("bundleMaxPrice")
        self.unclaimedOffersCount: int = option.get("unclaimedOffersCount")
        self.claimedOffersCount: int = option.get("claimedOffersCount")
        self.withdrawalPeriod: str = option.get("withdrawalPeriod")
        self.canAddStory: bool = option.get("canAddStory")
        self.canAddSubscriberByBundle: bool = option.get("canAddSubscriberByBundle")
        self.isSuggestionsOptOut: bool = option.get("isSuggestionsOptOut")
        self.canCreateFundRaising: bool = option.get("canCreateFundRaising")
        self.minFundRaisingTarget: int = option.get("minFundRaisingTarget")
        self.maxFundRaisingTarget: int = option.get("maxFundRaisingTarget")
        self.disputesRatio: int = option.get("disputesRatio")
        self.vaultListsSort: str = option.get("vaultListsSort")
        self.vaultListsSortOrder: str = option.get("vaultListsSortOrder")
        self.canCreateVaultLists: bool = option.get("canCreateVaultLists")
        self.canMakeProfileLinks: bool = option.get("canMakeProfileLinks")
        self.replyOnSubscribe: bool = option.get("replyOnSubscribe")
        self.payoutType: str = option.get("payoutType")
        self.minPayoutSumm: int = option.get("minPayoutSumm")
        self.canHasW9Form: bool = option.get("canHasW9Form")
        self.isVatRequired: bool = option.get("isVatRequired")
        self.isCountryVatRefundable: bool = option.get("isCountryVatRefundable")
        self.isCountryVatNumberCollect: bool = option.get("isCountryVatNumberCollect")
        self.vatNumberName: str = option.get("vatNumberName")
        self.isCountryWithVat: bool = option.get("isCountryWithVat")
        self.connectedOfAccounts: list = option.get("connectedOfAccounts")
        self.hasPassword: bool = option.get("hasPassword")
        self.canConnectOfAccount: bool = option.get("canConnectOfAccount")
        self.pinnedPostsCount: int = option.get("pinnedPostsCount")
        self.maxPinnedPostsCount: int = option.get("maxPinnedPostsCount")
        # Custom
        self.subscriber = subscriber
        self.scraped = content_types()
        self.temp_scraped = content_types()
        self.session_manager = None
        if subscriber:
            self.session_manager = subscriber.session_manager
        self.download_info = {}
        self.__raw__ = option

    def get_link(self):
        link = f"https://onlyfans.com/{self.username}"
        return link

    def is_me(self) -> bool:
        status = False
        if self.email:
            status = True
        return status

    async def get_stories(
        self, refresh=True, limit=100, offset=0
    ) -> list[create_story]:
        api_type = "stories"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        if not self.hasStories:
            return []
        link = [
            endpoint_links(
                identifier=self.id, global_limit=limit, global_offset=offset
            ).stories_api
        ]
        results = await api_helper.scrape_endpoint_links(
            link, self.session_manager, api_type
        )
        results = [create_story(x) for x in results]
        self.temp_scraped.Stories = results
        return results

    async def get_highlights(
        self, identifier="", refresh=True, limit=100, offset=0, hightlight_id=""
    ) -> Union[list[create_highlight], list[create_story]]:
        api_type = "highlights"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        if not identifier:
            identifier = self.id
        if not hightlight_id:
            link = endpoint_links(
                identifier=identifier, global_limit=limit, global_offset=offset
            ).list_highlights
            results = await self.session_manager.json_request(link)
            results = await remove_errors(results)
            results = [create_highlight(x) for x in results]
        else:
            link = endpoint_links(
                identifier=hightlight_id, global_limit=limit, global_offset=offset
            ).highlight
            results = await self.session_manager.json_request(link)
            results = [create_story(x) for x in results["stories"]]
        return results

    async def get_posts(
        self, links: Optional[list[str]] = None, limit=10, offset=0, refresh=True
    ) -> Optional[list[create_post]]:
        api_type = "posts"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        if links is None:
            links = []
        api_count = self.postsCount
        if api_count and not links:
            link = endpoint_links(
                identifier=self.id, global_limit=limit, global_offset=offset
            ).post_api
            ceil = math.ceil(api_count / limit)
            numbers = list(range(ceil))
            for num in numbers:
                num = num * limit
                link = link.replace(f"limit={limit}", f"limit={limit}")
                new_link = link.replace("offset=0", f"offset={num}")
                links.append(new_link)
        results = await api_helper.scrape_endpoint_links(
            links, self.session_manager, api_type
        )
        final_results = self.finalize_content_set(results)
        self.temp_scraped.Posts = final_results
        return final_results

    async def get_post(
        self, identifier=None, limit=10, offset=0
    ) -> Union[create_post, error_details]:
        if not identifier:
            identifier = self.id
        link = endpoint_links(
            identifier=identifier, global_limit=limit, global_offset=offset
        ).post_by_id
        response = await self.session_manager.json_request(link)
        if isinstance(response, dict):
            final_result = create_post(response, self)
            return final_result
        return response

    async def get_medias(
        self, links: Optional[list[str]] = None, limit:int=10, offset:int=0, refresh:bool=True
    ) -> Optional[list[create_post]]:
        api_type = "medias"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        if links is None:
            links = []
        api_count = self.mediasCount["total"]
        if api_count and not links:
            link = endpoint_links(
                identifier=self.id, global_limit=limit, global_offset=offset
            ).media_api
            ceil = math.ceil(api_count / limit)
            numbers = list(range(ceil))
            for num in numbers:
                num = num * limit
                link = link.replace(f"limit={limit}", f"limit={limit}")
                new_link = link.replace("offset=0", f"offset={num}")
                links.append(new_link)
        results = await api_helper.scrape_endpoint_links(
            links, self.session_manager, api_type
        )
        final_results = self.finalize_content_set(results)
        self.temp_scraped.Products = final_results
        return final_results
    async def get_messages(
        self,
        links: Optional[list] = None,
        limit=10,
        offset=0,
        refresh=True,
        inside_loop=False,
    ) -> Optional[list]:
        api_type = "messages"
        if not self.subscriber or self.is_me():
            return []
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        if links is None:
            links = []
        multiplier = getattr(self.session_manager.pool, "_processes")
        if links:
            link = links[-1]
        else:
            link = endpoint_links(
                identifier=self.id, global_limit=limit, global_offset=offset
            ).message_api
            links.append(link)
        links2 = api_helper.calculate_the_unpredictable(link, limit, multiplier)
        if not inside_loop:
            links += links2
        else:
            links = links2
        results = await self.session_manager.async_requests(links)
        results = await remove_errors(results)
        final_results = [x for x in results if x]
        has_more = False
        final_results = list(chain.from_iterable(final_results))

        if has_more:
            results2 = await self.get_messages(
                links=[links[-1]], limit=limit, offset=limit + offset, inside_loop=True
            )
            final_results.extend(results2)
        print
        if not inside_loop:
            final_results = [
                create_message.create_message(x, self) for x in final_results if x
            ]
        else:
            final_results.sort(key=lambda x: x["fromUser"]["id"], reverse=True)
        self.temp_scraped.Messages = final_results
        return final_results

    async def get_message_by_id(
        self, user_id=None, message_id=None, refresh=True, limit=10, offset=0
    ):
        if not user_id:
            user_id = self.id
        link = endpoint_links(
            identifier=user_id,
            identifier2=message_id,
            global_limit=limit,
            global_offset=offset,
        ).message_by_id
        response = await self.session_manager.json_request(link)
        if isinstance(response, dict):
            results = [x for x in response["list"] if x["id"] == message_id]
            result = results[0] if results else {}
            final_result = create_message.create_message(result, self)
            return final_result
        return response

    async def get_archived_stories(self, refresh=True, limit=100, offset=0):
        api_type = "archived_stories"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        link = endpoint_links(global_limit=limit, global_offset=offset).archived_stories
        results = await self.session_manager.json_request(link)
        results = await remove_errors(results)
        results = [create_story(x) for x in results]
        return results

    async def get_archived_posts(
        self, links: Optional[list] = None, limit=10, offset=0, refresh=True
    ) -> list:
        api_type = "archived_posts"
        if not refresh:
            result = handle_refresh(self, api_type)
            if result:
                return result
        if links is None:
            links = []
        api_count = self.archivedPostsCount
        if api_count and not links:
            link = endpoint_links(
                identifier=self.id, global_limit=limit, global_offset=offset
            ).archived_posts
            ceil = math.ceil(api_count / limit)
            numbers = list(range(ceil))
            for num in numbers:
                num = num * limit
                link = link.replace(f"limit={limit}", f"limit={limit}")
                new_link = link.replace("offset=0", f"offset={num}")
                links.append(new_link)
        results = await api_helper.scrape_endpoint_links(
            links, self.session_manager, api_type
        )
        final_results = self.finalize_content_set(results)

        self.temp_scraped.Archived.Posts = final_results
        return final_results

    async def get_archived(self, api):
        items = []
        if self.is_me():
            item = {}
            item["type"] = "Stories"
            item["results"] = [await self.get_archived_stories()]
            items.append(item)
        item = {}
        item["type"] = "Posts"
        # item["results"] = test
        item["results"] = await self.get_archived_posts()
        items.append(item)
        return items

    async def search_chat(
        self, identifier="", text="", refresh=True, limit=10, offset=0
    ):
        if identifier:
            identifier = parse.urljoin(identifier, "messages")
        link = endpoint_links(
            identifier=identifier, text=text, global_limit=limit, global_offset=offset
        ).search_chat
        results = await self.session_manager.json_request(link)
        return results

    async def search_messages(
        self, identifier="", text="", refresh=True, limit=10, offset=0
    ):
        if identifier:
            identifier = parse.urljoin(identifier, "messages")
        text = parse.quote_plus(text)
        link = endpoint_links(
            identifier=identifier, text=text, global_limit=limit, global_offset=offset
        ).search_messages
        results = await self.session_manager.json_request(link)
        return results

    async def like(self, category: str, identifier: int):
        link = endpoint_links(identifier=category, identifier2=identifier).like
        results = await self.session_manager.json_request(link, method="POST")
        return results

    async def unlike(self, category: str, identifier: int):
        link = endpoint_links(identifier=category, identifier2=identifier).like
        results = await self.session_manager.json_request(link, method="DELETE")
        return results

    async def subscription_price(self):
        """
        Returns subscription price. This includes the promotional price.
        """
        subscription_price = self.subscribePrice
        if self.promotions:
            for promotion in self.promotions:
                promotion_price = promotion["price"]
                if promotion_price < subscription_price:
                    subscription_price = promotion_price
        return subscription_price

    async def buy_subscription(self):
        """
        This function will subscribe to a model. If the model has a promotion available, it will use it.
        """
        subscription_price = await self.subscription_price()
        x = {
            "paymentType": "subscribe",
            "userId": self.id,
            "subscribeSource": "profile",
            "amount": subscription_price,
            "token": "",
            "unavailablePaymentGates": [],
        }
        if self.subscriber.creditBalance >= subscription_price:
            link = endpoint_links().pay
            result = await self.session_manager.json_request(
                link, method="POST", payload=x
            )
        else:
            result = error_details(
                {"code": 2011, "message": "Insufficient Credit Balance"}
            )
        return result

    def set_scraped(self, name, scraped):
        setattr(self.scraped, name, scraped)
    def finalize_content_set(self,results:list[dict[str,Any]]):
        final_results:list[create_post|create_product] = []
        for result in results:
            result["media"] = [result["media"]] if isinstance(result["media"], dict) else result["media"]
            if "mediaSet" in result:
                result["media"] = result["mediaSet"]
            if "id" in result:
                created = create_post(result,self)
            else:
                created = create_product(result,self)
            final_results.append(created)
        return final_results