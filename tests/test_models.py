from scripts.models import Drift, Plan, Result


def test_drift_is_hashable():
    d = Drift(
        scope="rust",
        key="RUSTSEC-2024-1",
        summary="x",
        fixed_versions=["1.2"],
        current="1.1",
        raw={},
    )
    assert hash(d)


def test_plan_default_post_steps_empty():
    p = Plan(
        scope="rust", key="k", branch="b", title="t", body="bd", files_changed=["f"], commands=[]
    )
    assert p.post_steps == ()


def test_result_kind_constrained():
    r = Result(scope="rust", key="k", kind="pr", summary="x")
    assert r.kind == "pr"


def test_drift_defaults_severity_unknown():
    from scripts.models import Drift

    d = Drift(scope="rust", key="K", summary="s", fixed_versions=["1.0.0"], current="0.9.0")
    assert d.severity == "unknown"


def test_drift_severity_settable_and_not_in_hash():
    from scripts.models import Drift

    a = Drift(scope="rust", key="K", summary="s", fixed_versions=[], current="", severity="high")
    b = Drift(scope="rust", key="K", summary="s", fixed_versions=[], current="", severity="low")
    assert a.severity == "high"
    assert hash(a) == hash(b)  # severity must not affect identity
