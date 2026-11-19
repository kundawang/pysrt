#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import unittest

file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.abspath(file_path))

import pysrt
from pysrt import SubRipFile, SubRipItem, SubRipTime
from pysrt.gaps import ChapterPlacementError, find_gaps, place_chapters


FIXTURE = """1
00:00:10,000 --> 00:00:20,000
First line

2
00:00:15,000 --> 00:00:25,000
Second line, overlaps the first

3
00:00:30,000 --> 00:00:40,000
Third line
"""


def ordinals(gaps):
    return [(gap.start.ordinal, gap.end.ordinal) for gap in gaps]


class TestFindGaps(unittest.TestCase):
    """
    Three overlapping cues (10-20, 15-25, 30-40) in a 60s media with a
    2s safety margin on both ends: occupancy merges to [10,25] and
    [30,40], leaving gaps [2,10], [25,30] and [40,58].
    """

    def setUp(self):
        self.subs = SubRipFile.from_string(FIXTURE)

    def test_merged_gaps(self):
        gaps = find_gaps(self.subs, 60000, min_gap=3000,
                         head_margin=2000, tail_margin=2000)
        self.assertEqual(ordinals(gaps),
                         [(2000, 10000), (25000, 30000), (40000, 58000)])

    def test_min_gap_filters_short_windows(self):
        gaps = find_gaps(self.subs, 60000, min_gap=6000,
                         head_margin=2000, tail_margin=2000)
        self.assertEqual(ordinals(gaps), [(2000, 10000), (40000, 58000)])

    def test_no_margin_no_min_gap(self):
        gaps = find_gaps(self.subs, 60000)
        self.assertEqual(ordinals(gaps),
                         [(0, 10000), (25000, 30000), (40000, 60000)])

    def test_zero_duration_and_out_of_bounds_cues(self):
        subs = SubRipFile(items=[
            SubRipItem(1, -5000, 5000, 'negative start'),
            SubRipItem(2, 8000, 8000, 'zero duration'),
            SubRipItem(3, 55000, 70000, 'overflows the end'),
            SubRipItem(4, 70000, 80000, 'fully out of bounds'),
        ])
        gaps = find_gaps(subs, 60000, min_gap=0, head_margin=0,
                         tail_margin=0)
        self.assertEqual(ordinals(gaps), [(5000, 55000)])

    def test_no_available_gap(self):
        subs = SubRipFile(items=[SubRipItem(1, 0, 60000, 'wall to wall')])
        self.assertEqual(find_gaps(subs, 60000), [])

    def test_empty_file_is_one_big_gap(self):
        gaps = find_gaps(SubRipFile(), 60000, head_margin=2000,
                         tail_margin=2000)
        self.assertEqual(ordinals(gaps), [(2000, 58000)])

    def test_illegal_margins(self):
        self.assertRaises(ValueError, find_gaps, self.subs, 60000,
                          head_margin=-1)
        self.assertRaises(ValueError, find_gaps, self.subs, 60000,
                          tail_margin=-1000)
        self.assertRaises(ValueError, find_gaps, self.subs, 60000,
                          head_margin=30000, tail_margin=30000)
        self.assertRaises(ValueError, find_gaps, self.subs, 60000,
                          min_gap=-1)
        self.assertRaises(ValueError, find_gaps, self.subs, 0)
        self.assertRaises(ValueError, find_gaps, self.subs, -60000)


class TestPlaceChapters(unittest.TestCase):

    def setUp(self):
        self.subs = SubRipFile.from_string(FIXTURE)
        self.kwargs = dict(media_duration=60000, min_gap=3000,
                           min_display=4000, head_margin=2000,
                           tail_margin=2000)

    def test_placement_by_priority(self):
        chapters = [('Chapter two', 10), ('Chapter one', 20)]
        new_file = place_chapters(self.subs, chapters, **self.kwargs)

        self.assertEqual(len(new_file), 5)
        self.assertEqual([item.index for item in new_file], [1, 2, 3, 4, 5])

        cards = [item for item in new_file
                 if item.text.startswith('Chapter')]
        # highest priority first, each at the start of the earliest gap
        # that still fits min_display
        self.assertEqual(cards[0].text, 'Chapter one')
        self.assertEqual((cards[0].start.ordinal, cards[0].end.ordinal),
                         (2000, 6000))
        self.assertEqual(cards[1].text, 'Chapter two')
        self.assertEqual((cards[1].start.ordinal, cards[1].end.ordinal),
                         (6000, 10000))

        # chapter cards never overlap an original cue
        for card in cards:
            for cue in self.subs:
                self.assertTrue(card.end <= cue.start
                                or card.start >= cue.end)

    def test_original_file_untouched(self):
        place_chapters(self.subs, ['Chapter one'], **self.kwargs)
        self.assertEqual(len(self.subs), 3)
        self.assertEqual([item.index for item in self.subs], [1, 2, 3])
        self.assertEqual([item.text for item in self.subs],
                         ['First line', 'Second line, overlaps the first',
                          'Third line'])
        self.assertEqual(self.subs[0].start.ordinal, 10000)

    def test_too_many_chapters(self):
        chapters = ['c%d' % i for i in range(10)]
        self.assertRaises(ChapterPlacementError, place_chapters,
                          self.subs, chapters, **self.kwargs)

    def test_unplaced_chapters_reported(self):
        # only the [40,58] gap can hold a 10s card, and only once
        kwargs = dict(self.kwargs, min_display=10000)
        try:
            place_chapters(self.subs, ['fits', 'does not'], **kwargs)
        except ChapterPlacementError as error:
            self.assertEqual(error.unplaced, ['does not'])
        else:
            self.fail('ChapterPlacementError not raised')

    def test_no_gap_at_all(self):
        subs = SubRipFile(items=[SubRipItem(1, 0, 60000, 'wall to wall')])
        self.assertRaises(ChapterPlacementError, place_chapters,
                          subs, ['nowhere to go'], **self.kwargs)

    def test_illegal_min_display(self):
        self.assertRaises(ValueError, place_chapters, self.subs, ['x'],
                          media_duration=60000, min_display=0)

    def test_save_and_reload(self):
        new_file = place_chapters(self.subs, ['Chapter one'], **self.kwargs)
        path = os.path.join(file_path, 'tests', 'static', 'temp-gaps.srt')
        try:
            new_file.save(path)
            reloaded = pysrt.open(path)
        finally:
            if os.path.exists(path):
                os.remove(path)

        self.assertEqual(len(reloaded), 4)
        self.assertEqual([item.index for item in reloaded], [1, 2, 3, 4])
        self.assertEqual(reloaded[0].text, 'Chapter one')
        self.assertEqual((reloaded[0].start.ordinal,
                          reloaded[0].end.ordinal), (2000, 6000))
        self.assertEqual(reloaded[1].text, 'First line')


if __name__ == '__main__':
    unittest.main()
