from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from apis.onlyfans.classes import user_model
from apis.onlyfans.classes.extras import endpoint_links

if TYPE_CHECKING:
    from apis.onlyfans.classes.user_model import create_user


class create_message:
    def __init__(self, option: dict[str, Any], user: create_user) -> None:
        self.responseType: Optional[str] = option.get("responseType")
        self.text: Optional[str] = option.get("text")
        self.lockedText: Optional[bool] = option.get("lockedText")
        self.isFree: Optional[bool] = option.get("isFree")
        self.price: Optional[float] = option.get("price")
        self.isMediaReady: Optional[bool] = option.get("isMediaReady")
        self.mediaCount: Optional[int] = option.get("mediaCount")
        self.media: list[dict[str, Any]] = option.get("media", [])
        self.previews: list[dict[str, Any]] = option.get("previews", [])
        self.isTip: Optional[bool] = option.get("isTip")
        self.isReportedByMe: Optional[bool] = option.get("isReportedByMe")
        self.fromUser = (
            user
            if user.id == option["fromUser"]["id"]
            else user_model.create_user(option["fromUser"], user.get_authed())
        )
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

    async def get_author(self):
        return self.fromUser

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
        result = await self.fromUser.session_manager.json_request(
            link, method="POST", payload=x
        )
        return result

    async def link_picker(self, media: dict[str, Any], video_quality: str):
        link = ""
        if "source" in media:
            quality_key = "source"
            source = media[quality_key]
            link = source[quality_key]
            if link:
                if media["type"] == "video":
                    qualities = media["videoSources"]
                    qualities = dict(sorted(qualities.items(), reverse=False))
                    qualities[quality_key] = source[quality_key]
                    for quality, quality_link in qualities.items():
                        video_quality = video_quality.removesuffix("p")
                        if quality == video_quality:
                            if quality_link:
                                link = quality_link
                                break
        if "src" in media:
            link = media["src"]
        return link
