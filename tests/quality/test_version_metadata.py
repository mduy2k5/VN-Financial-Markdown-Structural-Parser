from flat_parser import PARSER_VERSION, __version__

def test_parser_version_is_defined_once_and_matches_package_metadata():
    assert PARSER_VERSION == "0.6.0"
    assert __version__ == PARSER_VERSION
