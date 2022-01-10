from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from apis.fansly.classes import user_model
from apis.fansly.classes.extras import endpoint_links

if TYPE_CHECKING:
    from apis.fansly.classes.user_model import create_user


class create_message:
    def __init__(
        self, option: dict[str, Any], user: create_user, extra: dict[Any, Any] = {}
    ) -> None:
        self.responseType: Optional[str] = option.get("responseType")
        self.text: Optional[str] = option.get("text")
        self.lockedText: Optional[bool] = option.get("lockedText")
        self.isFree: Optional[bool] = option.get("isFree")
        self.price: Optional[float] = option.get("price")
        self.isMediaReady: Optional[bool] = option.get("isMediaReady")
        self.mediaCount: Optional[int] = option.get("mediaCount")
        self.media: list = option.get("media", [])
        self.previews: list = option.get("previews", [])
        self.isTip: Optional[bool] = option.get("isTip")
        self.isReportedByMe: Optional[bool] = option.get("isReportedByMe")
        self.fromUser = user
        self.isFromQueue: Optional[bool] = option.get("isFromQueue")
        self.queueId: Optional[int] = option.get("queueId")
        self.canUnsendQueue: Optional[bool] = option.get("canUnsendQueue")
        self.unsendSecondsQueue: Optional[int] = option.get("unsendSecondsQueue")
        self.id: Optional[int] = option.get("id")
        self.isOpened: Optional[bool] = option.get("isOpened")
        self.isNew: Optional[bool] = option.get("isNew")
        self.createdAt: Optional[str] = option.get("createdAt")
        self.changedAt: Optional[str] = option.get("changedAt")
        self.cancelSeconds: Optional[int] = option.get("cancelSeconds")
        self.isLiked: Optional[bool] = option.get("isLiked")
        self.canPurchase: Optional[bool] = option.get("canPurchase")
        self.canPurchaseReason: Optional[str] = option.get("canPurchaseReason")
        self.canReport: Optional[bool] = option.get("canReport")
        self.attachments: list = option.get("attachments")
        # Custom
        final_media: list[Any] = []
        final_media_ids: list[Any] = []
        for attachment in self.attachments:
            attachment_content_id = attachment["contentId"]
            match attachment["contentType"]:
                case 1:
                    final_media_ids.append(attachment_content_id)
                case 2:
                    for bundle in extra["accountMediaBundles"]:
                        if bundle["id"] == attachment_content_id:
                            final_media_ids.extend(bundle["accountMediaIds"])
                case _:
                    print
        if final_media_ids:
            for final_media_id in final_media_ids:
                for account_media in extra["accountMedia"]:
                    if account_media["id"] == final_media_id:
                        final_media.append(account_media)
        self.media: list[Any] = final_media
        self.user = user

    async def buy_message(self):
        """
        This function will buy a ppv message from a model.
        """
        message_price = self.price
        x = {
            "amount": message_price,
            "messageId": self.id,
            "paymentType": "message",
            "token": "",
            "unavailablePaymentGates": [],
        }
        link = endpoint_links().pay
        result = await self.user.session_manager.json_request(
            link, method="POST", payload=x
        )
        return result

    async def link_picker(self, media: dict[Any, Any], target_quality: str):
        # There are two media results at play here.
        # The top-level `media` element itself represents the original source quality.
        # It may also contain a `variants` list entry with alternate encoding qualities.
        # Each variant has a similar structure to the main media element.
        media_url = ""
        source_media = media
        variants = media.get("variants", [])

        if target_quality == "source":
            try:
                return source_media["locations"][0]["location"]
            except (KeyError, IndexError):
                pass

        # Track the target type as videos may also include thumbnail image variants.
        target_type = source_media.get("mimetype")

        qualities: list[tuple[int, str]] = []
        for variant in variants + [source_media]:
            if variant.get("mimetype") != target_type:
                continue

            media_quality = variant["height"]
            try:
                media_url = variant["locations"][0]["location"]
            except (KeyError, IndexError):
                continue
            qualities.append((media_quality, media_url))

        if not qualities:
            return

        # Iterate the media from highest to lowest quality.
        for media_quality, media_url in sorted(qualities, reverse=True):
            # If there was no "source" quality media, return the highest quality/first media.
            if target_quality == "source":
                return media_url

            # Return the first media <= the target quality.
            if media_quality <= int(target_quality):
                return media_url

        # If all media was > target quality, return the lowest quality/last media.
        return media_url
