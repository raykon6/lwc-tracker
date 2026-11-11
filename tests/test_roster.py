import pytest

from conftest import GOOD_ID
from lwc_tracker.roster import RosterError, load_roster, roster_from_lines

URL = f"https://www.skills.google/public_profiles/{GOOD_ID}"


def test_detects_columns_by_content_not_position():
    data = f"Roll No;Student Name;E-mail Address;Link to Skills profile\n1;Asha Rao;asha@x.edu;{URL}\n".encode()
    r = load_roster(data, 10_000, 10)
    assert r.columns == {"url": "Link to Skills profile", "name": "Student Name", "email": "E-mail Address"}
    assert r.rows[0].name == "Asha Rao" and r.rows[0].profile_id == GOOD_ID


def test_headerless_file_and_bom():
    data = ("﻿" + f"Asha Rao,{URL}\n").encode("utf-8")
    r = load_roster(data, 10_000, 10)
    assert r.rows[0].profile_id == GOOD_ID and r.warnings


def test_duplicates_and_invalid_rows_are_reported():
    data = f"name,url\nA,{URL}\nB,{URL}\nC,https://evil.example/x\n\n".encode()
    s = load_roster(data, 10_000, 10).summary()
    assert s == {**s, "total": 3, "valid": 2, "invalid": 1, "duplicates": 1, "unique_profiles": 1}


@pytest.mark.parametrize("data,msg", [
    (b"", "empty"),
    (b"\x00\x01\x02binary", "binary"),
    (b"name,email\nA,a@x\n", "No column"),
    (b"x" * 20_000, "larger"),
])
def test_rejects_unusable_files(data, msg):
    with pytest.raises(RosterError, match=msg):
        load_roster(data, 10_000, 10)


def test_row_limit():
    data = ("url\n" + f"{URL}\n" * 11).encode()
    with pytest.raises(RosterError, match="limit"):
        load_roster(data, 100_000, 10)


def test_pasted_lines():
    r = roster_from_lines(f"Asha Rao, {URL}\n\n{URL}\n", 10_000, 10)
    assert [x.name for x in r.rows] == ["Asha Rao", ""]
