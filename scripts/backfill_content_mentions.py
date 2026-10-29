#!/usr/bin/env python3
"""Backfill archive content_mentions from linked_users and content text.

Runs safely in dry-run mode by default.  Text extraction records only explicit
``@handles``; it intentionally does not guess at ordinary names.

Usage:
    PYTHONPATH=. uv run python scripts/backfill_content_mentions.py --sites onlyfans
    PYTHONPATH=. uv run python scripts/backfill_content_mentions.py --sites onlyfans --apply
"""

from __future__ import annotations

import argparse
import re
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

from sqlalchemy import BigInteger, String, any_, bindparam, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Session

from ultima_scraper_backend.database.factory import MultiSiteDatabaseManager
from ultima_scraper_db_archive import (
    ContentMentionModel,
    MassMessageModel,
    MessageModel,
    PostModel,
    UserModel,
)

HANDLE_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]+)")
PLATFORM_URL_RE = re.compile(
    # Captions often concatenate URLs with no whitespace.  Stop before the
    # next URL scheme instead of treating the entire run as one malformed URL.
    r"https?://(?:www\.)?(?:onlyfans|fansly|loyalfans)\.com/[^\s<>'\"]*?(?=https?://|[\s<>'\"]|$)",
    re.IGNORECASE,
)
# Derived from the captured OnlyFans SPA router in UltimaRE.  These roots are
# application pages, not creator usernames; unknown roots remain reviewable.
ONLYFANS_APPLICATION_ROUTE_ROOTS = {
    "action", "antitraffickingstatement", "appeal", "banking-help", "blurred",
    "brand", "closefriends", "collections", "compliance", "compliance2",
    "contact", "contacts", "contract", "contractnov21", "dmca", "explore",
    "faq", "fightcsam", "gdpr", "help", "legalguide", "legalinquiry",
    "license_form", "my", "oauth", "partners", "posts", "privacy",
    "purchased", "queue", "referrals", "report_abuse", "report_dmca",
    "saved-for-later", "search", "store", "support", "tags-required", "terms",
    "terms-of-service", "termsnov21", "tos", "tosd", "transparency",
    "transparency-center", "usc2257", "values",
}
ProgressCallback = Callable[[str, int, int], None]
MAX_BIGINT = 9_223_372_036_854_775_807
PROFILE_SLUG_RE = re.compile(r"[A-Za-z0-9_.-]+")
PROFILE_CHILD_ROUTES = {
    "friends",
    "nft",
    "nfts",
    "media",
    "medias",
    "photos",
    "videos",
    "audios",
    "likes",
    "streams",
    "archived",
    "private_archived",
    "live",
}
POST_ACTION_ROUTES = {"likes", "tips", "buyers"}


def _profile_slug(value: str) -> str | None:
    """Return the URL-safe username prefix, excluding numeric-only values."""
    match = PROFILE_SLUG_RE.match(value)
    if not match or match.group(0).isdecimal():
        return None
    return match.group(0).casefold()


def _is_clean_profile_segment(value: str) -> bool:
    """Reject a URL segment that visibly contains a concatenated URL host."""
    normalized = value.casefold()
    # Platform names are legal username text (for example
    # ``oexample21``).  Only domain/scheme syntax is evidence that
    # another URL was actually glued into this path segment.
    return not (normalized.endswith(":") or ".com" in normalized)


def _excluded_route_signature(raw: str, parts: list[str]) -> str:
    """Group excluded application URLs by shape instead of volatile values."""
    parsed = urlsplit(raw)
    signature_parts = [
        ":id"
        if part.isdecimal()
        else ":token"
        if len(part) >= 16 and re.fullmatch(r"[A-Za-z0-9_-]+", part)
        else part.casefold()
        for part in parts
    ]
    return f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}/{'/'.join(signature_parts)}"


def _embedded_post_permalink(
    raw: str, parsed: Any, parts: list[str]
) -> tuple[str, str] | None:
    """Recover the last intact ``/<post id>/<creator>`` pair in a damaged URL."""
    # Some bad captions omit the slash before a second post ID, e.g.
    # /227503782/kexample20227503782/kexample20.  Check this first because the whole
    # damaged segment is otherwise syntactically a valid username.
    if len(parts) >= 3 and parts[0].isdecimal():
        following_creator = _profile_slug(parts[2])
        inserted_id = (
            parts[1][len(following_creator):]
            if following_creator and parts[1].casefold().startswith(following_creator)
            else ""
        )
        if following_creator and inserted_id.isdecimal() and len(inserted_id) >= 7:
            return (
                f"{parsed.scheme}://{parsed.netloc}/{parts[0]}/{following_creator}",
                following_creator,
            )
        match = re.fullmatch(r"(.+?)(\d{7,})", parts[1])
        creator = _profile_slug(match.group(1)) if match else None
        if creator and _is_clean_profile_segment(match.group(1)):
            return f"{parsed.scheme}://{parsed.netloc}/{parts[0]}/{creator}", creator

    pairs: list[tuple[int, str, str]] = []
    for index, post_id in enumerate(parts[:-1]):
        creator_segment = parts[index + 1]
        creator = _profile_slug(creator_segment)
        if post_id.isdecimal() and creator and _is_clean_profile_segment(creator_segment):
            pairs.append((index, post_id, creator))
    if pairs:
        index, post_id, creator = pairs[-1]
        # Keep the source text for a normal permalink.  For a glued run, show
        # the recovered canonical permalink in the preview instead.
        if index == 0 and len(pairs) == 1:
            return raw, creator
        return f"{parsed.scheme}://{parsed.netloc}/{post_id}/{creator}", creator

    return None


@dataclass(slots=True)
class MentionBackfillDetail:
    content_type: str
    content_id: int
    raw_mention: str
    normalized_mention: str
    mention_kind: str
    mentioned_user_id: int | None
    occurrence_count: int = 1
    raw_mentions: set[str] = field(default_factory=set)
    taggers: dict[int, str | None] = field(default_factory=dict)
    occurrences: list["MentionBackfillOccurrence"] = field(default_factory=list)


@dataclass(slots=True)
class MentionBackfillOccurrence:
    content_type: str
    content_id: int
    content_text: str | None
    tagger_user_id: int | None
    tagger_username: str | None


@dataclass(slots=True)
class MentionBackfillStats:
    site: str
    linked_users_seen: int = 0
    linked_users_inserted: int = 0
    content_rows_seen: int = 0
    handles_found: int = 0
    handles_resolved: int = 0
    text_mentions_inserted: int = 0
    details: dict[tuple[str, str, int | None], MentionBackfillDetail] = field(
        default_factory=dict
    )
    oversized_profile_links: dict[str, int] = field(default_factory=dict)
    ambiguous_profile_links: dict[str, int] = field(default_factory=dict)


def _add_detail(stats: MentionBackfillStats, detail: MentionBackfillDetail) -> None:
    """Group preview candidates by mention while retaining their taggers."""
    detail.raw_mentions.add(detail.raw_mention)
    key = (detail.normalized_mention, detail.mention_kind, detail.mentioned_user_id)
    existing = stats.details.get(key)
    if existing is None:
        stats.details[key] = detail
        return
    existing.occurrence_count += 1
    existing.raw_mentions.update(detail.raw_mentions)
    existing.taggers.update(detail.taggers)
    if len(existing.occurrences) < 50:
        existing.occurrences.extend(detail.occurrences)


def _merge_stats(target: MentionBackfillStats, source: MentionBackfillStats) -> None:
    target.content_rows_seen += source.content_rows_seen
    target.handles_found += source.handles_found
    target.handles_resolved += source.handles_resolved
    target.text_mentions_inserted += source.text_mentions_inserted
    for url, count in source.oversized_profile_links.items():
        target.oversized_profile_links[url] = target.oversized_profile_links.get(url, 0) + count
    for url, count in source.ambiguous_profile_links.items():
        target.ambiguous_profile_links[url] = target.ambiguous_profile_links.get(url, 0) + count
    for detail in source.details.values():
        _add_detail(target, detail)


def _sites(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for item in value.split(","):
            site = item.strip().lower()
            if site and site not in result:
                result.append(site)
    return result


def extract_handles(value: str | None) -> list[tuple[str, str]]:
    """Return unique explicit handles and profile-link targets in source order."""
    return [(raw, normalized) for raw, normalized, _ in extract_mentions(value)]


def extract_mentions(value: str | None) -> list[tuple[str, str, str]]:
    """Return ``(raw, normalized, kind)`` mentions from handles and platform URLs.

    The explicit OnlyFans route shapes below come from the captured SPA router.
    Unknown creator-prefixed paths are retained as lower-confidence candidates so
    archive data can still surface newer routes for review.
    """
    # A handle and a permalink can name the same user in one content row.
    # Preserve both evidence types: the URL is useful for preview search and
    # carries more context than the matching @handle.
    seen: set[tuple[str, str, str]] = set()
    result: list[tuple[str, str, str]] = []
    candidates = [
        (match.start(), f"@{match.group(1)}", match.group(1).casefold(), "handle")
        for match in HANDLE_RE.finditer(value or "")
    ]
    for match in PLATFORM_URL_RE.finditer(value or ""):
        raw = match.group(0).rstrip(".,;:!?)]}\"'")
        parsed = urlsplit(raw)
        parts = [part for part in parsed.path.split("/") if part]
        if not parts:
            continue
        root = parts[0].casefold()
        # /message/<post id>/<creator> is a real router permalink.  It is not
        # an application-root false positive even though /message is otherwise
        # an application section.
        if root == "message":
            author = _profile_slug(parts[2]) if len(parts) == 3 and parts[1].isdecimal() else None
            if author:
                candidates.append((match.start(), raw, author, "message_link_author"))
            else:
                candidates.append((match.start(), raw, raw.casefold(), "ambiguous_link"))
            continue
        # The SPA calls this value chatId, but it identifies the user whose
        # conversation is opened.  Preserve it as a numeric user candidate.
        chat_user_id_match = (
            re.match(r"\d+", parts[3])
            if root == "my"
            and len(parts) >= 4
            and parts[1].casefold() == "chats"
            and parts[2].casefold() == "chat"
            else None
        )
        if (
            root == "my"
            and len(parts) >= 4
            and parts[1].casefold() == "chats"
            and parts[2].casefold() == "chat"
            and chat_user_id_match is not None
        ):
            candidates.append(
                (
                    match.start(),
                    raw,
                    chat_user_id_match.group(0),
                    "chat_link_user_id",
                )
            )
            continue
        if _link_platform(raw) == "onlyfans" and root in ONLYFANS_APPLICATION_ROUTE_ROOTS:
            candidates.append(
                (
                    match.start(),
                    raw,
                    _excluded_route_signature(raw, parts),
                    "excluded_application_route",
                )
            )
            continue
        if len(parts) == 1:
            candidates.append((match.start(), raw, parts[0].casefold(), "profile_link"))
        elif parts[0].isdecimal():
            recovered_permalink = _embedded_post_permalink(raw, parsed, parts)
            author = recovered_permalink[1] if recovered_permalink else None
            is_post_route = (
                (len(parts) == 2 and parts[1].casefold() not in {"buyers", "claimers"})
                or (len(parts) == 3 and parts[2].casefold() in POST_ACTION_ROUTES)
                or (len(parts) >= 3 and parts[2].casefold() == "vote")
            )
            # A recovered pair after the initial path is evidence that a URL
            # was concatenated; it is safe even though the original path has
            # extra segments.
            recovered_from_deep_path = (
                recovered_permalink is not None and recovered_permalink[0] != raw
            )
            if author and (is_post_route or recovered_from_deep_path):
                candidates.append(
                    (
                        match.start(),
                        recovered_permalink[0],
                        author,
                        "post_link_author",
                    )
                )
            else:
                candidates.append((match.start(), raw, raw.casefold(), "ambiguous_link"))
        else:
            profile = _profile_slug(parts[0])
            child = parts[1].casefold()
            if not profile:
                candidates.append((match.start(), raw, raw.casefold(), "ambiguous_link"))
            elif child.startswith("c") and child[1:].isdecimal():
                candidates.append((match.start(), raw, profile, "profile_campaign_link"))
            elif child.isdecimal() or child in PROFILE_CHILD_ROUTES:
                candidates.append((match.start(), raw, profile, "profile_child_link"))
            elif child == "trial":
                # Seen in archive content; retain separately until a current
                # SPA bundle confirms the route shape.
                candidates.append((match.start(), raw, profile, "profile_trial_link"))
            else:
                candidates.append((match.start(), raw, profile, "heuristic_profile_link"))
    for _, raw, normalized, kind in sorted(candidates):
        # Excluded route variants share a grouping signature, but each raw URL
        # must survive so it remains searchable inside that group.
        key = (
            normalized,
            kind,
            raw.casefold() if kind.startswith("excluded_") else "",
        )
        if key not in seen:
            seen.add(key)
            result.append((raw, normalized, kind))
    return result


def _existing_keys(
    session: Session, *, parent_field: str, content_ids: list[int], kind: str | None
) -> set[tuple[int, str, str]]:
    if not content_ids:
        return set()
    parent = getattr(ContentMentionModel, parent_field)
    rows = session.exec(
        select(parent, ContentMentionModel.normalized_mention, ContentMentionModel.mention_kind)
        .where(
            parent
            == any_(bindparam("content_ids", type_=ARRAY(BigInteger)))
        ),
        params={"content_ids": content_ids},
    ).all()
    return {
        (int(content_id), str(normalized), str(mention_kind))
        for content_id, normalized, mention_kind in rows
        if kind is None or mention_kind == kind
    }


def _count_content_rows(session: Session, model: Any) -> int:
    """Return a scalar count across SQLAlchemy/SQLModel driver result shapes."""
    value = session.exec(select(func.count()).select_from(model)).one()
    try:
        return int(value)
    except TypeError:
        return int(value[0])


def _as_int(value: Any) -> int:
    """Unwrap a scalar returned either directly or in a SQL row wrapper."""
    try:
        return int(value)
    except TypeError:
        return int(value[0])


def _usernames_by_id(session: Session, user_ids: set[int]) -> dict[int, str | None]:
    if not user_ids:
        return {}
    return {
        int(user_id): str(username) if username else None
        for user_id, username in session.exec(
            select(UserModel.id, UserModel.username).where(
                UserModel.id == any_(bindparam("user_ids", type_=ARRAY(BigInteger)))
            ),
            params={"user_ids": list(user_ids)},
        ).all()
    }


def _fits_bigint(value: str) -> bool:
    return len(value) < 19 or (len(value) == 19 and value <= str(MAX_BIGINT))


def _link_platform(raw_url: str) -> str | None:
    hostname = urlsplit(raw_url).hostname or ""
    return hostname.removeprefix("www.").split(".", 1)[0].casefold() or None


def _mention_kind_for_archive(
    raw: str, mention_kind: str, archive_site: str
) -> str:
    if (
        mention_kind != "ambiguous_link"
        and mention_kind != "handle"
        and not mention_kind.startswith("excluded_")
    ):
        link_platform = _link_platform(raw)
        if link_platform and link_platform != archive_site:
            return "cross_platform_profile_link"
    return mention_kind


def _backfill_text_model(
    session: Session,
    *,
    model: Any,
    parent_field: str,
    content_type: str,
    archive_site: str,
    batch_size: int,
    limit: int | None,
    apply: bool,
    stats: MentionBackfillStats,
    total_content_rows: int,
    progress_callback: ProgressCallback | None,
    include_preview_context: bool,
) -> None:
    last_id = 0
    remaining = limit
    while remaining is None or remaining > 0:
        current_size = min(batch_size, remaining) if remaining is not None else batch_size
        rows = session.exec(
            select(model.id, model.text, model.user_id)
            .where(
                model.id > last_id,
                model.text.is_not(None),
                or_(
                    model.text.like("%@%"),
                    model.text.ilike("%onlyfans.com/%"),
                    model.text.ilike("%fansly.com/%"),
                    model.text.ilike("%loyalfans.com/%"),
                ),
            )
            .order_by(model.id)
            .limit(current_size)
        ).all()
        if not rows:
            return
        last_id = int(rows[-1][0])
        if remaining is not None:
            remaining -= len(rows)
        stats.content_rows_seen += len(rows)
        if progress_callback:
            progress_callback(content_type, stats.content_rows_seen, total_content_rows)
        mentions_by_content = {
            int(content_id): [
                (raw, normalized, _mention_kind_for_archive(raw, kind, archive_site))
                for raw, normalized, kind in extract_mentions(content_text)
            ]
            for content_id, content_text, _ in rows
        }
        resolvable_mentions_by_content = {
            content_id: [
                mention
                for mention in mentions
                if mention[2] != "ambiguous_link"
                and not mention[2].startswith("excluded_")
            ]
            for content_id, mentions in mentions_by_content.items()
        }
        excluded_mentions_by_content = {
            content_id: [
                mention for mention in mentions if mention[2].startswith("excluded_")
            ]
            for content_id, mentions in mentions_by_content.items()
        }
        content_text_by_id = {
            int(content_id): str(content_text) if content_text is not None else None
            for content_id, content_text, _ in rows
        }
        tagger_ids_by_content = {int(content_id): int(user_id) for content_id, _, user_id in rows}
        handles = {
            normalized
            for mentions in resolvable_mentions_by_content.values()
            for _, normalized, mention_kind in mentions
            if mention_kind != "cross_platform_profile_link"
        }
        for mentions in mentions_by_content.values():
            for raw, normalized, mention_kind in mentions:
                if mention_kind == "ambiguous_link":
                    stats.ambiguous_profile_links[raw] = (
                        stats.ambiguous_profile_links.get(raw, 0) + 1
                    )
                if (
                    mention_kind == "profile_link"
                    and normalized.isdecimal()
                    and not _fits_bigint(normalized)
                ):
                    stats.oversized_profile_links[raw] = (
                        stats.oversized_profile_links.get(raw, 0) + 1
                    )
        stats.handles_found += sum(len(item) for item in resolvable_mentions_by_content.values())
        users_by_handle: dict[str, int] = {}
        if handles:
            users_by_handle = {
                str(username).casefold(): int(user_id)
                for user_id, username in session.exec(
                    select(UserModel.id, UserModel.username).where(
                        func.lower(UserModel.username)
                        == any_(bindparam("handles", type_=ARRAY(String)))
                    ),
                    params={"handles": list(handles)},
                ).all()
                if username
            }
        numeric_profile_ids = {
            int(handle)
            for handle in handles
            if handle.isdecimal()
            and _fits_bigint(handle)
        }
        users_by_profile_id = {}
        if numeric_profile_ids:
            for row in session.exec(
                select(UserModel.id).where(
                    UserModel.id
                    == any_(bindparam("numeric_profile_ids", type_=ARRAY(BigInteger)))
                ),
                params={"numeric_profile_ids": list(numeric_profile_ids)},
            ).all():
                user_id = _as_int(row)
                users_by_profile_id[str(user_id)] = user_id
        existing = _existing_keys(
            session,
            parent_field=parent_field,
            content_ids=list(resolvable_mentions_by_content),
            kind=None,
        )
        tagger_ids = {
            tagger_ids_by_content[content_id]
            for content_id, mentions in resolvable_mentions_by_content.items()
            if any((content_id, normalized, kind) not in existing for _, normalized, kind in mentions)
        } if include_preview_context else set()
        if include_preview_context:
            tagger_ids.update(
                tagger_ids_by_content[content_id]
                for content_id, mentions in excluded_mentions_by_content.items()
                if mentions
            )
        tagger_usernames = _usernames_by_id(session, tagger_ids)
        for content_id, mentions in excluded_mentions_by_content.items():
            for raw, normalized, mention_kind in mentions:
                _add_detail(
                    stats,
                    MentionBackfillDetail(
                        content_type=content_type,
                        content_id=content_id,
                        raw_mention=raw,
                        normalized_mention=normalized,
                        mention_kind=mention_kind,
                        mentioned_user_id=None,
                        taggers={
                            tagger_ids_by_content[content_id]: tagger_usernames.get(
                                tagger_ids_by_content[content_id]
                            )
                        } if include_preview_context else {},
                        occurrences=[
                            MentionBackfillOccurrence(
                                content_type=content_type,
                                content_id=content_id,
                                content_text=(content_text_by_id[content_id] if include_preview_context else None),
                                tagger_user_id=(tagger_ids_by_content[content_id] if include_preview_context else None),
                                tagger_username=(tagger_usernames.get(tagger_ids_by_content[content_id]) if include_preview_context else None),
                            )
                        ],
                    ),
                )
        pending_mentions: list[ContentMentionModel] = []
        for content_id, mentions in resolvable_mentions_by_content.items():
            for raw, normalized, mention_kind in mentions:
                if (content_id, normalized, mention_kind) in existing:
                    continue
                if mention_kind == "cross_platform_profile_link":
                    mentioned_user_id = None
                else:
                    mentioned_user_id = (
                        users_by_handle.get(normalized)
                        or users_by_profile_id.get(normalized)
                    )
                if mentioned_user_id is not None:
                    stats.handles_resolved += 1
                stats.text_mentions_inserted += 1
                _add_detail(
                    stats,
                    MentionBackfillDetail(
                        content_type=content_type,
                        content_id=content_id,
                        raw_mention=raw,
                        normalized_mention=normalized,
                        mention_kind=mention_kind,
                        mentioned_user_id=mentioned_user_id,
                        taggers={
                            tagger_ids_by_content[content_id]: tagger_usernames.get(
                                tagger_ids_by_content[content_id]
                            )
                        } if include_preview_context else {},
                        occurrences=[
                            MentionBackfillOccurrence(
                                content_type=content_type,
                                content_id=content_id,
                                content_text=(content_text_by_id[content_id] if include_preview_context else None),
                                tagger_user_id=(tagger_ids_by_content[content_id] if include_preview_context else None),
                                tagger_username=(tagger_usernames.get(tagger_ids_by_content[content_id]) if include_preview_context else None),
                            )
                        ],
                    ),
                )
                if apply:
                    pending_mentions.append(
                        ContentMentionModel(
                            **{parent_field: content_id},
                            mentioned_user_id=mentioned_user_id,
                            raw_mention=raw,
                            normalized_mention=normalized,
                            mention_kind=mention_kind,
                        )
                    )
        if apply:
            session.add_all(pending_mentions)
            session.commit()


def _backfill_linked_users(
    session: Session, *, batch_size: int, apply: bool, stats: MentionBackfillStats,
    include_preview_context: bool,
) -> None:
    last_id = 0
    while True:
        rows = session.execute(
            text(
                """
                SELECT linked.id, linked.post_id, linked.linked_user_id,
                       COALESCE(users.username, linked.linked_user_id::text) AS raw_mention
                FROM linked_users AS linked
                LEFT JOIN users ON users.id = linked.linked_user_id
                WHERE linked.id > :last_id
                ORDER BY linked.id
                LIMIT :batch_size
                """
            ),
            {"last_id": last_id, "batch_size": batch_size},
        ).mappings().all()
        if not rows:
            return
        last_id = int(rows[-1]["id"])
        stats.linked_users_seen += len(rows)
        post_ids = [int(row["post_id"]) for row in rows]
        existing_users = {
            (int(post_id), int(mentioned_user_id))
            for post_id, mentioned_user_id in session.exec(
                select(ContentMentionModel.post_id, ContentMentionModel.mentioned_user_id).where(
                    ContentMentionModel.post_id
                    == any_(bindparam("post_ids", type_=ARRAY(BigInteger))),
                    ContentMentionModel.mention_kind == "platform_tag",
                ),
                params={"post_ids": post_ids},
            ).all()
            if post_id is not None and mentioned_user_id is not None
        }
        new_post_ids = [
            int(row["post_id"])
            for row in rows
            if (int(row["post_id"]), int(row["linked_user_id"])) not in existing_users
        ]
        post_details: dict[int, tuple[int, str | None]] = {}
        if include_preview_context and new_post_ids:
            post_details = {
                int(post_id): (
                    int(user_id),
                    str(content_text) if content_text is not None else None,
                )
                for post_id, user_id, content_text in session.exec(
                    select(PostModel.id, PostModel.user_id, PostModel.text).where(
                        PostModel.id
                        == any_(bindparam("new_post_ids", type_=ARRAY(BigInteger)))
                    ),
                    params={"new_post_ids": new_post_ids},
                ).all()
            }
        tagger_user_ids_by_post = {post_id: values[0] for post_id, values in post_details.items()}
        tagger_usernames = _usernames_by_id(
            session, set(tagger_user_ids_by_post.values())
        ) if include_preview_context else {}
        pending_mentions: list[ContentMentionModel] = []
        for row in rows:
            key = (int(row["post_id"]), int(row["linked_user_id"]))
            if key in existing_users:
                continue
            raw = str(row["raw_mention"])
            stats.linked_users_inserted += 1
            _add_detail(
                stats,
                MentionBackfillDetail(
                    content_type="post",
                    content_id=key[0],
                    raw_mention=raw,
                    normalized_mention=raw.lstrip("@").casefold(),
                    mention_kind="platform_tag",
                    mentioned_user_id=key[1],
                    taggers=(
                        {
                            tagger_user_ids_by_post[key[0]]: tagger_usernames.get(
                                tagger_user_ids_by_post[key[0]]
                            )
                        }
                        if include_preview_context and key[0] in tagger_user_ids_by_post
                        else {}
                    ),
                    occurrences=[
                        MentionBackfillOccurrence(
                            content_type="post",
                            content_id=key[0],
                            content_text=(post_details.get(key[0], (None, None))[1] if include_preview_context else None),
                            tagger_user_id=(tagger_user_ids_by_post.get(key[0]) if include_preview_context else None),
                            tagger_username=(tagger_usernames.get(tagger_user_ids_by_post.get(key[0], -1)) if include_preview_context else None),
                        )
                    ],
                ),
            )
            if apply:
                pending_mentions.append(
                    ContentMentionModel(
                        post_id=key[0],
                        mentioned_user_id=key[1],
                        raw_mention=raw,
                        normalized_mention=raw.lstrip("@").casefold(),
                        mention_kind="platform_tag",
                    )
                )
        if apply:
            session.add_all(pending_mentions)
            session.commit()


def backfill_site(
    site: str,
    *,
    batch_size: int,
    limit: int | None,
    apply: bool,
    progress_callback: ProgressCallback | None = None,
    include_preview_context: bool = True,
    include_legacy_links: bool = True,
    worker_count: int = 3,
) -> MentionBackfillStats:
    manager = MultiSiteDatabaseManager().get_or_create_manager(site)
    if manager is None:
        raise RuntimeError(f"Unsupported site: {site}")
    stats = MentionBackfillStats(site=site)
    with manager.get_session() as session:
        text_models = (
            (PostModel, "post_id", "post"),
            (MessageModel, "message_id", "message"),
            (MassMessageModel, "mass_message_id", "mass_message"),
        )
        total_content_rows = (
            limit * len(text_models)
            if limit is not None
            else sum(_count_content_rows(session, model) for model, _, _ in text_models)
        )
        if progress_callback:
            progress_callback("preparing", 0, total_content_rows)
        if include_legacy_links:
            _backfill_linked_users(
                session,
                batch_size=batch_size,
                apply=apply,
                stats=stats,
                include_preview_context=include_preview_context,
            )
        if not apply:
            session.rollback()

    progress_lock = Lock()
    scanned_by_type: dict[str, int] = {}

    def run_text_model(spec: tuple[Any, str, str]) -> MentionBackfillStats:
        model, field, content_type = spec
        model_stats = MentionBackfillStats(site=site)

        def report(phase: str, scanned: int, total: int) -> None:
            if progress_callback is None:
                return
            with progress_lock:
                scanned_by_type[phase] = scanned
                progress_callback(phase, sum(scanned_by_type.values()), total)

        with manager.get_session() as worker_session:
            _backfill_text_model(
                worker_session,
                model=model,
                parent_field=field,
                content_type=content_type,
                archive_site=site,
                batch_size=batch_size,
                limit=limit,
                apply=apply,
                stats=model_stats,
                total_content_rows=total_content_rows,
                progress_callback=report,
                include_preview_context=include_preview_context,
            )
            if not apply:
                worker_session.rollback()
        return model_stats

    max_workers = max(1, worker_count)
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="content-mentions") as executor:
        for model_stats in executor.map(run_text_model, text_models):
            _merge_stats(stats, model_stats)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", nargs="+", default=["onlyfans", "fansly", "loyalfans"])
    parser.add_argument("--batch-size", type=int, default=1_000)
    parser.add_argument("--limit", type=int, default=None, help="Per content type, per site")
    parser.add_argument("--apply", action="store_true", help="Write results; default is dry run")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.batch_size < 1 or args.limit is not None and args.limit < 1:
        parser.error("--batch-size and --limit must be positive")
    for site in _sites(args.sites):
        stats = backfill_site(site, batch_size=args.batch_size, limit=args.limit, apply=args.apply, worker_count=args.workers)
        print(
            f"{site}: linked {stats.linked_users_inserted}/{stats.linked_users_seen}, "
            f"text {stats.text_mentions_inserted} from {stats.handles_found} handles "
            f"({stats.handles_resolved} resolved) across {stats.content_rows_seen} rows"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
