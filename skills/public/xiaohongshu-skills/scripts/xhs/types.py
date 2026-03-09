"""小红书数据类型定义，对应 Go types.go。"""

from __future__ import annotations

from dataclasses import dataclass, field

# ========== Feed 列表 ==========


@dataclass
class ImageInfo:
    image_scene: str = ""
    url: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> ImageInfo:
        return cls(
            image_scene=d.get("imageScene", ""),
            url=d.get("url", ""),
        )


@dataclass
class VideoCapability:
    duration: int = 0  # 秒

    @classmethod
    def from_dict(cls, d: dict) -> VideoCapability:
        return cls(duration=d.get("duration", 0))


@dataclass
class Video:
    capa: VideoCapability = field(default_factory=VideoCapability)

    @classmethod
    def from_dict(cls, d: dict) -> Video:
        return cls(capa=VideoCapability.from_dict(d.get("capa", {})))


@dataclass
class Cover:
    width: int = 0
    height: int = 0
    url: str = ""
    file_id: str = ""
    url_pre: str = ""
    url_default: str = ""
    info_list: list[ImageInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Cover:
        return cls(
            width=d.get("width", 0),
            height=d.get("height", 0),
            url=d.get("url", ""),
            file_id=d.get("fileId", ""),
            url_pre=d.get("urlPre", ""),
            url_default=d.get("urlDefault", ""),
            info_list=[ImageInfo.from_dict(i) for i in d.get("infoList", [])],
        )


@dataclass
class User:
    user_id: str = ""
    nickname: str = ""
    nick_name: str = ""
    avatar: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> User:
        return cls(
            user_id=d.get("userId", ""),
            nickname=d.get("nickname", ""),
            nick_name=d.get("nickName", ""),
            avatar=d.get("avatar", ""),
        )


@dataclass
class InteractInfo:
    liked: bool = False
    liked_count: str = ""
    shared_count: str = ""
    comment_count: str = ""
    collected_count: str = ""
    collected: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> InteractInfo:
        return cls(
            liked=d.get("liked", False),
            liked_count=d.get("likedCount", ""),
            shared_count=d.get("sharedCount", ""),
            comment_count=d.get("commentCount", ""),
            collected_count=d.get("collectedCount", ""),
            collected=d.get("collected", False),
        )


@dataclass
class NoteCard:
    type: str = ""
    display_title: str = ""
    user: User = field(default_factory=User)
    interact_info: InteractInfo = field(default_factory=InteractInfo)
    cover: Cover = field(default_factory=Cover)
    video: Video | None = None

    @classmethod
    def from_dict(cls, d: dict) -> NoteCard:
        video_data = d.get("video")
        return cls(
            type=d.get("type", ""),
            display_title=d.get("displayTitle", ""),
            user=User.from_dict(d.get("user", {})),
            interact_info=InteractInfo.from_dict(d.get("interactInfo", {})),
            cover=Cover.from_dict(d.get("cover", {})),
            video=Video.from_dict(video_data) if video_data else None,
        )


@dataclass
class Feed:
    xsec_token: str = ""
    id: str = ""
    model_type: str = ""
    note_card: NoteCard = field(default_factory=NoteCard)
    index: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> Feed:
        return cls(
            xsec_token=d.get("xsecToken", ""),
            id=d.get("id", ""),
            model_type=d.get("modelType", ""),
            note_card=NoteCard.from_dict(d.get("noteCard", {})),
            index=d.get("index", 0),
        )

    def to_dict(self) -> dict:
        """序列化为 JSON 兼容的字典。"""
        result: dict = {
            "id": self.id,
            "xsecToken": self.xsec_token,
            "modelType": self.model_type,
            "index": self.index,
            "displayTitle": self.note_card.display_title,
            "type": self.note_card.type,
            "user": {
                "userId": self.note_card.user.user_id,
                "nickname": self.note_card.user.nickname or self.note_card.user.nick_name,
            },
            "interactInfo": {
                "likedCount": self.note_card.interact_info.liked_count,
                "collectedCount": self.note_card.interact_info.collected_count,
                "commentCount": self.note_card.interact_info.comment_count,
                "sharedCount": self.note_card.interact_info.shared_count,
            },
        }
        cover = self.note_card.cover
        if cover.url or cover.url_default:
            result["cover"] = cover.url or cover.url_default
        if self.note_card.video:
            result["video"] = {"duration": self.note_card.video.capa.duration}
        return result


# ========== Feed 详情 ==========


@dataclass
class DetailImageInfo:
    width: int = 0
    height: int = 0
    url_default: str = ""
    url_pre: str = ""
    live_photo: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> DetailImageInfo:
        return cls(
            width=d.get("width", 0),
            height=d.get("height", 0),
            url_default=d.get("urlDefault", ""),
            url_pre=d.get("urlPre", ""),
            live_photo=d.get("livePhoto", False),
        )


@dataclass
class Comment:
    id: str = ""
    note_id: str = ""
    content: str = ""
    like_count: str = ""
    create_time: int = 0
    ip_location: str = ""
    liked: bool = False
    user_info: User = field(default_factory=User)
    sub_comment_count: str = ""
    sub_comments: list[Comment] = field(default_factory=list)
    show_tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Comment:
        return cls(
            id=d.get("id", ""),
            note_id=d.get("noteId", ""),
            content=d.get("content", ""),
            like_count=d.get("likeCount", ""),
            create_time=d.get("createTime", 0),
            ip_location=d.get("ipLocation", ""),
            liked=d.get("liked", False),
            user_info=User.from_dict(d.get("userInfo", {})),
            sub_comment_count=d.get("subCommentCount", ""),
            sub_comments=[cls.from_dict(c) for c in d.get("subComments", []) or []],
            show_tags=d.get("showTags", []) or [],
        )

    def to_dict(self) -> dict:
        result: dict = {
            "id": self.id,
            "content": self.content,
            "likeCount": self.like_count,
            "createTime": self.create_time,
            "ipLocation": self.ip_location,
            "user": {
                "userId": self.user_info.user_id,
                "nickname": self.user_info.nickname or self.user_info.nick_name,
            },
            "subCommentCount": self.sub_comment_count,
        }
        if self.sub_comments:
            result["subComments"] = [c.to_dict() for c in self.sub_comments]
        return result


@dataclass
class CommentList:
    list_: list[Comment] = field(default_factory=list)
    cursor: str = ""
    has_more: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> CommentList:
        return cls(
            list_=[Comment.from_dict(c) for c in d.get("list", []) or []],
            cursor=d.get("cursor", ""),
            has_more=d.get("hasMore", False),
        )


@dataclass
class FeedDetail:
    note_id: str = ""
    xsec_token: str = ""
    title: str = ""
    desc: str = ""
    type: str = ""
    time: int = 0
    ip_location: str = ""
    user: User = field(default_factory=User)
    interact_info: InteractInfo = field(default_factory=InteractInfo)
    image_list: list[DetailImageInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> FeedDetail:
        return cls(
            note_id=d.get("noteId", ""),
            xsec_token=d.get("xsecToken", ""),
            title=d.get("title", ""),
            desc=d.get("desc", ""),
            type=d.get("type", ""),
            time=d.get("time", 0),
            ip_location=d.get("ipLocation", ""),
            user=User.from_dict(d.get("user", {})),
            interact_info=InteractInfo.from_dict(d.get("interactInfo", {})),
            image_list=[DetailImageInfo.from_dict(i) for i in d.get("imageList", []) or []],
        )

    def to_dict(self) -> dict:
        return {
            "noteId": self.note_id,
            "title": self.title,
            "desc": self.desc,
            "type": self.type,
            "time": self.time,
            "ipLocation": self.ip_location,
            "user": {
                "userId": self.user.user_id,
                "nickname": self.user.nickname or self.user.nick_name,
            },
            "interactInfo": {
                "liked": self.interact_info.liked,
                "likedCount": self.interact_info.liked_count,
                "collectedCount": self.interact_info.collected_count,
                "collected": self.interact_info.collected,
                "commentCount": self.interact_info.comment_count,
                "sharedCount": self.interact_info.shared_count,
            },
            "imageList": [
                {
                    "width": img.width,
                    "height": img.height,
                    "urlDefault": img.url_default,
                }
                for img in self.image_list
            ],
        }


@dataclass
class FeedDetailResponse:
    note: FeedDetail = field(default_factory=FeedDetail)
    comments: CommentList = field(default_factory=CommentList)

    @classmethod
    def from_dict(cls, d: dict) -> FeedDetailResponse:
        return cls(
            note=FeedDetail.from_dict(d.get("note", {})),
            comments=CommentList.from_dict(d.get("comments", {})),
        )

    def to_dict(self) -> dict:
        return {
            "note": self.note.to_dict(),
            "comments": [c.to_dict() for c in self.comments.list_],
        }


# ========== 用户主页 ==========


@dataclass
class UserBasicInfo:
    gender: int = 0
    ip_location: str = ""
    desc: str = ""
    imageb: str = ""
    nickname: str = ""
    images: str = ""
    red_id: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> UserBasicInfo:
        return cls(
            gender=d.get("gender", 0),
            ip_location=d.get("ipLocation", ""),
            desc=d.get("desc", ""),
            imageb=d.get("imageb", ""),
            nickname=d.get("nickname", ""),
            images=d.get("images", ""),
            red_id=d.get("redId", ""),
        )


@dataclass
class UserInteraction:
    type: str = ""
    name: str = ""
    count: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> UserInteraction:
        return cls(
            type=d.get("type", ""),
            name=d.get("name", ""),
            count=d.get("count", ""),
        )


@dataclass
class UserProfileResponse:
    user_basic_info: UserBasicInfo = field(default_factory=UserBasicInfo)
    interactions: list[UserInteraction] = field(default_factory=list)
    feeds: list[Feed] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "basicInfo": {
                "nickname": self.user_basic_info.nickname,
                "redId": self.user_basic_info.red_id,
                "desc": self.user_basic_info.desc,
                "gender": self.user_basic_info.gender,
                "ipLocation": self.user_basic_info.ip_location,
            },
            "interactions": [
                {"type": i.type, "name": i.name, "count": i.count} for i in self.interactions
            ],
            "feeds": [f.to_dict() for f in self.feeds],
        }


# ========== 搜索 ==========


@dataclass
class FilterOption:
    """搜索筛选选项。"""

    sort_by: str = ""  # 综合|最新|最多点赞|最多评论|最多收藏
    note_type: str = ""  # 不限|视频|图文
    publish_time: str = ""  # 不限|一天内|一周内|半年内
    search_scope: str = ""  # 不限|已看过|未看过|已关注
    location: str = ""  # 不限|同城|附近


# ========== 发布 ==========


@dataclass
class PublishImageContent:
    """图文发布内容。"""

    title: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    schedule_time: str | None = None  # ISO8601 格式，None 表示立即发布
    is_original: bool = False
    visibility: str = ""  # 公开可见(默认)|仅自己可见|仅互关好友可见


@dataclass
class PublishVideoContent:
    """视频发布内容。"""

    title: str = ""
    content: str = ""
    tags: list[str] = field(default_factory=list)
    video_path: str = ""
    schedule_time: str | None = None  # ISO8601 格式
    visibility: str = ""  # 公开可见(默认)|仅自己可见|仅互关好友可见


# ========== 互动 ==========


@dataclass
class ActionResult:
    """通用动作响应（点赞/收藏等）。"""

    feed_id: str = ""
    success: bool = False
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "feed_id": self.feed_id,
            "success": self.success,
            "message": self.message,
        }


# ========== 评论加载配置 ==========


@dataclass
class CommentLoadConfig:
    """评论加载配置。"""

    click_more_replies: bool = False
    max_replies_threshold: int = 10
    max_comment_items: int = 0  # 0 = 不限
    scroll_speed: str = "normal"  # slow|normal|fast
