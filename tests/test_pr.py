from scripts.pr import branch_name


def test_branch_name_basic():
    assert branch_name("rust", "RUSTSEC-2024-1") == "sentinel/rust/rustsec-2024-1"


def test_branch_name_lowercases():
    assert branch_name("Rust", "Foo") == "sentinel/rust/foo"


def test_branch_name_replaces_unsafe_chars():
    assert branch_name("go", "GO 2024 / 12") == "sentinel/go/go-2024-12"


def test_branch_name_collapses_repeats():
    assert branch_name("go", "a//b") == "sentinel/go/a-b"
