"""Startup upgrades to head, so the archive graph must have one target."""
from pathlib import Path

from alembic.script import ScriptDirectory


def test_archive_migrations_have_one_head_and_join_both_branches():
    directory = (Path(__file__).resolve().parents[2] /
        "UltimaDatabases/UltimaScraperDBArchive/ultima_scraper_db_archive/migrations/alembic")
    scripts = ScriptDirectory(str(directory))
    head = scripts.get_current_head()
    assert head is not None
    ancestors = {revision.revision for revision in scripts.walk_revisions(head=head)}
    assert {"a6d901fe7823", "0614b9710fa1"} <= ancestors
    for current in ("a6d901fe7823", "0614b9710fa1", ("a6d901fe7823", "0614b9710fa1")):
        assert scripts._upgrade_revs("head", current)
