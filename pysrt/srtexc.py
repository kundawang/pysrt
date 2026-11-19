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


class InvalidTimecode(InvalidTimeString):
    """
    Raised when a SMPTE timecode is malformed or cannot be represented.

    This covers invalid frame numbers, wrong separators for the frame rate,
    out of range hours/minutes/seconds and negative times.
    """
    pass


class DroppedFrameCode(InvalidTimecode):
    """
    Raised when a timecode names a frame number skipped by drop-frame
    counting (``HH:MM:00;00`` and ``HH:MM:00;01`` for minutes that are not
    multiples of ten).
    """
    pass


class InvalidFrameRate(Error, ValueError):
    """
    Raised when a frame rate is not finite or not supported.

    Supported rates are 24, 25, 30 and 30000/1001 (29.97 drop-frame).
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
