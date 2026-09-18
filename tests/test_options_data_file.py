from pathlib import Path

import click
import pytest

from satori_cli.utils.options import _input_callback, apply_data_files, apply_splits


def test_input_callback_preserves_empty_string():
    result = _input_callback(None, "input", ("INPUT=",))

    assert result == {"INPUT": [""]}


def test_input_callback_non_empty_value():
    result = _input_callback(None, "input", ("INPUT=Hola",))

    assert result == {"INPUT": ["Hola"]}


def test_input_callback_splits_multiline_values():
    result = _input_callback(None, "input", ("KEY=a\nb\nc",))

    assert result == {"KEY": ["a", "b", "c"]}


def test_apply_data_files_into_empty_parameters(tmp_path: Path):
    path = tmp_path / "values.txt"
    path.write_text("a\nb\nc\n", encoding="utf-8")

    result = apply_data_files(None, (f"KEY={path}",))

    assert result == {"KEY": ["a", "b", "c"]}


def test_apply_data_files_merges_existing_parameters(tmp_path: Path):
    path = tmp_path / "values.txt"
    path.write_text("two\nthree\n", encoding="utf-8")

    result = apply_data_files({"KEY": ["one"]}, (f"KEY={path}",))

    assert result == {"KEY": ["one", "two", "three"]}


def test_apply_data_files_skips_blank_lines(tmp_path: Path):
    path = tmp_path / "values.txt"
    path.write_text("a\n\n\nb\n", encoding="utf-8")

    result = apply_data_files(None, (f"OUT={path}",))

    assert result == {"OUT": ["a", "b"]}


def test_apply_data_files_missing_equals_raises():
    with pytest.raises(click.BadParameter, match="expected KEY=PATH"):
        apply_data_files(None, ("badvalue",))


def test_apply_data_files_missing_file_raises(tmp_path: Path):
    missing = tmp_path / "missing.txt"

    with pytest.raises(click.BadParameter, match="file not found"):
        apply_data_files(None, (f"KEY={missing}",))


def test_apply_order_splits_then_data_files(tmp_path: Path):
    path = tmp_path / "values.txt"
    path.write_text("x,y\nz\n", encoding="utf-8")

    parameters = apply_splits({"KEY": ["a,b"]}, {"KEY": ","})
    result = apply_data_files(parameters, (f"KEY={path}",))

    assert result == {"KEY": ["a", "b", "x,y", "z"]}
