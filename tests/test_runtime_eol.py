from scripts.runtime_eol import bump_floor, bump_pin, floor_lower_cycle, pin_cycle


def test_floor_lower_cycle_python():
    assert floor_lower_cycle(">=3.8", parts=2) == "3.8"
    assert floor_lower_cycle(">=3.8,<4.0", parts=2) == "3.8"
    assert floor_lower_cycle(">=3.8.1", parts=2) == "3.8"


def test_floor_lower_cycle_node():
    assert floor_lower_cycle(">=18", parts=1) == "18"
    assert floor_lower_cycle(">=18.0.0", parts=1) == "18"


def test_floor_lower_cycle_unparseable():
    assert floor_lower_cycle("^18 || ^20", parts=1) is None
    assert floor_lower_cycle("18.x", parts=1) is None
    assert floor_lower_cycle("", parts=2) is None


def test_bump_floor_preserves_upper_bound():
    assert bump_floor(">=3.8,<4.0", "3.9") == ">=3.9,<4.0"
    assert bump_floor(">=18", "20") == ">=20"
    assert bump_floor(">= 3.8", "3.9") == ">= 3.9"


def test_pin_cycle():
    assert pin_cycle("3.8.10", parts=2) == "3.8"
    assert pin_cycle("3.8", parts=2) == "3.8"
    assert pin_cycle("v18", parts=1) == "18"
    assert pin_cycle("18.16.0", parts=1) == "18"
    assert pin_cycle("lts/iron", parts=1) is None


def test_bump_pin_matches_granularity():
    # python cycle granularity = 2 components
    assert bump_pin("3.8", "3.9", "3.9.18", parts=2) == "3.9"
    assert bump_pin("3.8.10", "3.9", "3.9.18", parts=2) == "3.9.18"
    # node cycle granularity = 1 component
    assert bump_pin("18", "20", "20.11.1", parts=1) == "20"
    assert bump_pin("18.16.0", "20", "20.11.1", parts=1) == "20.11.1"
    assert bump_pin("v18", "20", "20.11.1", parts=1) == "v20"
    assert bump_pin("v18.16.0", "20", "20.11.1", parts=1) == "v20.11.1"
