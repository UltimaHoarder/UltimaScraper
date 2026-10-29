from __future__ import annotations


def test_all_content_text_search_excludes_non_searchable_stories(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    class FakeResult:
        def one(self) -> int:
            return 1

        def all(self) -> list[object]:
            return []

    class FakeSession:
        def exec(self, statement):
            captured_sql.append(
                str(statement.compile(compile_kwargs={"literal_binds": True}))
            )
            return FakeResult()

        def close(self) -> None:
            return None

    class FakeSiteDB:
        def get_session(self) -> FakeSession:
            return FakeSession()

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_all_content(
        site="onlyfans",
        content_type=None,
        user_id=None,
        exclude_user_ids=None,
        search="needle",
        sort_by="created_at",
        order="desc",
        include_flags=None,
        exclude_flags=None,
        page=1,
        page_size=30,
        include_total=True,
    )

    assert response.success is True
    assert response.total == 3

    assert response.total_is_exact is True
    count_sql = [sql for sql in captured_sql if "count(" in sql.lower()]
    assert len(count_sql) == 3
    assert all("UNION ALL" not in sql for sql in count_sql)
    assert any("x_posts.text" in sql for sql in count_sql)
    assert any("x_messages.text" in sql for sql in count_sql)
    assert any("x_mass_messages.text" in sql for sql in count_sql)
    search_sql = next(sql for sql in captured_sql if "UNION ALL" in sql)
    assert "x_posts.text" in search_sql
    assert "x_messages.text" in search_sql
    assert "x_mass_messages.text" in search_sql
    assert "x_stories" not in search_sql
    assert search_sql.count("%needle%") == 3
    # Each searchable content type is reduced to one page before UNION ALL,
    # preventing a global sort over every matching row.
    assert search_sql.count("LIMIT 31") >= 3


def test_all_content_media_filter_limits_each_union_branch(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    class FakeResult:
        def all(self) -> list[object]:
            return []

    class FakeSession:
        def exec(self, statement):
            captured_sql.append(
                str(statement.compile(compile_kwargs={"literal_binds": True}))
            )
            return FakeResult()

        def close(self) -> None:
            return None

    class FakeSiteDB:
        def get_session(self) -> FakeSession:
            return FakeSession()

    class FakeMultiDB:
        def get_or_create_manager(self, site: str) -> FakeSiteDB:
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_all_content(
        site="onlyfans",
        content_type=None,
        user_id=None,
        exclude_user_ids=None,
        search=None,
        sort_by="created_at",
        order="desc",
        include_flags="has_video",
        exclude_flags=None,
        page=2,
        page_size=30,
        include_total=False,
    )

    assert response.success is True
    page_sql = next(sql for sql in captured_sql if "UNION ALL" in sql)
    assert page_sql.count("LIMIT 61") >= 4
    assert "content_media_asso.post_id = x_posts.id" in page_sql
    assert "content_media_asso.story_id = x_stories.id" in page_sql
    assert "content_media_asso.message_id = x_messages.id" in page_sql
    assert "content_media_asso.mass_message_id = x_mass_messages.id" in page_sql
