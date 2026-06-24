from pathlib import Path

from scripts.runtime import (
    read_engines_node,
    read_pin,
    read_requires_python,
    write_engines_node,
    write_pin,
    write_requires_python,
)


def test_requires_python_roundtrip(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.1"\nrequires-python = ">=3.8,<4.0"\n'
    )
    assert read_requires_python(tmp_path) == ">=3.8,<4.0"
    write_requires_python(tmp_path, ">=3.9,<4.0")
    assert read_requires_python(tmp_path) == ">=3.9,<4.0"
    # tomlkit preserves surrounding content
    assert 'name = "x"' in (tmp_path / "pyproject.toml").read_text()


def test_engines_node_minimal_diff(tmp_path: Path):
    original = '{\n  "name": "x",\n  "engines": {\n    "node": ">=18"\n  }\n}\n'
    (tmp_path / "package.json").write_text(original)
    assert read_engines_node(tmp_path) == ">=18"
    write_engines_node(tmp_path, ">=20")
    after = (tmp_path / "package.json").read_text()
    assert '"node": ">=20"' in after
    assert after == original.replace(">=18", ">=20")  # only the value changed


def test_engines_node_absent(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"name": "x"}')
    assert read_engines_node(tmp_path) is None


def test_pin_roundtrip(tmp_path: Path):
    (tmp_path / ".nvmrc").write_text("18\n")
    assert read_pin(".nvmrc")(tmp_path) == "18"
    write_pin(".nvmrc")(tmp_path, "20")
    assert (tmp_path / ".nvmrc").read_text() == "20\n"  # trailing newline preserved
