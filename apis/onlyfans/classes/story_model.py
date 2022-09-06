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
        self.media: list[dict[str, Any]] = option.get("media", [])
        self.question: Any = option.get("question")
        self.placedContents: list = option.get("placedContents")
        self.answered: int = option.get("answered")

    async def link_picker(self, media: dict[str, Any], video_quality: str):
        link = ""
        if "files" in media:
            if "source" in media["files"]:
                quality_key = "source"
                source = media["files"][quality_key]
                link = source["url"]
                if link:
                    if media["type"] == "video":
                        qualities = source["sources"]
                        qualities = dict(sorted(qualities.items(), reverse=False))
                        for quality, quality_link in qualities.items():
                            video_quality = video_quality.removesuffix("p")
                            if quality == video_quality:
                                if quality_link:
                                    link = quality_link
                                    break
        return link
