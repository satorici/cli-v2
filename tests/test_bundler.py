from io import BytesIO
from zipfile import ZipFile

from satori_cli.utils.bundler import make_bundle


def test_make_bundle_follows_nested_file_imports(tmp_path):
    (tmp_path / "ci").mkdir()
    (tmp_path / ".satori.yml").write_text(
        "import:\n  - satori://code/x.yml\n  - file://.satori-llm.yml\n"
    )
    (tmp_path / ".satori-llm.yml").write_text("import:\n  - file://ci/nested.yml\n")
    (tmp_path / "ci/nested.yml").write_text(
        "test:\n  host:\n    - - file: file://ci/hosts.txt\n  cmd:\n    - echo ${{host}}\n"
    )
    (tmp_path / "ci/hosts.txt").write_text("a\n")

    with ZipFile(BytesIO(make_bundle(tmp_path / ".satori.yml"))) as zf:
        assert sorted(zf.namelist()) == [
            ".satori-llm.yml",
            ".satori.yml",
            "ci/hosts.txt",
            "ci/nested.yml",
        ]


def test_make_bundle_handles_import_cycles(tmp_path):
    (tmp_path / ".satori.yml").write_text("import: [file://a.yml]\n")
    (tmp_path / "a.yml").write_text("import: [file://b.yml]\n")
    (tmp_path / "b.yml").write_text("import: [file://a.yml]\n")

    with ZipFile(BytesIO(make_bundle(tmp_path / ".satori.yml"))) as zf:
        assert sorted(zf.namelist()) == [".satori.yml", "a.yml", "b.yml"]
