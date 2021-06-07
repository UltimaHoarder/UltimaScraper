class create_highlight:
    def __init__(self, option={}) -> None:
        self.id: int = option.get("id")
        self.userId: int = option.get("userId")
        self.title: str = option.get("title")
        self.coverStoryId: int = option.get("coverStoryId")
        self.cover: str = option.get("cover")
        self.storiesCount: int = option.get("storiesCount")
        self.createdAt: str = option.get("createdAt")
        self.stories: list = option.get("stories")
