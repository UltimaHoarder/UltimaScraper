from scripts.backfill_content_mentions import (
    _mention_kind_for_archive,
    extract_handles,
    extract_mentions,
)

def test_extract_handles_keeps_source_order_and_excludes_email_addresses() -> None:
    assert extract_handles("@Ashley, @ashley, and @Esmerelda; a@b.example") == [
        ("@Ashley", "ashley"),
        ("@Esmerelda", "esmerelda"),
    ]


def test_extract_mentions_accepts_profile_links_but_skips_the_known_action_route() -> None:
    assert extract_mentions(
        "https://onlyfans.com/kexample17 https://onlyfans.com/action/trial/token"
    ) == [
        ("https://onlyfans.com/kexample17", "kexample17", "profile_link"),
        (
            "https://onlyfans.com/action/trial/token",
            "https://onlyfans.com/action/trial/token",
            "excluded_application_route",
        ),
    ]


def test_extract_mentions_preserves_numeric_profile_link_ids() -> None:
    assert extract_mentions("https://onlyfans.com/487193598") == [
        ("https://onlyfans.com/487193598", "487193598", "profile_link")
    ]


def test_extract_mentions_uses_post_permalink_author_not_post_id() -> None:
    assert extract_mentions("https://onlyfans.com/15585607/onlyfans") == [
        ("https://onlyfans.com/15585607/onlyfans", "onlyfans", "post_link_author")
    ]


def test_extract_mentions_allows_platform_name_inside_a_real_username() -> None:
    assert extract_mentions(
        "https://onlyfans.com/877292389/onlyfans "
        "https://onlyfans.com/667544277/oexample21 "
        "https://onlyfans.com/201002118/aexample22"
    ) == [
        ("https://onlyfans.com/877292389/onlyfans", "onlyfans", "post_link_author"),
        (
            "https://onlyfans.com/667544277/oexample21",
            "oexample21",
            "post_link_author",
        ),
        (
            "https://onlyfans.com/201002118/aexample22",
            "aexample22",
            "post_link_author",
        ),
    ]


def test_extract_mentions_keeps_permalink_when_a_matching_handle_exists() -> None:
    assert extract_mentions(
        "@onlyfans https://onlyfans.com/877292389/onlyfans"
    ) == [
        ("@onlyfans", "onlyfans", "handle"),
        (
            "https://onlyfans.com/877292389/onlyfans",
            "onlyfans",
            "post_link_author",
        ),
    ]


def test_extract_mentions_splits_adjacent_post_permalinks() -> None:
    assert extract_mentions(
        "https://onlyfans.com/15585607/onlyfanshttps://onlyfans.com/308086813/lexample15"
    ) == [
        ("https://onlyfans.com/15585607/onlyfans", "onlyfans", "post_link_author"),
        ("https://onlyfans.com/308086813/lexample15", "lexample15", "post_link_author"),
    ]


def test_extract_mentions_recovers_post_permalink_from_damaged_url_runs() -> None:
    assert extract_mentions(
        "https://onlyfans.com/329540981/lexample15yfans.com/329540981/lexample15 "
        "https://onlyfans.com/227503782/kexample20227503782/kexample20"
    ) == [
        (
            "https://onlyfans.com/329540981/lexample15",
            "lexample15",
            "post_link_author",
        ),
        (
            "https://onlyfans.com/227503782/kexample20",
            "kexample20",
            "post_link_author",
        ),
    ]


def test_extract_mentions_uses_creator_from_campaign_permalink() -> None:
    assert extract_mentions("https://onlyfans.com/cexample19/c27") == [
        ("https://onlyfans.com/cexample19/c27", "cexample19", "profile_campaign_link")
    ]


def test_extract_mentions_uses_creator_from_profile_subroutes_and_numeric_post_links() -> None:
    assert extract_mentions(
        "https://onlyfans.com/mexample14/4027219 "
        "https://onlyfans.com/559683660/sexample16💗 "
        "https://onlyfans.com/eexample18/trial/token "
        "https://onlyfans.com/my/chats/chat/126991416/q=funvip"
    ) == [
        ("https://onlyfans.com/mexample14/4027219", "mexample14", "profile_child_link"),
        ("https://onlyfans.com/559683660/sexample16💗", "sexample16", "post_link_author"),
        ("https://onlyfans.com/eexample18/trial/token", "eexample18", "profile_trial_link"),
        (
            "https://onlyfans.com/my/chats/chat/126991416/q=funvip",
            "126991416",
            "chat_link_user_id",
        ),
    ]


def test_extract_mentions_uses_message_permalink_author_but_not_chat_routes() -> None:
    assert extract_mentions(
        "https://onlyfans.com/message/15585607/onlyfans "
        "https://onlyfans.com/my/chats/chat/126991416/q=funvip"
    ) == [
        (
            "https://onlyfans.com/message/15585607/onlyfans",
            "onlyfans",
            "message_link_author",
        ),
        (
            "https://onlyfans.com/my/chats/chat/126991416/q=funvip",
            "126991416",
            "chat_link_user_id",
        ),
    ]


def test_extract_mentions_allows_emoji_after_chat_user_id() -> None:
    raw = "https://onlyfans.com/my/chats/chat/4984954💦👆🏼"
    assert extract_mentions(raw) == [
        (raw, "4984954", "chat_link_user_id"),
    ]


def test_extract_mentions_leaves_ambiguous_numeric_application_routes_for_review() -> None:
    assert extract_mentions("https://onlyfans.com/123456/buyers") == [
        ("https://onlyfans.com/123456/buyers", "https://onlyfans.com/123456/buyers", "ambiguous_link")
    ]


def test_extract_mentions_marks_known_onlyfans_application_routes_excluded() -> None:
    assert extract_mentions(
        "https://onlyfans.com/my/chats/chat/126991416/q=funvip "
        "https://onlyfans.com/action/trial/token "
        "https://onlyfans.com/search/users/example"
    ) == [
        (
            "https://onlyfans.com/my/chats/chat/126991416/q=funvip",
            "126991416",
            "chat_link_user_id",
        ),
        (
            "https://onlyfans.com/action/trial/token",
            "https://onlyfans.com/action/trial/token",
            "excluded_application_route",
        ),
        (
            "https://onlyfans.com/search/users/example",
            "https://onlyfans.com/search/users/example",
            "excluded_application_route",
        ),
    ]


def test_extract_mentions_groups_excluded_routes_by_dynamic_token_shape() -> None:
    first = "https://onlyfans.com/action/trial/ynmxccnhnxenimiwa6wqdlugpt8bibdg"
    second = "https://onlyfans.com/action/trial/htsvbigu6katr3itvalwggdil0eh7dew"
    assert extract_mentions(f"{first} {second}") == [
        (first, "https://onlyfans.com/action/trial/:token", "excluded_application_route"),
        (second, "https://onlyfans.com/action/trial/:token", "excluded_application_route"),
    ]


def test_cross_platform_profile_links_do_not_resolve_in_the_current_archive() -> None:
    assert _mention_kind_for_archive(
        "https://fansly.com/karma", "profile_link", "onlyfans"
    ) == "cross_platform_profile_link"
