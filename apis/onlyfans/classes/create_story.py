from typing import Any


class create_story:
    def __init__(self, option={}) -> None:
        self.id: int = option.get("id")
        self.userId: int = option.get("userId")
        self.createdAt: str = option.get("createdAt")
        self.expiredAt: str = option.get("expiredAt")
        self.isReady: bool = option.get("isReady")
        self.viewersCount: int = option.get("viewersCount")
        self.viewers: list = option.get("viewers")
        self.canLike: bool = option.get("canLike")
        self.mediaCount: int = option.get("mediaCount")
        self.isWatched: bool = option.get("isWatched")
        self.isLiked: bool = option.get("isLiked")
        self.canDelete: bool = option.get("canDelete")
        self.isHighlightCover: bool = option.get("isHighlightCover")
        self.isLastInHighlight: bool = option.get("isLastInHighlight")
        self.media: list = option.get("media")
        self.question: Any = option.get("question")
        self.placedContents: list = option.get("placedContents")
        self.answered: int = option.get("answered")
