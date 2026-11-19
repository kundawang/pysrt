"""
Exception classes
"""


class Error(Exception):
    """
    Pysrt's base exception
    """
    pass


class InvalidTimeString(Error):
    """
    Raised when parser fail on bad formatted time strings
    """
    pass


class InvalidItem(Error):
    """
    Raised when parser fail to parse a sub title item
    """
    pass


class InvalidIndex(InvalidItem):
    """
    Raised when parser fail to parse a sub title index
    """
    pass


class InvalidMarkup(Error):
    """
    Raised (in strict mode only) when inline tags such as <i>, <b>, <u> or
    <font> are malformed: cross closing, stray closing, unclosed tag, bad
    color value or unparseable attribute.

    The ``errors`` attribute holds the full list of problems, each one
    carrying ``position`` (offset in the raw text) and ``tag`` (raw tag).
    """
    def __init__(self, *args, **kwargs):
        Error.__init__(self, *args)
        self.errors = kwargs.get('errors', [])
