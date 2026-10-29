from __future__ import annotations

from inspect import getsource

import pytest

from ultima_scraper_backend.api.routes.database_browser import (
    ArchiveMetricItem,
    ArchivePurchaseFact,
    _archive_completeness,
    _archive_purchase_page_state,
    _parse_archive_metrics_cursor,
    archive_metrics,
    archive_purchase_facts,
)


def test_archive_metrics_cursor_is_stable_and_site_scoped() -> None:
    assert _parse_archive_metrics_cursor(None, None) == ("onlyfans", 0)
    assert _parse_archive_metrics_cursor(None, "fansly:987") == ("fansly", 987)
    assert _parse_archive_metrics_cursor("onlyfans", "onlyfans:42") == (
        "onlyfans",
        42,
    )
    with pytest.raises(ValueError):
        _parse_archive_metrics_cursor("onlyfans", "fansly:42")
    with pytest.raises(ValueError):
        _parse_archive_metrics_cursor(None, "onlyfans:not-a-number")


def test_archive_metrics_source_is_scoped_to_performers() -> None:
    source = getsource(archive_metrics)
    assert "UserModel.performer.is_(True)" in source
    assert "downloaded_at = user.downloaded_at" in source
    assert "downloaded_at.isoformat()" in source
    assert "if downloaded_only" in source
    assert "UserModel.downloaded_at.is_not(None)" in source
    assert "UserInfoModel.downloaded_at.is_not(None)" in source
    assert "card_media_by_user" in source
    assert "FilePathModel.downloaded.is_(True)" in source
    assert "Path(str(filepath)).is_file()" in source
    assert "card_media_id=card_media_by_user.get(user.id)" in source
    assert "price or 0" not in source
    assert "purchase_fact_limit + 1" in source
    assert "purchase_facts_next_cursor" in source
    assert "post_counts.get(user.id, [0, 0])[1]" in source


def test_purchase_heavy_performers_have_a_generic_fact_cursor() -> None:
    source = getsource(archive_purchase_facts)
    assert "BoughtContentModel.id > cursor" in source
    assert ".limit(limit + 1)" in source
    assert "ArchivePurchaseFactsResponse" in source


def test_incomplete_purchase_fact_page_recovers_cursor_from_last_fact() -> None:
    facts = [
        ArchivePurchaseFact(
            external_id="onlyfans:bought_content:149262",
            acquisition_type="ppv",
            value_status="unknown",
        )
    ]

    assert _archive_purchase_page_state(
        "onlyfans",
        facts,
        complete=False,
        next_cursor=None,
    ) == (False, 149262)


def test_archive_completeness_distinguishes_unknown_absent_partial_and_complete() -> (
    None
):
    assert _archive_completeness(None, 0) == {"status": "unknown", "ratio": None}
    assert _archive_completeness(0, 0) == {"status": "complete", "ratio": 1.0}
    assert _archive_completeness(10, 4) == {"status": "partial", "ratio": 0.4}
    assert _archive_completeness(10, 12) == {"status": "complete", "ratio": 1.0}


def test_archive_metric_contract_preserves_unknown_money_and_ppv_classification() -> (
    None
):
    item = ArchiveMetricItem(
        site="onlyfans",
        user_id=7,
        available=True,
        downloaded_at="2026-08-23T12:34:56+00:00",
        card_media_id=1234,
        current_subscription_price_usd=None,
        feed_post_count=12,
        ppv_post_count=2,
        ppv_message_count=3,
        source_media_count=None,
        downloaded_media_count=0,
        source_bytes=None,
        downloaded_bytes=0,
        media_types={},
        completeness={"status": "unknown", "ratio": None},
        purchase_facts=[
            ArchivePurchaseFact(
                external_id="onlyfans:bought_content:9",
                acquisition_type="ppv",
                amount_usd=None,
                value_status="unknown",
                content_type="message",
                content_id=88,
            )
        ],
        purchase_facts_complete=True,
        purchase_facts_next_cursor=None,
    )
    payload = item.model_dump()
    assert payload["downloaded_at"] == "2026-08-23T12:34:56+00:00"
    assert payload["card_media_id"] == 1234
    assert payload["current_subscription_price_usd"] is None
    assert payload["ppv_post_count"] == 2
    assert payload["ppv_message_count"] == 3
    assert payload["purchase_facts"][0]["amount_usd"] is None
