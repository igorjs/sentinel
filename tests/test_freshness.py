from scripts.freshness import Outdated, Selection, select

_O = [
    Outdated(name="lodash", current="4.17.20", wanted="4.17.21", latest="5.0.0"),
    Outdated(name="express", current="4.18.0", wanted="4.18.2", latest="4.18.2"),
    Outdated(name="@types/node", current="18.0.0", wanted="18.19.0", latest="20.1.0"),
]


def test_select_in_range_default():
    sel = select(_O, level="range", include=[], exclude=[])
    assert sel == [
        Selection("@types/node", "18.0.0", "18.19.0", False),
        Selection("express", "4.18.0", "4.18.2", False),
        Selection("lodash", "4.17.20", "4.17.21", False),
    ]


def test_select_major_opt_in():
    sel = select(_O, level="major", include=[], exclude=[])
    by = {s.name: s for s in sel}
    assert by["lodash"].target == "5.0.0" and by["lodash"].is_major is True
    assert by["@types/node"].target == "20.1.0" and by["@types/node"].is_major is True
    assert by["express"].target == "4.18.2" and by["express"].is_major is False


def test_select_exclude_glob():
    sel = select(_O, level="range", include=[], exclude=["@types/*"])
    assert [s.name for s in sel] == ["express", "lodash"]


def test_select_include_only():
    sel = select(_O, level="range", include=["lodash"], exclude=[])
    assert [s.name for s in sel] == ["lodash"]


def test_select_exclude_wins_over_include():
    sel = select(_O, level="range", include=["lodash", "express"], exclude=["lodash"])
    assert [s.name for s in sel] == ["express"]


def test_select_drops_unchanged():
    o = [Outdated(name="stable", current="1.0.0", wanted="1.0.0", latest="1.0.0")]
    assert select(o, level="major", include=[], exclude=[]) == []
