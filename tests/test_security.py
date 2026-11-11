import pytest

from conftest import GOOD_ID
from lwc_tracker.security import (InvalidProfileURL, canonical_profile_url, clean_text, mask_email,
                                  parse_profile_url, safe_cell)


@pytest.mark.parametrize("url", [
    f"https://www.skills.google/public_profiles/{GOOD_ID}",
    f"https://www.skills.google/public_profiles/{GOOD_ID}/",
    f"https://skills.google/public_profiles/{GOOD_ID}",
    f"https://www.cloudskillsboost.google/public_profiles/{GOOD_ID}",
    f"http://www.skills.google/public_profiles/{GOOD_ID}",
    f"www.skills.google/public_profiles/{GOOD_ID}",
    f"  https://WWW.SKILLS.GOOGLE/public_profiles/{GOOD_ID.upper()}  ",
    f"https://www.skills.google/public_profiles/{GOOD_ID}?locale=en#badges",
    f"https://www.skills.google:443/public_profiles/{GOOD_ID}",
])
def test_accepts_public_profile_links(url):
    assert parse_profile_url(url) == GOOD_ID


@pytest.mark.parametrize("url", [
    "",
    "   ",
    None,
    f"https://evil.example/public_profiles/{GOOD_ID}",
    f"https://www.skills.google.evil.example/public_profiles/{GOOD_ID}",
    f"https://www.skills.google@evil.example/public_profiles/{GOOD_ID}",
    f"https://user:pass@www.skills.google/public_profiles/{GOOD_ID}",
    f"https://evil.example\\@www.skills.google/public_profiles/{GOOD_ID}",
    f"https://www.skills.google:8080/public_profiles/{GOOD_ID}",
    f"https://www.skills.google/public_profiles/../admin/{GOOD_ID}",
    f"https://www.skills.google/public_profiles/{GOOD_ID}/badges/123",
    "https://www.skills.google/public_profiles/not-a-uuid-at-all-but-36-characters!",
    f"javascript:alert(1)//www.skills.google/public_profiles/{GOOD_ID}",
    f"file:///etc/passwd?/public_profiles/{GOOD_ID}",
    f"https://www.skills.google/public_profiles/{GOOD_ID}​",
    f"https://www.skills.google/public_profiles/{GOOD_ID}\r\nHost: evil",
    "https://www.skills.google/public_profiles/" + "a" * 400,
    f"https://127.0.0.1/public_profiles/{GOOD_ID}",
    f"https://169.254.169.254/public_profiles/{GOOD_ID}",
])
def test_rejects_everything_else(url):
    with pytest.raises(InvalidProfileURL):
        parse_profile_url(url)


def test_canonical_url_refuses_unvalidated_ids():
    assert canonical_profile_url(GOOD_ID).endswith(GOOD_ID)
    for bad in ["../../etc", "x", GOOD_ID + "/../", "", None]:
        with pytest.raises(InvalidProfileURL):
            canonical_profile_url(bad)


@pytest.mark.parametrize("value,expected", [
    ("=SUM(A1)", "'=SUM(A1)"),
    ("+1", "'+1"),
    ("-2", "'-2"),
    ("@cmd", "'@cmd"),
    ("\tx", "'\tx"),
    ("Asha Rao", "Asha Rao"),
    (10, 10),
])
def test_safe_cell_blocks_formula_injection(value, expected):
    assert safe_cell(value) == expected


def test_clean_text_strips_controls_and_bidi_overrides():
    assert clean_text("Asha‮oaR\x00  Rao", 50) == "Asha oaR Rao"
    assert len(clean_text("x" * 500, 20)) == 20


def test_mask_email():
    assert mask_email("asha.rao@example.edu") == "a***@example.edu"
    assert mask_email("") == "-"
