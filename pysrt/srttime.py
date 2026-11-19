# -*- coding: utf-8 -*-
"""
SubRip's time format parser: HH:MM:SS,mmm
"""
import re
from datetime import time

from pysrt.srtexc import InvalidTimeString, InvalidTimecode
from pysrt.comparablemixin import ComparableMixin
from pysrt.compat import str, basestring
from pysrt.smpte import FrameRate, SECONDS_PER_DAY


class TimeItemDescriptor(object):
    # pylint: disable-msg=R0903
    def __init__(self, ratio, super_ratio=0):
        self.ratio = int(ratio)
        self.super_ratio = int(super_ratio)

    def _get_ordinal(self, instance):
        if self.super_ratio:
            return instance.ordinal % self.super_ratio
        return instance.ordinal

    def __get__(self, instance, klass):
        if instance is None:
            raise AttributeError
        return self._get_ordinal(instance) // self.ratio

    def __set__(self, instance, value):
        part = self._get_ordinal(instance) - instance.ordinal % self.ratio
        instance.ordinal += value * self.ratio - part


class SubRipTime(ComparableMixin):
    TIME_PATTERN = '%02d:%02d:%02d,%03d'
    TIME_REPR = 'SubRipTime(%d, %d, %d, %d)'
    RE_TIME_SEP = re.compile(r'\:|\.|\,')
    RE_INTEGER = re.compile(r'^(\d+)')
    SECONDS_RATIO = 1000
    MINUTES_RATIO = SECONDS_RATIO * 60
    HOURS_RATIO = MINUTES_RATIO * 60

    hours = TimeItemDescriptor(HOURS_RATIO)
    minutes = TimeItemDescriptor(MINUTES_RATIO, HOURS_RATIO)
    seconds = TimeItemDescriptor(SECONDS_RATIO, MINUTES_RATIO)
    milliseconds = TimeItemDescriptor(1, SECONDS_RATIO)

    def __init__(self, hours=0, minutes=0, seconds=0, milliseconds=0):
        """
        SubRipTime(hours, minutes, seconds, milliseconds)

        All arguments are optional and have a default value of 0.
        """
        super(SubRipTime, self).__init__()
        self.ordinal = hours * self.HOURS_RATIO \
                     + minutes * self.MINUTES_RATIO \
                     + seconds * self.SECONDS_RATIO \
                     + milliseconds

    def __repr__(self):
        return self.TIME_REPR % tuple(self)

    def __str__(self):
        if self.ordinal < 0:
            # Represent negative times as zero
            return str(SubRipTime.from_ordinal(0))
        return self.TIME_PATTERN % tuple(self)

    def _compare(self, other, method):
        return super(SubRipTime, self)._compare(self.coerce(other), method)

    def _cmpkey(self):
        return self.ordinal

    def __add__(self, other):
        return self.from_ordinal(self.ordinal + self.coerce(other).ordinal)

    def __iadd__(self, other):
        self.ordinal += self.coerce(other).ordinal
        return self

    def __sub__(self, other):
        return self.from_ordinal(self.ordinal - self.coerce(other).ordinal)

    def __isub__(self, other):
        self.ordinal -= self.coerce(other).ordinal
        return self

    def __mul__(self, ratio):
        return self.from_ordinal(int(round(self.ordinal * ratio)))

    def __imul__(self, ratio):
        self.ordinal = int(round(self.ordinal * ratio))
        return self

    @classmethod
    def coerce(cls, other):
        """
        Coerce many types to SubRipTime instance.
        Supported types:
          - str/unicode
          - int/long
          - datetime.time
          - any iterable
          - dict
        """
        if isinstance(other, SubRipTime):
            return other
        if isinstance(other, basestring):
            return cls.from_string(other)
        if isinstance(other, int):
            return cls.from_ordinal(other)
        if isinstance(other, time):
            return cls.from_time(other)
        try:
            return cls(**other)
        except TypeError:
            return cls(*other)

    def __iter__(self):
        yield self.hours
        yield self.minutes
        yield self.seconds
        yield self.milliseconds

    def shift(self, *args, **kwargs):
        """
        shift(hours, minutes, seconds, milliseconds)

        All arguments are optional and have a default value of 0.
        """
        if 'ratio' in kwargs:
            self *= kwargs.pop('ratio')
        self += self.__class__(*args, **kwargs)

    @classmethod
    def from_ordinal(cls, ordinal):
        """
        int -> SubRipTime corresponding to a total count of milliseconds
        """
        return cls(milliseconds=int(ordinal))

    @classmethod
    def from_string(cls, source):
        """
        str/unicode(HH:MM:SS,mmm) -> SubRipTime corresponding to serial
        raise InvalidTimeString
        """
        items = cls.RE_TIME_SEP.split(source)
        if len(items) != 4:
            raise InvalidTimeString
        return cls(*(cls.parse_int(i) for i in items))

    @classmethod
    def parse_int(cls, digits):
        try:
            return int(digits)
        except ValueError:
            match = cls.RE_INTEGER.match(digits)
            if match:
                return int(match.group())
            return 0

    @classmethod
    def from_time(cls, source):
        """
        datetime.time -> SubRipTime corresponding to time object
        """
        return cls(hours=source.hour, minutes=source.minute,
            seconds=source.second, milliseconds=source.microsecond // 1000)

    def to_time(self):
        """
        Convert SubRipTime instance into a pure datetime.time object
        """
        return time(self.hours, self.minutes, self.seconds,
                    self.milliseconds * 1000)

    # -- SMPTE timecode (HH:MM:SS:FF / HH:MM:SS;FF) -----------------------

    def to_frame_number(self, frame_rate):
        """
        to_frame_number(frame_rate) -> int

        Frame number at the given frame rate, rounded to the nearest frame.
        A time exactly halfway between two frames selects the later frame.

        `frame_rate` may be a FrameRate, 24, 25, 30, 30000/1001, 29.97 or
        any equivalent Fraction/string.
        raise InvalidTimecode on negative times
        raise InvalidFrameRate on unsupported rates
        """
        return FrameRate.coerce(frame_rate).ordinal_to_frames(self.ordinal)

    @classmethod
    def from_frame_number(cls, frame_number, frame_rate):
        """
        from_frame_number(frame_number, frame_rate) -> SubRipTime

        SubRipTime for the given frame number, rounded to the nearest
        millisecond (ties upwards). Frame numbers do not wrap; numbers
        beyond 24 hours are accepted since SubRipTime has no 24 hour limit.
        raise InvalidTimecode on negative frame numbers
        raise InvalidFrameRate on unsupported rates
        """
        frame_rate = FrameRate.coerce(frame_rate)
        if isinstance(frame_number, bool):
            raise InvalidTimecode(
                'Frame number must be an integer, got %r' % (frame_number, ))
        try:
            is_integer = int(frame_number) == frame_number
        except (TypeError, ValueError, OverflowError):
            is_integer = False
        if not is_integer:
            raise InvalidTimecode(
                'Frame number must be an integer, got %r' % (frame_number, ))
        return cls.from_ordinal(frame_rate.frames_to_ordinal(int(frame_number)))

    def to_timecode(self, frame_rate, wrap=False):
        """
        to_timecode(frame_rate[, wrap]) -> str

        SMPTE timecode for this time. Drop-frame rates use ``;`` before the
        frames field, other rates use ``:``.

        A time at or after 24 hours raises InvalidTimecode unless
        `wrap` is true, in which case the time of day is taken modulo 24
        hours of wall-clock time (24:00:00,000 -> 00:00:00:00 at every
        rate, drop-frame included).
        raise InvalidTimecode on negative times
        raise InvalidFrameRate on unsupported rates
        """
        frame_rate = FrameRate.coerce(frame_rate)
        if self.ordinal < 0:
            raise InvalidTimecode(
                'Negative time (%d ms) has no SMPTE representation'
                % self.ordinal)
        ordinal = self.ordinal
        if wrap:
            ordinal %= SECONDS_PER_DAY * 1000
        frame_number = frame_rate.ordinal_to_frames(ordinal)
        if wrap and frame_number >= frame_rate.frames_per_24_hours:
            # At drop-frame rates the last fraction of a second rounds
            # past the end of the 24 hour timecode day (a 29.97 timecode
            # day is a few frames shorter than 24 hours of wall time).
            # Clamp so a wrapped time inside the day never raises.
            frame_number = frame_rate.frames_per_24_hours - 1
        return frame_rate.frames_to_timecode(frame_number)

    @classmethod
    def from_timecode(cls, timecode, frame_rate):
        """
        from_timecode(timecode, frame_rate) -> SubRipTime

        Parse ``HH:MM:SS:FF`` (or ``HH:MM:SS;FF`` for drop-frame) at the
        given frame rate and round to the nearest millisecond.

        raise InvalidTimecode on malformed codes, out of range fields,
            a separator mismatching the rate and negative times
        raise DroppedFrameCode when a drop-frame code names a skipped frame
        raise InvalidFrameRate on unsupported rates
        """
        frame_rate = FrameRate.coerce(frame_rate)
        return cls.from_frame_number(
            frame_rate.timecode_to_frames(timecode), frame_rate)
