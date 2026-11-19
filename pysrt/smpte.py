# -*- coding: utf-8 -*-
"""
SMPTE timecode support: HH:MM:SS:FF (non drop-frame) and HH:MM:SS;FF
(drop-frame).

Supported frame rates are 24, 25, 30 and 30000/1001 (29.97 drop-frame).
The conversions between :class:`~pysrt.srttime.SubRipTime` and timecodes
live on ``SubRipTime`` and are backed by :class:`FrameRate`.

Rounding rules
--------------

Both directions round to the nearest unit and resolve exact ties upwards
(toward the later frame / millisecond):

* ``SubRipTime`` -> timecode: the millisecond timestamp is rounded to the
  nearest frame. A timestamp exactly halfway between two frames selects the
  later one. Consequently a millisecond value that does not fall exactly on
  a frame is silently snapped to the closest frame; it is neither truncated
  nor rejected.
* timecode -> ``SubRipTime``: the frame number is converted to milliseconds
  and rounded to the nearest millisecond, ties upwards. ``SubRipTime`` only
  has millisecond precision, so sub-millisecond exactness cannot be kept.

Because each endpoint rounds on its own, a cue whose start and end are not
frame aligned can change duration by one frame on the first export/import
pass. ``to_timecodes`` output is a fixed point, though: importing an exported
``(start, end)`` pair stores frame-aligned values, so a second export
reproduces exactly the same codes and frame durations.

``HH:MM:SS:FF`` is a 24 hour cyclic format. ``pysrt`` refuses to wrap
silently: exporting a time at or after the 24 hour limit raises
:class:`~pysrt.srtexc.InvalidTimecode` unless ``wrap=True`` is passed, in
which case the time of day is taken modulo 24 hours of wall-clock time.
Wrapping is done on the millisecond timestamp rather than on the frame
number, so ``24:00:00,000`` becomes ``00:00:00:00`` at every supported rate,
including drop-frame. A drop-frame 24 hour *timecode day* is 107892 * 24
frames, which is slightly shorter than 24 hours of wall time; the last few
tens of milliseconds of the day therefore round past the final code. With
``wrap=True`` they clamp to ``23:59:59;29`` instead of wrapping to zero.
SRT files may legitimately contain times beyond 24 hours, so a silent wrap
would corrupt them.
"""
import math
import re
from fractions import Fraction

from pysrt.srtexc import (DroppedFrameCode, InvalidFrameRate,
                          InvalidTimecode)

try:
    text_type = unicode  # Python 2
except NameError:
    text_type = str

try:
    integer_types = (int, long)  # Python 2
except NameError:
    integer_types = (int, )

DROP_FRAME_RATE = Fraction(30000, 1001)
SUPPORTED_INTEGER_RATES = (24, 25, 30)

#: ``HH:MM:SS:FF`` (non drop-frame) or ``HH:MM:SS;FF`` (drop-frame).
#: Exactly two digits per field; anything else is malformed.
RE_TIMECODE = re.compile(r'^(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})$')
#: ``24``, ``25.0``, ``30000/1001`` and similar.
RE_FRAME_RATE = re.compile(
    r'^\s*(\d+(?:\.\d+)?)(?:\s*/\s*(\d+))?\s*$')

#: Frames skipped at the start of every drop-frame minute.
DROP_FRAMES_PER_MINUTE = 2
#: Frames in a ten minute block: 10 * 60 * 30 - 9 * 2.
FRAMES_PER_TEN_MINUTES = 17982
#: Frames in a drop-frame hour: 6 * FRAMES_PER_TEN_MINUTES.
FRAMES_PER_DROP_FRAME_HOUR = 107892
#: Frames in a drop-frame day.
FRAMES_PER_DROP_FRAME_DAY = FRAMES_PER_DROP_FRAME_HOUR * 24

SECONDS_PER_DAY = 24 * 60 * 60


def round_half_up(value):
    """
    Round a Fraction/int to the nearest integer, resolving ties upwards.

    Works for negative values too (ties toward positive infinity) but
    conversions reject negative values before calling it.
    """
    value = Fraction(value)
    return (2 * value.numerator + value.denominator) // \
        (2 * value.denominator)


def _parse_rate(rate):
    """
    Normalize a frame rate to ``(numerator, denominator)``.

    Accepted forms: 24, 25, 30, 30000/1001 (as a string, Fraction or
    float), and the decimal approximations 29.97 / 29.97002997.
    """
    if isinstance(rate, FrameRate):
        return rate.numerator, rate.denominator

    if isinstance(rate, bool):
        raise InvalidFrameRate('Unsupported frame rate: %r' % (rate, ))

    if isinstance(rate, text_type):
        match = RE_FRAME_RATE.match(rate)
        if not match:
            raise InvalidFrameRate('Unsupported frame rate: %r' % (rate, ))
        try:
            if match.group(2):
                numerator = Fraction(match.group(1))
                denominator = int(match.group(2))
                if denominator == 0:
                    raise InvalidFrameRate('Frame rate must not be zero')
                return _parse_rate(numerator / denominator)
            return _parse_rate(float(match.group(1)))
        except (ValueError, ZeroDivisionError):
            raise InvalidFrameRate('Unsupported frame rate: %r' % (rate, ))

    if isinstance(rate, integer_types):
        if rate in SUPPORTED_INTEGER_RATES:
            return rate, 1
        raise InvalidFrameRate(
            'Unsupported frame rate: %r (supported: 24, 25, 30, 30000/1001)'
            % (rate, ))

    if isinstance(rate, Fraction):
        if rate == 0:
            raise InvalidFrameRate('Frame rate must not be zero')
        if rate == DROP_FRAME_RATE:
            return rate.numerator, rate.denominator
        if rate.denominator == 1 and rate.numerator in SUPPORTED_INTEGER_RATES:
            return rate.numerator, rate.denominator
        # The float form of a supported rate (e.g. Fraction(29.97) built
        # from a float literal) goes through the same approximation check.
        try:
            as_float = float(rate)
        except (OverflowError, ValueError):
            raise InvalidFrameRate('Unsupported frame rate: %s' % rate)
        return _parse_rate(as_float)

    if isinstance(rate, float):
        if math.isnan(rate) or math.isinf(rate):
            raise InvalidFrameRate(
                'Frame rate must be finite, got %r' % (rate, ))
        if rate in (24.0, 25.0, 30.0):
            return int(rate), 1
        # 30000 / 1001 is 29.97002997..., 29.97 is its usual short form.
        # Both are accepted and normalized to the exact rational value.
        if abs(rate - float(DROP_FRAME_RATE)) <= 1e-4:
            return DROP_FRAME_RATE.numerator, DROP_FRAME_RATE.denominator
        raise InvalidFrameRate(
            'Unsupported frame rate: %r (supported: 24, 25, 30, 30000/1001)'
            % (rate, ))

    raise InvalidFrameRate('Unsupported frame rate: %r' % (rate, ))


class FrameRate(object):
    """
    A SMPTE frame rate.

    FrameRate(rate[, drop_frame])

    ``rate`` may be 24, 25, 30, 30000/1001 (string, Fraction or float) or
    one of the common 29.97 spellings. 30000/1001 is a drop-frame rate;
    passing ``drop_frame=False`` for it raises
    :class:`~pysrt.srtexc.InvalidFrameRate`. Integer rates are non
    drop-frame and ``drop_frame=True`` for them raises as well.

    >>> FrameRate(25).timecode_separator
    ':'
    >>> FrameRate('30000/1001').timecode_separator
    ';'
    """
    def __init__(self, rate, drop_frame=None):
        numerator, denominator = _parse_rate(rate)
        is_drop_frame_rate = Fraction(numerator, denominator) == DROP_FRAME_RATE

        if is_drop_frame_rate:
            if drop_frame is False:
                raise InvalidFrameRate(
                    '30000/1001 fps is only supported with drop-frame '
                    'counting')
            drop_frame = True
        else:
            if drop_frame:
                raise InvalidFrameRate(
                    'Drop-frame counting is only supported at 30000/1001 '
                    'fps, not at %s fps' % (numerator // denominator))
            drop_frame = False

        self.numerator = numerator
        self.denominator = denominator
        self.drop_frame = drop_frame

    @property
    def fps(self):
        """The exact rate as a Fraction of frames per second."""
        return Fraction(self.numerator, self.denominator)

    @property
    def nominal_fps(self):
        """The integer rate used for timecode fields (30 for 29.97 DF)."""
        if self.drop_frame:
            return 30
        return self.numerator // self.denominator

    @property
    def timecode_separator(self):
        """``';'`` for drop-frame, ``':'`` otherwise."""
        return ';' if self.drop_frame else ':'

    @property
    def frames_per_24_hours(self):
        """Number of frames a 24 hour timecode can hold."""
        if self.drop_frame:
            return FRAMES_PER_DROP_FRAME_DAY
        return SECONDS_PER_DAY * self.nominal_fps

    def __repr__(self):
        if self.drop_frame:
            return 'FrameRate(30000/1001)'
        return 'FrameRate(%d)' % self.nominal_fps

    def __eq__(self, other):
        try:
            other = FrameRate.coerce(other)
        except InvalidFrameRate:
            return NotImplemented
        return (self.numerator, self.denominator, self.drop_frame) == \
            (other.numerator, other.denominator, other.drop_frame)

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __hash__(self):
        return hash((self.numerator, self.denominator, self.drop_frame))

    @classmethod
    def coerce(cls, rate):
        """Return ``rate`` if it already is a FrameRate, else build one."""
        if isinstance(rate, cls):
            return rate
        return cls(rate)

    # -- millisecond <-> frame number -------------------------------------

    def ordinal_to_frames(self, ordinal):
        """
        Milliseconds -> frame number, rounded to the nearest frame.

        A time exactly halfway between two frames rounds up (later frame).
        """
        if ordinal < 0:
            raise InvalidTimecode(
                'Negative time (%d ms) has no SMPTE representation'
                % ordinal)
        return round_half_up(Fraction(ordinal) * self.fps / 1000)

    def frames_to_ordinal(self, frame_number):
        """
        Frame number -> milliseconds, rounded to the nearest millisecond.

        A value exactly halfway between two milliseconds rounds up.
        """
        if frame_number < 0:
            raise InvalidTimecode(
                'Negative frame number (%r) is invalid' % (frame_number, ))
        return round_half_up(Fraction(frame_number) * 1000 / self.fps)

    # -- frame number <-> timecode ----------------------------------------

    def frames_to_timecode(self, frame_number):
        """
        Frame number -> ``HH:MM:SS:FF`` / ``HH:MM:SS;FF`` string.

        Raises InvalidTimecode for a negative frame number or one outside
        the 24 hour range. Use ``frame_number % frames_per_24_hours`` to
        wrap explicitly.
        """
        if frame_number < 0:
            raise InvalidTimecode(
                'Negative frame number (%r) is invalid' % (frame_number, ))
        if frame_number >= self.frames_per_24_hours:
            raise InvalidTimecode(
                'Frame number %d is outside the 24 hour timecode range '
                '(%d..%d)' % (frame_number, 0, self.frames_per_24_hours - 1))

        hours, minutes, seconds, frames = self.frame_number_to_fields(
            frame_number)
        return '%02d:%02d:%02d%s%02d' % (hours, minutes, seconds,
                                         self.timecode_separator, frames)

    def timecode_to_frames(self, timecode):
        """
        ``HH:MM:SS:FF`` / ``HH:MM:SS;FF`` string -> frame number.

        Raises InvalidTimecode for malformed strings, out of range fields,
        frame numbers >= the nominal rate, a separator that does not match
        the frame rate, or hours >= 24. Drop-frame codes naming a skipped
        frame raise DroppedFrameCode.
        """
        if not isinstance(timecode, text_type):
            raise InvalidTimecode('Timecode must be a string, got %r'
                                  % (timecode, ))
        match = RE_TIMECODE.match(timecode)
        if not match:
            raise InvalidTimecode('Malformed timecode: %r' % (timecode, ))

        groups = match.groups()
        hours, minutes, seconds, frames = (int(groups[index])
                                           for index in (0, 1, 2, 4))
        separator = groups[3]

        if separator != self.timecode_separator:
            if self.drop_frame:
                raise InvalidTimecode(
                    'Drop-frame timecodes must use ";" before frames: %r'
                    % (timecode, ))
            raise InvalidTimecode(
                'Non drop-frame timecodes must use ":" before frames: %r'
                % (timecode, ))

        if hours >= 24:
            raise InvalidTimecode(
                'Hours must be in 00..23 (24 hour wrap is not implicit): %r'
                % (timecode, ))
        if minutes >= 60 or seconds >= 60:
            raise InvalidTimecode('Malformed timecode: %r' % (timecode, ))
        if frames >= self.nominal_fps:
            raise InvalidTimecode(
                'Invalid frame number %d for %s fps in %r'
                % (frames, self.nominal_fps, timecode))

        if self.drop_frame and seconds == 0 and frames < DROP_FRAMES_PER_MINUTE \
                and minutes % 10 != 0:
            raise DroppedFrameCode(
                'Drop-frame timecode %r names a frame skipped by 29.97 '
                'counting' % (timecode, ))

        return self.fields_to_frame_number(hours, minutes, seconds, frames)

    # -- field arithmetic --------------------------------------------------

    def frame_number_to_fields(self, frame_number):
        """
        Convert a 0-based frame number to ``(hours, minutes, seconds, frames)``.
        """
        if self.drop_frame:
            ten_minute_blocks, remainder = divmod(frame_number,
                                                   FRAMES_PER_TEN_MINUTES)
            counted = frame_number + DROP_FRAMES_PER_MINUTE * 9 * \
                ten_minute_blocks
            if remainder >= DROP_FRAMES_PER_MINUTE:
                # 1798 = 60 * 30 - 2 frames in a non-boundary minute.
                counted += DROP_FRAMES_PER_MINUTE * \
                    ((remainder - DROP_FRAMES_PER_MINUTE) // 1798)
            frame_number = counted

        nominal = self.nominal_fps
        frames = frame_number % nominal
        seconds = (frame_number // nominal) % 60
        minutes = (frame_number // (nominal * 60)) % 60
        hours = (frame_number // (nominal * 3600)) % 24
        return hours, minutes, seconds, frames

    def fields_to_frame_number(self, hours, minutes, seconds, frames):
        """
        Convert ``(hours, minutes, seconds, frames)`` to a 0-based frame
        number. Callers are responsible for validating the fields.
        """
        nominal = self.nominal_fps
        frame_number = ((hours * 3600 + minutes * 60 + seconds) * nominal
                        + frames)
        if self.drop_frame:
            total_minutes = hours * 60 + minutes
            frame_number -= DROP_FRAMES_PER_MINUTE * \
                (total_minutes - total_minutes // 10)
        return frame_number
