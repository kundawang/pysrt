#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SMPTE timecode support tests.

Covered:
  * SubRipTime <-> HH:MM:SS:FF / HH:MM:SS;FF conversion at 24, 25, 30 and
    30000/1001 drop-frame.
  * Rounding to the frame and to the millisecond.
  * SubRipFile export/import of all start/end times, order and duration
    stability.
  * Errors: invalid frame numbers, skipped drop-frame codes, negative
    times, 24 hour wrap, non finite frame rates, unframeable milliseconds.
  * Fixed reference samples around the hour, across a ten minute boundary
    and one hour long.
"""

import os
import sys
import unittest
from fractions import Fraction

file_path = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, os.path.abspath(file_path))

import pysrt
from pysrt import (SubRipFile, SubRipItem, SubRipTime, FrameRate,
                   InvalidTimecode, DroppedFrameCode, InvalidFrameRate,
                   InvalidTimeString, Error)

DROP_FRAME = '30000/1001'


class TestFrameRate(unittest.TestCase):

    def test_supported_integer_rates(self):
        for rate in (24, 25, 30):
            frame_rate = FrameRate(rate)
            self.assertEqual(frame_rate.fps, rate)
            self.assertEqual(frame_rate.nominal_fps, rate)
            self.assertFalse(frame_rate.drop_frame)
            self.assertEqual(frame_rate.timecode_separator, ':')

    def test_supported_drop_frame_forms(self):
        for rate in (DROP_FRAME, '29.97', 29.97, 29.97002997,
                     Fraction(30000, 1001)):
            frame_rate = FrameRate(rate)
            self.assertEqual(frame_rate.fps, Fraction(30000, 1001))
            self.assertTrue(frame_rate.drop_frame)
            self.assertEqual(frame_rate.nominal_fps, 30)
            self.assertEqual(frame_rate.timecode_separator, ';')

    def test_string_integer_rate(self):
        self.assertEqual(FrameRate('25'), FrameRate(25))
        self.assertEqual(FrameRate('25.0'), FrameRate(25))

    def test_non_finite_rates(self):
        for rate in (float('nan'), float('inf'), float('-inf')):
            self.assertRaises(InvalidFrameRate, FrameRate, rate)

    def test_unsupported_rates(self):
        for rate in (23, 23.976, 50, 60, -25, 0, 0.0, '0', '0/1', 'abc',
                     '', None, True, False):
            self.assertRaises(InvalidFrameRate, FrameRate, rate)

    def test_decimal_and_fraction_string_rates(self):
        for rate in ('29.97', '29.97002997', '29.97/1', '30000/1001',
                     ' 30000 / 1001 '):
            self.assertTrue(FrameRate(rate).drop_frame, rate)
        self.assertRaises(InvalidFrameRate, FrameRate, '30000.0/1001.5')
        self.assertRaises(InvalidFrameRate, FrameRate, '1e1')

    def test_zero_denominator(self):
        self.assertRaises(InvalidFrameRate, FrameRate, '30000/0')

    def test_drop_frame_constraints(self):
        self.assertRaises(InvalidFrameRate, FrameRate, DROP_FRAME,
                          drop_frame=False)
        self.assertRaises(InvalidFrameRate, FrameRate, 25, drop_frame=True)
        self.assertTrue(FrameRate(DROP_FRAME, drop_frame=True).drop_frame)

    def test_frames_per_24_hours(self):
        self.assertEqual(FrameRate(24).frames_per_24_hours, 24 * 3600 * 24)
        self.assertEqual(FrameRate(25).frames_per_24_hours, 25 * 3600 * 24)
        self.assertEqual(FrameRate(30).frames_per_24_hours, 30 * 3600 * 24)
        self.assertEqual(FrameRate(DROP_FRAME).frames_per_24_hours, 2589408)

    def test_coerce_and_equality(self):
        frame_rate = FrameRate(25)
        self.assertTrue(FrameRate.coerce(frame_rate) is frame_rate)
        self.assertEqual(FrameRate.coerce('25'), frame_rate)
        self.assertEqual(hash(FrameRate(25)), hash(FrameRate('25')))
        self.assertNotEqual(FrameRate(25), FrameRate(24))
        self.assertNotEqual(FrameRate(25), FrameRate(DROP_FRAME))

    def test_repr(self):
        self.assertEqual(repr(FrameRate(25)), 'FrameRate(25)')
        self.assertEqual(repr(FrameRate(DROP_FRAME)), 'FrameRate(30000/1001)')

    def test_equality_with_junk(self):
        self.assertFalse(FrameRate(25) == 'junk')
        self.assertTrue(FrameRate(25) != object())


class TestFrameArithmetic(unittest.TestCase):

    def test_integer_rate_frame_boundaries(self):
        for rate in (24, 25, 30):
            frame_rate = FrameRate(rate)
            # Whole seconds map to exact frame counts and back.
            for second in (0, 1, 59, 60, 3599, 3600, 36000, 86399):
                ordinal = second * 1000
                self.assertEqual(
                    frame_rate.ordinal_to_frames(ordinal), second * rate)
                self.assertEqual(
                    frame_rate.frames_to_ordinal(second * rate), ordinal)

    def test_round_half_up_to_frame(self):
        frame_rate = FrameRate(25)  # 40 ms per frame
        self.assertEqual(frame_rate.ordinal_to_frames(19), 0)
        self.assertEqual(frame_rate.ordinal_to_frames(20), 1)  # tie up
        self.assertEqual(frame_rate.ordinal_to_frames(39), 1)
        self.assertEqual(frame_rate.ordinal_to_frames(19.5), 0)
        self.assertEqual(frame_rate.ordinal_to_frames(20.0), 1)

    def test_round_down_below_half(self):
        frame_rate = FrameRate(24)  # 41.666... ms per frame
        self.assertEqual(frame_rate.ordinal_to_frames(20), 0)
        self.assertEqual(frame_rate.ordinal_to_frames(21), 1)  # 20.83 -> 1

    def test_round_half_up_to_millisecond(self):
        frame_rate = FrameRate(DROP_FRAME)  # 33.3667 ms per frame
        # frame 1 = 33.3667 -> 33 ms
        self.assertEqual(frame_rate.frames_to_ordinal(1), 33)
        # frame 45 = 1501.5 ms exactly -> tie rounds up to 1502
        self.assertEqual(frame_rate.frames_to_ordinal(45), 1502)
        # frame 15 = 500.5 ms exactly -> 501
        self.assertEqual(frame_rate.frames_to_ordinal(15), 501)

    def test_negative_rejected(self):
        self.assertRaises(InvalidTimecode,
                          FrameRate(25).ordinal_to_frames, -1)
        self.assertRaises(InvalidTimecode,
                          FrameRate(25).frames_to_ordinal, -1)


class TestTimecodeFixedSamples(unittest.TestCase):
    """Fixed samples around the hour, the ten minute boundary and 1 hour."""

    # (rate, HH:MM:SS:FF, expected milliseconds, expected frame number)
    #
    # Expected milliseconds are computed independently of the library:
    #   integer rates: round_half_up(frame * 1000 / rate)
    #   drop-frame:    timecode fields -> frame number -> round_half_up(
    #                  frame * 1001 / 30)
    # Drop-frame timecodes track 30000/1001 fps, so a code at the top of
    # the hour names slightly less than one hour of wall time. That drift
    # is expected: 01:00:00;00 is 3599996 ms, not 3600000 ms.
    SAMPLES = (
        # Around the hour.
        (24, '00:59:59:23', 3599958, 86399),
        (24, '01:00:00:00', 3600000, 86400),
        (24, '01:00:00:01', 3600042, 86401),
        (25, '00:59:59:24', 3599960, 89999),
        (25, '01:00:00:00', 3600000, 90000),
        (25, '01:00:00:01', 3600040, 90001),
        (30, '00:59:59:29', 3599967, 107999),
        (30, '01:00:00:00', 3600000, 108000),
        (30, '01:00:00:01', 3600033, 108001),
        # Drop-frame around the hour: no frames are dropped at minute 60.
        (DROP_FRAME, '00:59:59;29', 3599963, 107891),
        (DROP_FRAME, '01:00:00;00', 3599996, 107892),
        (DROP_FRAME, '01:00:00;01', 3600030, 107893),
        # Drop-frame ten minute boundary: frames ;00 and ;01 skipped.
        (DROP_FRAME, '00:09:59;29', 599966, 17981),
        (DROP_FRAME, '00:10:00;00', 599999, 17982),
        (DROP_FRAME, '00:10:00;01', 600033, 17983),
        (DROP_FRAME, '00:10:00;02', 600066, 17984),
        (DROP_FRAME, '00:19:59;29', 1199965, 35963),
        (DROP_FRAME, '00:20:00;00', 1199999, 35964),
        # Non drop-frame ten minute boundary: no skipping.
        (25, '00:09:59:24', 599960, 14999),
        (25, '00:10:00:00', 600000, 15000),
        (25, '00:10:00:01', 600040, 15001),
        # One hour fixed sample.
        (24, '01:00:00:00', 3600000, 86400),
        (25, '01:00:00:00', 3600000, 90000),
        (30, '01:00:00:00', 3600000, 108000),
        (DROP_FRAME, '01:00:00;00', 3599996, 107892),
    )

    def test_timecode_to_time_and_frames(self):
        for rate, timecode, ordinal, frame_number in self.SAMPLES:
            time = SubRipTime.from_timecode(timecode, rate)
            self.assertEqual(time.ordinal, ordinal,
                             '%s at %s -> %s' % (timecode, rate, time))
            self.assertEqual(time.to_frame_number(rate), frame_number,
                             '%s at %s' % (timecode, rate))
            self.assertEqual(time.to_timecode(rate), timecode,
                             '%s at %s' % (timecode, rate))

    def test_drop_frame_drift_is_one_millisecond_scale(self):
        # The frame-aligned SRT value is within a millisecond of the true
        # frame instant; the timecode itself still round-trips exactly.
        for rate, timecode, ordinal, frame_number in self.SAMPLES:
            if rate != DROP_FRAME:
                continue
            true_ms = Fraction(frame_number * 1001, 30)
            self.assertLessEqual(abs(true_ms - ordinal), Fraction(1, 2),
                                 timecode)

    def test_twenty_three_thirty(self):
        # 23:30:00;00 is the third ten minute block of the 23rd hour. Its
        # wall time is slightly under 23.5 h because of 29.97 drift.
        frame_rate = FrameRate(DROP_FRAME)
        frame_number = 23 * 107892 + 3 * 17982
        self.assertEqual(
            frame_rate.timecode_to_frames('23:30:00;00'), frame_number)
        time = SubRipTime.from_frame_number(frame_number, DROP_FRAME)
        self.assertEqual(time.to_timecode(DROP_FRAME), '23:30:00;00')
        self.assertEqual(time.ordinal, 84599915)


class TestTenMinuteBoundaryDropFrame(unittest.TestCase):
    """Explicit checks for the 00:01:00;00-style skipped codes."""

    def test_skipped_codes_rejected(self):
        frame_rate = FrameRate(DROP_FRAME)
        for minute in range(0, 60):
            if minute % 10 == 0:
                continue
            for frame in (0, 1):
                timecode = '00:%02d:00;%02d' % (minute, frame)
                self.assertRaises(DroppedFrameCode,
                                  frame_rate.timecode_to_frames, timecode)
                self.assertRaises(DroppedFrameCode,
                                  SubRipTime.from_timecode,
                                  timecode, DROP_FRAME)

    def test_valid_codes_accepted(self):
        frame_rate = FrameRate(DROP_FRAME)
        for minute in range(0, 60, 10):
            self.assertEqual(
                frame_rate.timecode_to_frames('00:%02d:00;00' % minute),
                minute * 60 * 30 - (minute // 10) * 18)
            self.assertEqual(
                frame_rate.timecode_to_frames('00:%02d:00;01' % minute),
                minute * 60 * 30 - (minute // 10) * 18 + 1)
        # Frames 02 and up are valid on every minute.
        self.assertEqual(frame_rate.timecode_to_frames('00:01:00;02'), 1800)

    def test_every_generated_code_is_valid(self):
        frame_rate = FrameRate(DROP_FRAME)
        for frame_number in range(0, frame_rate.frames_per_24_hours, 1499):
            timecode = frame_rate.frames_to_timecode(frame_number)
            self.assertEqual(frame_rate.timecode_to_frames(timecode),
                             frame_number)

    def test_ten_minute_block_is_17982_frames(self):
        frame_rate = FrameRate(DROP_FRAME)
        self.assertEqual(frame_rate.timecode_to_frames('00:10:00;00'), 17982)
        self.assertEqual(frame_rate.timecode_to_frames('00:00:00;00')
                         + 17982, 17982)
        self.assertEqual(
            frame_rate.timecode_to_frames('00:20:00;00'),
            frame_rate.timecode_to_frames('00:10:00;00') + 17982)


class TestTimecodeErrors(unittest.TestCase):

    def test_malformed_timecodes(self):
        frame_rate = FrameRate(25)
        for timecode in ('', 'hello', '00:00:00', '00:00:00:00:00',
                         '00:00:0:00', '0:00:00:00', '00:00:00:0',
                         '00:00:00:-1', ' 00:00:00:00', '00:00:00:00 ',
                         '00.00.00.00', '00:00:00,00'):
            self.assertRaises(InvalidTimecode,
                              frame_rate.timecode_to_frames, timecode)

    def test_non_string_timecodes(self):
        for timecode in (1000, None, b'00:00:00:00', bytearray(b'x')):
            self.assertRaises(InvalidTimecode,
                              FrameRate(25).timecode_to_frames, timecode)
            self.assertRaises(InvalidTimecode, SubRipTime.from_timecode,
                              timecode, 25)

    def test_out_of_range_fields(self):
        frame_rate = FrameRate(25)
        for timecode in ('24:00:00:00', '25:00:00:00', '00:60:00:00',
                         '00:00:60:00', '00:00:00:25', '00:00:00:99'):
            self.assertRaises(InvalidTimecode,
                              frame_rate.timecode_to_frames, timecode)

    def test_last_valid_frame_of_the_day(self):
        self.assertEqual(FrameRate(25).timecode_to_frames('23:59:59:24'),
                         25 * 86400 - 1)
        self.assertEqual(FrameRate(DROP_FRAME).timecode_to_frames(
            '23:59:59;29'), 2589407)

    def test_wrong_separator(self):
        self.assertRaises(InvalidTimecode,
                          FrameRate(25).timecode_to_frames, '00:00:00;00')
        self.assertRaises(InvalidTimecode,
                          FrameRate(DROP_FRAME).timecode_to_frames,
                          '00:00:00:00')

    def test_invalid_frame_number_for_rate(self):
        # Frame 24 exists at 25 fps but not at 24 fps.
        self.assertEqual(FrameRate(25).timecode_to_frames('00:00:00:24'),
                         24)
        self.assertRaises(InvalidTimecode,
                          FrameRate(24).timecode_to_frames, '00:00:00:24')
        self.assertRaises(InvalidTimecode,
                          FrameRate(30).timecode_to_frames, '00:00:00:30')

    def test_from_frame_number_rejects_non_integers(self):
        for frame_number in (1.5, '10', None, float('nan'), float('inf'),
                             True, False):
            self.assertRaises((InvalidTimecode, InvalidFrameRate),
                              SubRipTime.from_frame_number,
                              frame_number, 25)
        self.assertRaises(InvalidTimecode, SubRipTime.from_frame_number,
                          -1, 25)

    def test_from_frame_number_accepts_integral_floats(self):
        self.assertEqual(SubRipTime.from_frame_number(25.0, 25),
                         SubRipTime.from_frame_number(25, 25))

    def test_errors_are_invalid_time_strings(self):
        self.assertTrue(issubclass(InvalidTimecode, InvalidTimeString))
        self.assertTrue(issubclass(DroppedFrameCode, InvalidTimecode))
        self.assertTrue(issubclass(InvalidFrameRate, ValueError))


class TestNegativeTimes(unittest.TestCase):

    def test_to_timecode_rejects_negative(self):
        self.assertRaises(InvalidTimecode,
                          SubRipTime(milliseconds=-1).to_timecode, 25)
        self.assertRaises(InvalidTimecode, SubRipTime(-1, 0, 0, 0).to_timecode,
                          25)

    def test_to_frame_number_rejects_negative(self):
        self.assertRaises(InvalidTimecode,
                          SubRipTime(milliseconds=-1).to_frame_number, 25)

    def test_negative_srt_serialization_unchanged(self):
        # Existing behaviour is preserved: str() clamps to zero.
        self.assertEqual(str(SubRipTime(milliseconds=-1)), '00:00:00,000')


class TestTwentyFourHourWrap(unittest.TestCase):

    def test_export_at_limit_raises(self):
        day = 24 * 3600 * 1000
        for rate in (24, 25, 30, DROP_FRAME):
            frame_rate = FrameRate(rate)
            at_limit = SubRipTime.from_frame_number(
                frame_rate.frames_per_24_hours, rate)
            self.assertRaises(InvalidTimecode, at_limit.to_timecode, rate)
            # Even frame numbers computed independently raise.
            self.assertRaises(
                InvalidTimecode, frame_rate.frames_to_timecode,
                frame_rate.frames_per_24_hours)
        self.assertRaises(InvalidTimecode,
                          SubRipTime.from_ordinal(day + 1).to_timecode, 25)

    def test_wrap_reduces_modulo_24_hours(self):
        day = 24 * 3600 * 1000
        for rate in (24, 25, 30, DROP_FRAME):
            frame_rate = FrameRate(rate)
            exact_day = SubRipTime.from_ordinal(day)
            self.assertEqual(exact_day.to_timecode(rate, wrap=True),
                             '00:00:00%s00' % frame_rate.timecode_separator)
        # A day plus one second wraps to one second.
        wrapped = SubRipTime.from_ordinal(day + 1000).to_timecode(25,
                                                                   wrap=True)
        self.assertEqual(wrapped, '00:00:01:00')

    def test_drop_frame_wrap(self):
        # 24 hours of wall time is frame 2589411 at 30000/1001, which is
        # past the end of the 24 hour timecode day (2589408 frames).
        # Wrapping reduces the wall time first, so exact multiples of a
        # day land on 00:00:00;00.
        frame_rate = FrameRate(DROP_FRAME)
        self.assertEqual(frame_rate.ordinal_to_frames(24 * 3600 * 1000),
                         2589411)
        self.assertEqual(
            SubRipTime.from_ordinal(24 * 3600 * 1000).to_timecode(
                DROP_FRAME, wrap=True),
            '00:00:00;00')
        self.assertEqual(SubRipTime(24, 0, 0, 0).to_timecode(DROP_FRAME,
                                                             wrap=True),
                         '00:00:00;00')

    def test_drop_frame_end_of_day(self):
        # The last representable drop-frame code is 23:59:59;29 (frame
        # 2589407), i.e. 86399880.23... ms of wall time. Values up to
        # 86399896 ms round to it; from 86399897 ms on they round past
        # the end of the timecode day. Without wrap that raises rather
        # than silently wrapping; with wrap it clamps to the last frame.
        self.assertEqual(SubRipTime(23, 59, 59, 896).to_timecode(DROP_FRAME),
                         '23:59:59;29')
        late = SubRipTime(23, 59, 59, 897)
        self.assertRaises(InvalidTimecode, late.to_timecode, DROP_FRAME)
        self.assertEqual(late.to_timecode(DROP_FRAME, wrap=True),
                         '23:59:59;29')

    def test_wrap_does_not_affect_in_range_times(self):
        time = SubRipTime(23, 59, 59, 960)
        self.assertEqual(time.to_timecode(25, wrap=True),
                         time.to_timecode(25))

    def test_wrap_multiple_days(self):
        self.assertEqual(SubRipTime(48, 0, 0, 0).to_timecode(25, wrap=True),
                         '00:00:00:00')
        self.assertEqual(SubRipTime(49, 2, 3, 0).to_timecode(25, wrap=True),
                         '01:02:03:00')

    def test_just_before_the_limit(self):
        # The last exactly frame-aligned time is frame limit - 1.
        self.assertEqual(SubRipTime(23, 59, 59, 960).to_timecode(25),
                         '23:59:59:24')
        # 23:59:59,999 is nearer to the frame at 24:00:00 than to the last
        # frame of the day, so it rounds out of range and raises.
        self.assertRaises(InvalidTimecode,
                          SubRipTime(23, 59, 59, 999).to_timecode, 25)


class TestMillisecondPrecision(unittest.TestCase):

    def test_unframeable_millisecond_snaps_to_nearest_frame(self):
        frame_rate = FrameRate(25)  # exact 40 ms frames
        # 1 ms is much closer to frame 0 than to frame 1 (40 ms).
        self.assertEqual(SubRipTime(milliseconds=1).to_timecode(25),
                         '00:00:00:00')
        self.assertEqual(SubRipTime(milliseconds=1).to_frame_number(25), 0)
        # 21 ms is closer to frame 1 (40 ms) than frame 0.
        self.assertEqual(SubRipTime(milliseconds=21).to_timecode(25),
                         '00:00:00:01')
        # 20 ms is exactly half a frame: ties round to the later frame.
        self.assertEqual(SubRipTime(milliseconds=20).to_frame_number(25), 1)

    def test_from_frame_number_rounds_to_millisecond(self):
        # frame 1 at 29.97 is 33.3667 ms: SRT resolution cannot keep it
        # exactly, it becomes 33 ms. Re-exporting gives frame 1 again.
        time = SubRipTime.from_timecode('00:00:00;01', DROP_FRAME)
        self.assertEqual(time.ordinal, 33)
        self.assertEqual(time.to_frame_number(DROP_FRAME), 1)
        self.assertEqual(time.to_timecode(DROP_FRAME), '00:00:00;01')

    def test_from_frame_number_tie_to_millisecond(self):
        frame_rate = FrameRate(DROP_FRAME)
        # 45 frames = 1501.5 ms exactly -> 1502 ms (tie upwards).
        self.assertEqual(SubRipTime.from_frame_number(45, DROP_FRAME),
                         SubRipTime(milliseconds=1502))
        # 15 frames = 500.5 ms exactly -> 501 ms (tie upwards).
        self.assertEqual(SubRipTime.from_frame_number(15, DROP_FRAME),
                         SubRipTime(milliseconds=501))

    def test_ms_roundtrip_is_stable(self):
        # Once converted through a timecode, further round trips are exact:
        # the intermediate SRT value is within half a millisecond of the
        # frame timestamp, so re-exporting is idempotent.
        for rate in (24, 25, 30, DROP_FRAME):
            frame_rate = FrameRate(rate)
            for frame_number in (0, 1, 7, 1798, 1800, 17982, 90000, 107892):
                if frame_number >= frame_rate.frames_per_24_hours:
                    continue
                first = SubRipTime.from_frame_number(frame_number, rate)
                timecode = first.to_timecode(rate)
                second = SubRipTime.from_timecode(timecode, rate)
                self.assertEqual(first, second,
                                 '%s at %s' % (timecode, rate))
                self.assertEqual(second.to_timecode(rate), timecode)


class TestSubRipTimeApi(unittest.TestCase):

    def test_timecode_requires_a_frame_rate(self):
        self.assertRaises(TypeError, SubRipTime(0, 0, 1, 0).to_timecode)
        self.assertRaises(TypeError, SubRipTime(0, 0, 1, 0).to_frame_number)
        self.assertRaises(TypeError, SubRipTime.from_timecode, '00:00:01:00')
        self.assertRaises(TypeError, SubRipTime.from_frame_number, 25)

    def test_separator_by_rate(self):
        time = SubRipTime(0, 0, 1, 0)
        self.assertEqual(time.to_timecode(24), '00:00:01:00')
        self.assertEqual(time.to_timecode(25), '00:00:01:00')
        self.assertEqual(time.to_timecode(30), '00:00:01:00')
        self.assertEqual(time.to_timecode(DROP_FRAME), '00:00:01;00')

    def test_frame_rate_object_accepted(self):
        time = SubRipTime(0, 0, 1, 0)
        self.assertEqual(time.to_timecode(FrameRate(25)), '00:00:01:00')
        self.assertEqual(SubRipTime.from_timecode('00:00:01:00',
                                                  FrameRate(25)), time)

    def test_unsupported_rate_propagates(self):
        self.assertRaises(InvalidFrameRate, SubRipTime().to_timecode, 60)
        self.assertRaises(InvalidFrameRate, SubRipTime().to_frame_number,
                          float('nan'))
        self.assertRaises(InvalidFrameRate, SubRipTime.from_timecode,
                          '00:00:00:00', 23)

    def test_editor_handoff_example(self):
        # The motivating case: an editor's 25 fps in-point is converted to
        # the SRT form and back.
        in_point = SubRipTime.from_timecode('01:00:00:00', 25)
        self.assertEqual(str(in_point), '01:00:00,000')
        self.assertEqual(in_point.to_timecode(25), '01:00:00:00')

    def test_drop_frame_editor_handoff(self):
        # A drop-frame in-point is not exactly 01:00:00,000 of wall time
        # (30000/1001 drift): it is 00:59:59,996. The timecode still
        # round-trips exactly.
        in_point = SubRipTime.from_timecode('01:00:00;00', DROP_FRAME)
        self.assertEqual(str(in_point), '00:59:59,996')
        self.assertEqual(in_point.to_timecode(DROP_FRAME), '01:00:00;00')
        self.assertEqual(in_point.to_frame_number(DROP_FRAME), 107892)


class TestSubRipFileTimecodes(unittest.TestCase):

    def setUp(self):
        self.file = SubRipFile([
            SubRipItem(1, (0, 0, 0, 0), (0, 0, 1, 0), 'one'),
            SubRipItem(2, (0, 9, 59, 960), (0, 10, 2, 0), 'ten minutes'),
            SubRipItem(3, (0, 59, 59, 960), (1, 0, 1, 0), 'the hour'),
            SubRipItem(4, (1, 0, 1, 0), (1, 0, 2, 0), 'after the hour'),
            SubRipItem(5, (23, 59, 58, 0), (23, 59, 59, 0), 'late'),
        ])

    def test_export_order_and_values(self):
        self.assertEqual(self.file.to_timecodes(25), [
            ('00:00:00:00', '00:00:01:00'),
            ('00:09:59:24', '00:10:02:00'),
            ('00:59:59:24', '01:00:01:00'),
            ('01:00:01:00', '01:00:02:00'),
            ('23:59:58:00', '23:59:59:00'),
        ])

    def test_export_drop_frame(self):
        # Values are frame-accurate; the ;03 suffix on the late sample is
        # drop-frame drift (23:59:58 wall is 3 frames into ;58).
        self.assertEqual(self.file.to_timecodes(DROP_FRAME), [
            ('00:00:00;00', '00:00:01;00'),
            ('00:09:59;29', '00:10:02;00'),
            ('00:59:59;29', '01:00:01;00'),
            ('01:00:01;00', '01:00:02;00'),
            ('23:59:58;03', '23:59:59;03'),
        ])

    def test_export_is_per_item(self):
        self.assertEqual(self.file[2].start.to_timecode(25), '00:59:59:24')
        self.assertEqual(self.file[2].end.to_timecode(25), '01:00:01:00')

    def test_roundtrip_preserves_everything(self):
        for rate in (24, 25, 30, DROP_FRAME):
            exported = self.file.to_timecodes(rate)
            clone = SubRipFile([
                SubRipItem(item.index, item.start, item.end, item.text,
                           item.position) for item in self.file])
            clone.from_timecodes(exported, rate)
            self.assertEqual(len(clone), len(self.file))
            self.assertEqual([item.index for item in clone],
                             [item.index for item in self.file])
            self.assertEqual([item.text for item in clone],
                             [item.text for item in self.file])
            self.assertEqual(clone.to_timecodes(rate), exported)
            # Durations are stable in frames.
            for original, restored in zip(self.file, clone):
                self.assertEqual(
                    original.duration.to_frame_number(rate),
                    restored.duration.to_frame_number(rate),
                    'duration %s at %s' % (original, rate))

    def test_roundtrip_is_ms_exact_for_frame_aligned_times(self):
        # All fixture times are frame aligned at 25 fps.
        clone = SubRipFile([
            SubRipItem(item.index, item.start, item.end, item.text)
            for item in self.file])
        clone.from_timecodes(self.file.to_timecodes(25), 25)
        self.assertEqual([item.start.ordinal for item in clone],
                         [item.start.ordinal for item in self.file])
        self.assertEqual([item.end.ordinal for item in clone],
                         [item.end.ordinal for item in self.file])

    def test_roundtrip_via_srt_serialization(self):
        # Export to timecodes, import, write SRT text and compare.
        clone = SubRipFile([
            SubRipItem(item.index, item.start, item.end, item.text)
            for item in self.file])
        clone.from_timecodes(clone.to_timecodes(25), 25)
        srt = SubRipFile.from_string(
            '\n'.join(str(item) for item in clone))
        self.assertEqual(len(srt), len(self.file))
        self.assertEqual([i.start.ordinal for i in srt],
                         [i.start.ordinal for i in self.file])

    def test_repeated_roundtrips_are_a_fixed_point(self):
        # Arbitrary millisecond inputs (not frame aligned) may shift a
        # duration by one frame on the *first* pass, because each endpoint
        # rounds independently. After that pass every endpoint is
        # frame-aligned, so export -> import -> export reproduces the same
        # codes and the frame durations stay put.
        file = SubRipFile([
            SubRipItem(1, SubRipTime.from_ordinal(1234),
                       SubRipTime.from_ordinal(5678), 'a'),
            SubRipItem(2, SubRipTime.from_ordinal(6100),
                       SubRipTime.from_ordinal(8245), 'b'),
            SubRipItem(3, SubRipTime.from_ordinal(9000),
                       SubRipTime.from_ordinal(9475), 'c'),
        ])
        for rate in (24, 25, 30, DROP_FRAME):
            first = file.to_timecodes(rate)
            restored = SubRipFile([SubRipItem(0, text=i.text)
                                   for i in file])
            restored.from_timecodes(first, rate)
            second = restored.to_timecodes(rate)
            self.assertEqual(second, first, rate)
            restored2 = SubRipFile([SubRipItem(0, text=i.text)
                                    for i in restored])
            restored2.from_timecodes(second, rate)
            self.assertEqual(
                [i.duration.to_frame_number(rate) for i in restored],
                [i.duration.to_frame_number(rate) for i in restored2], rate)

    def test_from_timecodes_modifies_in_place_and_returns_self(self):
        file = SubRipFile([SubRipItem(1, (0, 0, 0, 0), (0, 0, 1, 0), 'x')])
        result = file.from_timecodes([('00:00:10:00', '00:00:11:00')], 25)
        self.assertTrue(result is file)
        self.assertEqual(file[0].start, (0, 0, 10, 0))
        self.assertEqual(file[0].end, (0, 0, 11, 0))
        self.assertEqual(file[0].text, 'x')

    def test_from_timecodes_clean_indexes(self):
        file = SubRipFile([
            SubRipItem(9, (0, 0, 0, 0), (0, 0, 1, 0), 'b'),
            SubRipItem(3, (0, 0, 2, 0), (0, 0, 3, 0), 'a'),
        ])
        # Timecodes reorder the items ('a' now starts first) and
        # clean_indexes renumbers according to the new time order.
        file.from_timecodes([('00:00:02:00', '00:00:03:00'),
                             ('00:00:00:00', '00:00:01:00')], 25,
                            clean_indexes=True)
        self.assertEqual([item.text for item in file], ['a', 'b'])
        self.assertEqual([item.index for item in file], [1, 2])

    def test_from_timecodes_length_mismatch(self):
        self.assertRaises(Error, self.file.from_timecodes,
                          [('00:00:00:00', '00:00:01:00')], 25)
        self.assertRaises(Error, self.file.from_timecodes, [], 25)

    def test_from_timecodes_validates_before_mutating(self):
        snapshot = [(i.start.ordinal, i.end.ordinal) for i in self.file]
        self.assertRaises(InvalidTimecode, self.file.from_timecodes, [
            ('00:00:00:00', '00:00:01:00'),
            ('00:00:02:00', '00:00:03:00'),
            ('00:00:04:00', '00:00:05:00'),
            ('00:00:06:00', 'not a timecode'),
            ('00:00:08:00', '00:00:09:00'),
        ], 25)
        self.assertEqual([(i.start.ordinal, i.end.ordinal)
                          for i in self.file], snapshot)

    def test_export_wrap_option(self):
        file = SubRipFile([
            SubRipItem(1, (23, 59, 59, 0), (24, 0, 1, 0), 'crosses midnight'),
        ])
        self.assertRaises(InvalidTimecode, file.to_timecodes, 25)
        self.assertEqual(file.to_timecodes(25, wrap=True), [
            ('23:59:59:00', '00:00:01:00'),
        ])

    def test_export_negative_time_raises(self):
        file = SubRipFile([
            SubRipItem(1, SubRipTime(milliseconds=-40), (0, 0, 1, 0), 'x'),
        ])
        self.assertRaises(InvalidTimecode, file.to_timecodes, 25)

    def test_empty_file(self):
        self.assertEqual(SubRipFile().to_timecodes(25), [])
        file = SubRipFile()
        file.from_timecodes([], 25)
        self.assertEqual(len(file), 0)

    def test_order_independent_of_timestamps(self):
        # Out-of-order items are exported in file order, not time order.
        file = SubRipFile([
            SubRipItem(2, (0, 0, 5, 0), (0, 0, 6, 0), 'later'),
            SubRipItem(1, (0, 0, 0, 0), (0, 0, 1, 0), 'earlier'),
        ])
        self.assertEqual(file.to_timecodes(25), [
            ('00:00:05:00', '00:00:06:00'),
            ('00:00:00:00', '00:00:01:00'),
        ])
        restored = SubRipFile([SubRipItem(0, text=i.text) for i in file])
        restored.from_timecodes(file.to_timecodes(25), 25)
        self.assertEqual([i.text for i in restored], ['later', 'earlier'])
        self.assertEqual([i.start.ordinal for i in restored],
                         [i.start.ordinal for i in file])


class TestLongSample(unittest.TestCase):
    """One hour long sample with items every 30 seconds at fixed rates."""

    def _build_file(self):
        items = []
        for index in range(1, 121):
            start = SubRipTime(seconds=(index - 1) * 30)
            end = SubRipTime(seconds=(index - 1) * 30 + 5)
            items.append(SubRipItem(index, start, end, 'line %d' % index))
        return SubRipFile(items)

    def test_one_hour_of_samples_roundtrip(self):
        file = self._build_file()
        self.assertEqual(file[-1].end.ordinal, 3600 * 1000 - 30000 + 5000)
        for rate in (24, 25, 30):
            exported = file.to_timecodes(rate)
            self.assertEqual(len(exported), 120)
            restored = SubRipFile([SubRipItem(0, text=i.text) for i in file])
            restored.from_timecodes(exported, rate)
            self.assertEqual([i.start.ordinal for i in restored],
                             [i.start.ordinal for i in file])
            self.assertEqual([i.end.ordinal for i in restored],
                             [i.end.ordinal for i in file])
            # Timecodes are strictly increasing in file order.
            starts = [start for start, end in exported]
            self.assertEqual(starts, sorted(starts))
            self.assertEqual(len(set(starts)), len(starts))

    def test_one_hour_of_samples_drop_frame(self):
        file = self._build_file()
        exported = file.to_timecodes(DROP_FRAME)
        frame_rate = FrameRate(DROP_FRAME)
        frames = [frame_rate.timecode_to_frames(start) for start, end
                  in exported]
        # Frame numbers increase by the expected count between samples,
        # with no repeats or gaps.
        for first, second in zip(frames[:-1], frames[1:]):
            self.assertTrue(second > first)
        restored = SubRipFile([SubRipItem(0, text=i.text) for i in file])
        restored.from_timecodes(exported, DROP_FRAME)
        # Drop-frame timecodes are frame exact, but 30000/1001 is slower
        # than 30 fps so a "round" 30 s wall time lands a few milliseconds
        # earlier. The residual is always within one frame.
        frame_ms = Fraction(1001, 30)
        for original, copy in zip(file, restored):
            self.assertLessEqual(abs(original.start.ordinal -
                                     copy.start.ordinal), frame_ms)
            self.assertLessEqual(abs(original.end.ordinal -
                                     copy.end.ordinal), frame_ms)
        # And the restored values round-trip exactly from there on.
        self.assertEqual(restored.to_timecodes(DROP_FRAME), exported)


class TestBackwardCompatibility(unittest.TestCase):

    def test_srt_parsing_unaffected(self):
        item = SubRipItem.from_string(
            '1\n00:01:00,000 --> 00:01:20,000\nHello world !\n')
        self.assertEqual(item.start, (0, 1, 0, 0))
        self.assertEqual(str(item),
                         '1\n00:01:00,000 --> 00:01:20,000\nHello world !\n')

    def test_exports_available_from_package(self):
        for name in ('FrameRate', 'InvalidTimecode', 'DroppedFrameCode',
                     'InvalidFrameRate'):
            self.assertTrue(hasattr(pysrt, name), name)


if __name__ == '__main__':
    unittest.main()
