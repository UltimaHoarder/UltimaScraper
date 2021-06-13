from typing import Optional

from apis.onlyfans.classes import create_user
from apis.onlyfans.classes.extras import endpoint_links


class create_message:
    def __init__(self, option: dict, user: create_user) -> None:
        self.responseType: Optional[str] = option.get("responseType")
        self.text: Optional[str] = option.get("text")
        self.lockedText: Optional[bool] = option.get("lockedText")
        self.isFree: Optional[bool] = option.get("isFree")
        self.price: Optional[float] = option.get("price")
        self.isMediaReady: Optional[bool] = option.get("isMediaReady")
        self.mediaCount: Optional[int] = option.get("mediaCount")
        self.media: Optional[list] = option.get("media")
        self.previews: list = option.get("previews",[])
        self.isTip: Optional[bool] = option.get("isTip")
        self.isReportedByMe: Optional[bool] = option.get("isReportedByMe")
        self.fromUser: Optional[dict] = option.get("fromUser")
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
        # Custom
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
