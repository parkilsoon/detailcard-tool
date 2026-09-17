import pytest

from app.paths import iter_strings, path_get, path_set


def sample():
    return {"header": {"ingredient": "A", "badges": [{"text": "x"}, {"text": "y"}]},
            "sections": [{"rows": [{"label": "l", "value": "v"}]}]}


def test_get_nested():
    d = sample()
    assert path_get(d, "header.ingredient") == "A"
    assert path_get(d, "header.badges.1.text") == "y"
    assert path_get(d, "sections.0.rows.0.value") == "v"


def test_get_missing():
    with pytest.raises(KeyError):
        path_get(sample(), "sections.3.rows.0.value")
    assert path_get(sample(), "nope", default=None) is None


def test_set_existing():
    d = sample()
    path_set(d, "sections.0.rows.0.value", "changed")
    assert d["sections"][0]["rows"][0]["value"] == "changed"
    path_set(d, "header.badges.0.text", "z")
    assert d["header"]["badges"][0]["text"] == "z"


def test_set_does_not_create():
    d = sample()
    with pytest.raises(KeyError):
        path_set(d, "header.new_key", 1)
    with pytest.raises(KeyError):
        path_set(d, "header.badges.5.text", 1)


def test_iter_strings():
    got = dict(iter_strings(sample()))
    assert got["header.ingredient"] == "A"
    assert got["sections.0.rows.0.label"] == "l"
    assert len(got) == 5
