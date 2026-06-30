from scripts import freshness as F
from scripts.config import Config, ScopeOverride
from scripts.freshness import Outdated, Selection, select

_O = [
    Outdated(name="lodash", current="4.17.20", wanted="4.17.21", latest="5.0.0"),
    Outdated(name="express", current="4.18.0", wanted="4.18.2", latest="4.18.2"),
    Outdated(name="@types/node", current="18.0.0", wanted="18.19.0", latest="20.1.0"),
]


class _FakeAdapter:
    SCOPE = "javascript"
    FILES_CHANGED = ("package.json", "package-lock.json")

    def __init__(self, outdated, raise_list=False, raise_apply=False):
        self._outdated = outdated
        self._raise_list = raise_list
        self._raise_apply = raise_apply
        self.applied = []

    def list_outdated(self, workdir):
        if self._raise_list:
            raise F.FreshnessError("boom")
        return self._outdated

    def apply(self, workdir, selections):
        if self._raise_apply:
            raise F.FreshnessError("apply failed")
        self.applied.append(list(selections))


def _cfg(**over):
    return Config(scopes={"javascript": ScopeOverride(update_freshness=True, **over)})


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


def test_run_opted_out_returns_empty(tmp_path):
    adapter = _FakeAdapter(_O)
    assert F.run(tmp_path, Config(), dry_run=True, adapter=adapter) == []


def test_run_grouped_one_plan(tmp_path):
    adapter = _FakeAdapter(_O)
    results = F.run(tmp_path, _cfg(), dry_run=True, adapter=adapter)
    assert len(results) == 1 and results[0].kind == "noop"


def test_run_per_dep_one_plan_each(tmp_path):
    adapter = _FakeAdapter(_O)
    results = F.run(tmp_path, _cfg(freshness_group="dependency"), dry_run=True, adapter=adapter)
    assert len(results) == 3 and all(r.kind == "noop" for r in results)


def test_run_list_failure_opens_issue(tmp_path):
    adapter = _FakeAdapter(_O, raise_list=True)
    results = F.run(tmp_path, _cfg(), dry_run=True, adapter=adapter)
    assert len(results) == 1 and results[0].key == "javascript-freshness"


def test_run_nothing_selected_returns_empty(tmp_path):
    adapter = _FakeAdapter([Outdated("x", "1.0.0", "1.0.0", "1.0.0")])
    assert F.run(tmp_path, _cfg(), dry_run=True, adapter=adapter) == []


def test_run_dependabot_note_in_body(tmp_path, monkeypatch):
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "dependabot.yml").write_text("version: 2\n")
    captured = {}

    def fake_apply_plan(plan, **kw):
        captured["body"] = plan.body
        from scripts.models import Result

        return Result(scope=plan.scope, key=plan.key, kind="noop", summary="")

    monkeypatch.setattr(F, "apply_plan", fake_apply_plan)
    F.run(tmp_path, _cfg(), dry_run=True, adapter=_FakeAdapter(_O))
    assert "dependabot" in captured["body"].lower()


def test_run_apply_failure_opens_issue(tmp_path, monkeypatch):
    def boom(plan, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(F, "apply_plan", boom)
    results = F.run(tmp_path, _cfg(), dry_run=True, adapter=_FakeAdapter(_O))
    assert len(results) == 1 and results[0].key == "javascript-freshness"


def test_run_grouped_single_selection_uses_scope_branch(tmp_path, monkeypatch):
    captured = {}

    def fake(plan, **kw):
        captured["key"] = plan.key
        captured["branch"] = plan.branch
        from scripts.models import Result

        return Result(scope=plan.scope, key=plan.key, kind="noop", summary="")

    monkeypatch.setattr(F, "apply_plan", fake)
    one = [Outdated("lodash", "4.17.20", "4.17.21", "5.0.0")]
    F.run(tmp_path, _cfg(), dry_run=True, adapter=_FakeAdapter(one))
    assert captured["key"] == "freshness"
    assert captured["branch"].endswith("/freshness")
