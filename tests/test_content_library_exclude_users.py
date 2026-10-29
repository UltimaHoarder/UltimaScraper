from __future__ import annotations


def test_browse_all_content_supports_exclude_user_ids(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    class FakeResult:
        def one(self):
            return 0

        def all(self):
            return []

    class FakeSession:
        def exec(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            captured_sql.append(compiled)
            return FakeResult()

        def close(self):
            return None

    class FakeSiteDB:
        def get_session(self):
            return FakeSession()

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_all_content(
        site="onlyfans",
        content_type="post",
        user_id=None,
        exclude_user_ids="101,102,103",
        search=None,
        sort_by="created_at",
        order="desc",
        include_flags=None,
        exclude_flags=None,
        page=1,
        page_size=30,
    )

    assert response.success is True
    post_sql = next(sql for sql in captured_sql if "x_posts" in sql)
    assert "x_posts.user_id NOT IN (101, 102, 103)" in post_sql


def test_browse_all_content_without_exclude_user_ids_has_no_notin_clause(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    class FakeResult:
        def one(self):
            return 0

        def all(self):
            return []

    class FakeSession:
        def exec(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            captured_sql.append(compiled)
            return FakeResult()

        def close(self):
            return None

    class FakeSiteDB:
        def get_session(self):
            return FakeSession()

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_all_content(
        site="onlyfans",
        content_type="post",
        user_id=None,
        exclude_user_ids=None,
        search=None,
        sort_by="created_at",
        order="desc",
        include_flags=None,
        exclude_flags=None,
        page=1,
        page_size=30,
    )

    assert response.success is True
    post_sql = next(sql for sql in captured_sql if "x_posts" in sql)
    assert "NOT IN" not in post_sql


def test_browse_all_content_can_skip_recounting_subsequent_pages(monkeypatch) -> None:
    from ultima_scraper_backend.api.routes import database_browser

    captured_sql: list[str] = []

    class FakeResult:
        def all(self):
            return []

    class FakeSession:
        def exec(self, statement):
            captured_sql.append(
                str(statement.compile(compile_kwargs={"literal_binds": True}))
            )
            return FakeResult()

        def close(self):
            return None

    class FakeSiteDB:
        def get_session(self):
            return FakeSession()

    class FakeMultiDB:
        def get_or_create_manager(self, site: str):
            return FakeSiteDB()

    monkeypatch.setattr(database_browser, "MultiSiteDatabaseManager", FakeMultiDB)

    response = database_browser.browse_all_content(
        site="onlyfans",
        content_type="post",
        user_id=None,
        exclude_user_ids=None,
        search=None,
        sort_by="created_at",
        order="desc",
        include_flags=None,
        exclude_flags=None,
        page=2,
        page_size=30,
        include_total=False,
    )

    assert response.success is True
    assert response.total == 0
    assert response.has_more is False
    assert not any("count(" in sql.lower() for sql in captured_sql)
