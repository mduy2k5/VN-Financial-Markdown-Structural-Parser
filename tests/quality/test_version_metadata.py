from pathlib import Path

from flat_parser import PARSER_VERSION, __version__


ROOT = Path(__file__).resolve().parents[2]


def test_parser_version_is_defined_once_and_matches_package_metadata():
    assert PARSER_VERSION == "0.6.0"
    assert __version__ == PARSER_VERSION


def test_release_version_file_has_current_release_and_description():
    lines = (ROOT / "VERSION.txt").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "v23.2.0-source-first-recovery"
    assert lines[1]
