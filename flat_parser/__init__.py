from .pipeline import FlatParserPipeline
from .statement_locator import StatementLocator
from .version import PARSER_VERSION

__version__ = PARSER_VERSION
__all__ = ["FlatParserPipeline", "StatementLocator", "PARSER_VERSION"]
