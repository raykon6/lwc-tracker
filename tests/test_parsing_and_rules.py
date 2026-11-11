from dataclasses import replace
from datetime import date

import pytest

from lwc_tracker.campaign import CampaignRules, normalize_title
from lwc_tracker.parser import ProfileParseError, parse_earned, parse_profile


def test_parses_name_badges_dates_and_points(profile_html):
    p = parse_profile(profile_html)
    assert p.display_name == "Test Learner"  # heading inside <main>, not the nav heading
    assert p.points == 1339
    assert p.league == "Silver League"
    titles = [b.title for b in p.badges]
    assert titles[0] == "The Basics of Google Cloud Compute"
    # Empty title falls back to the button's accessible label.
    assert titles[2] == "Explore Generative AI with the Vertex AI Gemini API"
    assert p.badges[0].earned == date(2026, 11, 1)
    assert len(p.badges) == 4


def test_unrelated_page_is_a_parse_error():
    with pytest.raises(ProfileParseError):
        parse_profile("<html><body><div>Sign in to continue</div></body></html>")


def test_profile_without_badges_is_not_an_error():
    p = parse_profile("<html><body><main><h1>New Learner</h1></main></body></html>")
    assert p.display_name == "New Learner" and p.badges == ()


def test_parse_earned_handles_padding_and_garbage():
    assert parse_earned("Earned Nov  3, 2026 EST") == date(2026, 11, 3)
    assert parse_earned("Earned Foo 99, 2026") is None
    assert parse_earned("") is None


def test_normalize_title_ignores_dashes_case_and_spacing():
    a = normalize_title("Store, Process, and Manage Data on Google Cloud – Console")
    b = normalize_title("store process and manage data on google cloud - console")
    assert a == b


def test_rules_match_aliases_and_ignore_unrelated_badges(settings, profile_html):
    rules = CampaignRules(settings.campaign)
    ev = rules.evaluate(parse_profile(profile_html))
    assert ev.counted == 3  # basics, store/process (en dash), renamed GenAI badge via alias
    assert len(ev.missing) == 7
    assert [b.title for b in ev.extra] == ["=cmd|' /C calc'!A0 Level 3: Generative AI"]


def test_campaign_window_excludes_early_badges(settings, profile_html):
    windowed = replace(settings.campaign, start_date=date(2026, 11, 1))
    ev = CampaignRules(windowed).evaluate(parse_profile(profile_html))
    assert ev.counted == 2
    assert len(ev.outside_window) == 2


def test_count_mode_counts_every_badge(settings, profile_html):
    open_rules = replace(settings.campaign, required_badges=(), required_count=4)
    ev = CampaignRules(open_rules).evaluate(parse_profile(profile_html))
    assert ev.counted == 4 and ev.missing == []
