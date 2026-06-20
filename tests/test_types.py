from scripts.types import Drift, Plan, Result


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
