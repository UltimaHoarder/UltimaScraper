from __future__ import annotations

from typing import TYPE_CHECKING, Any

import apis.starsavn.classes.user_model as user_model
from apis.starsavn.classes.extras import endpoint_links

if TYPE_CHECKING:
    from apis.starsavn.classes.user_model import create_user


class create_product:
    def __init__(self, option: dict[str, Any], user: create_user) -> None:
        self.responseType: str = option.get("responseType")
        self.id: int = option.get("productId")
        self.postedAt: str = option.get("postedAt")
        self.postedAtPrecise: str = option.get("postedAtPrecise")
        self.expiredAt: Any = option.get("expiredAt")
        self.author = user
        text: str = option.get("text", "")
        self.text = str(text or "")
        raw_text: str = option.get("rawText", "")
        self.rawText = str(raw_text or "")
        self.lockedText: bool = option.get("lockedText")
        self.isFavorite: bool = option.get("isFavorite")
        self.isReportedByMe: bool = option.get("isReportedByMe")
        self.canReport: bool = option.get("canReport")
        self.canDelete: bool = option.get("canDelete")
        self.canComment: bool = option.get("canComment")
        self.canEdit: bool = option.get("canEdit")
        self.isPinned: bool = option.get("isPinned")
        self.favoritesCount: int = option.get("favoritesCount")
        self.mediaCount: int = option.get("mediaCount")
        self.isMediaReady: bool = option.get("isMediaReady")
        self.voting: list = option.get("voting")
        self.isOpened: bool = option.get("isOpened")
        self.canToggleFavorite: bool = option.get("canToggleFavorite")
        self.streamId: Any = option.get("streamId")
        self.price: Any = option.get("price")
        self.hasVoting: bool = option.get("hasVoting")
        self.isAddedToBookmarks: bool = option.get("isAddedToBookmarks")
        self.isArchived: bool = option.get("isArchived")
        self.isDeleted: bool = option.get("isDeleted")
        self.hasUrl: bool = option.get("hasUrl")
        self.commentsCount: int = option.get("commentsCount")
        self.mentionedUsers: list = option.get("mentionedUsers")
        self.linkedUsers: list = option.get("linkedUsers")
        self.linkedPosts: list = option.get("linkedPosts")
        self.media: list[dict[str, Any]] = option.get("media", [])
        self.canViewMedia: bool = option.get("canViewMedia")
        self.preview: list[int] = option.get("preview", [])
        self.canPurchase: bool = option.get("canPurchase")

    async def favorite(self):
        link = endpoint_links(
            identifier=f"{self.responseType}s",
            identifier2=self.id,
            identifier3=self.author.id,
        ).favorite
        results = await self.user.get_session_manager().json_request(
            link, method="POST"
        )
        self.isFavorite = True
        return results

    async def link_picker(self, media, video_quality):
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
                            print
                        print
                    print
        if "src" in media:
            link = media["src"]["source"]
        return link
