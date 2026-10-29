from ultima_scraper_backend.helpers.age_verification import (
    normalize_age_verification_state,
)


def test_normalize_age_verification_marks_required_accounts_unverified() -> None:
    assert normalize_age_verification_state(None, True) == (False, True)


def test_normalize_age_verification_marks_verified_accounts_not_required() -> None:
    assert normalize_age_verification_state(True, None) == (True, False)


def test_normalize_age_verification_leaves_unknown_state_unchanged() -> None:
    assert normalize_age_verification_state(None, None) == (None, None)
