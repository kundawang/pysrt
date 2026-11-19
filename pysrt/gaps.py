# -*- coding: utf-8 -*-
"""
Subtitle gap planning.

Find unoccupied time windows in a SubRipFile (e.g. to insert chapter
cards between dialogue lines) and optionally place chapter hints into
those windows without touching the original cues.
"""
from collections import namedtuple
from copy import copy

from pysrt.srtexc import Error
from pysrt.srtfile import SubRipFile
from pysrt.srtitem import SubRipItem
from pysrt.srttime import SubRipTime
from pysrt.compat import basestring, str


class ChapterPlacementError(Error):
    """
    Raised when not every chapter hint could be placed into a gap.

    The ``unplaced`` attribute holds the list of chapter texts that
    found no suitable gap.
    """
    def __init__(self, unplaced):
        super(ChapterPlacementError, self).__init__(
            'No suitable gap for chapters: %s' % ', '.join(unplaced))
        self.unplaced = list(unplaced)


class Gap(namedtuple('Gap', ('start', 'end'))):
    """
    An unoccupied time window, as a pair of SubRipTime.
    """
    __slots__ = ()

    @property
    def duration(self):
        return self.end - self.start


def _to_ordinal(value, name):
    try:
        return SubRipTime.coerce(value).ordinal
    except (TypeError, ValueError):
        raise ValueError('%s is not coercible to a time: %r' % (name, value))


def _validate_window(media_duration, min_gap, head_margin, tail_margin):
    duration = _to_ordinal(media_duration, 'media_duration')
    min_gap = _to_ordinal(min_gap, 'min_gap')
    head = _to_ordinal(head_margin, 'head_margin')
    tail = _to_ordinal(tail_margin, 'tail_margin')

    if duration <= 0:
        raise ValueError('media_duration must be positive')
    if min_gap < 0:
        raise ValueError('min_gap must not be negative')
    if head < 0 or tail < 0:
        raise ValueError('head_margin and tail_margin must not be negative')
    if head + tail >= duration:
        raise ValueError('head_margin + tail_margin must be smaller than '
                         'media_duration')
    return duration, min_gap, head, tail


def _merged_occupancy(subtitles, duration):
    """
    Merge every cue of `subtitles` into a sorted list of non overlapping
    (start, end) ordinal intervals, clamped to [0, duration].

    Zero-length cues and cues fully outside the media bounds are ignored.
    """
    intervals = []
    for item in subtitles:
        start = max(0, item.start.ordinal)
        end = min(duration, item.end.ordinal)
        if end > start:
            intervals.append((start, end))
    intervals.sort()

    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def find_gaps(subtitles, media_duration, min_gap=0, head_margin=0,
              tail_margin=0):
    """
    find_gaps(subtitles, media_duration, min_gap, head_margin, \
tail_margin) -> list of Gap

    Merge every occupied cue interval of `subtitles` (a SubRipFile) and
    return the ordered unoccupied windows inside the media timeline,
    restricted to [head_margin, media_duration - tail_margin] and at
    least `min_gap` long.

    All time arguments accept anything coercible to SubRipTime
    (milliseconds int, "HH:MM:SS,mmm" string, dict, tuple...).

    Overlapping cues are merged, negative times are clamped to zero and
    cues overflowing the media duration are clamped to it. Raises
    ValueError on non positive duration, negative margins or min_gap, or
    margins that together cover the whole media.
    """
    duration, min_gap, head, tail = _validate_window(
        media_duration, min_gap, head_margin, tail_margin)

    window_start = head
    window_end = duration - tail

    gaps = []
    cursor = window_start
    for start, end in _merged_occupancy(subtitles, duration):
        if end <= window_start:
            continue
        if start >= window_end:
            break
        if start > cursor:
            gaps.append(Gap(SubRipTime.from_ordinal(cursor),
                            SubRipTime.from_ordinal(min(start, window_end))))
        cursor = max(cursor, end)
    if cursor < window_end:
        gaps.append(Gap(SubRipTime.from_ordinal(cursor),
                        SubRipTime.from_ordinal(window_end)))

    return [gap for gap in gaps if gap.duration.ordinal >= min_gap]


def _normalize_chapter(chapter):
    if isinstance(chapter, dict):
        return str(chapter['text']), int(chapter.get('priority', 0))
    if isinstance(chapter, (tuple, list)):
        text = str(chapter[0])
        priority = int(chapter[1]) if len(chapter) > 1 else 0
        return text, priority
    if isinstance(chapter, basestring):
        return str(chapter), 0
    raise ValueError('Unsupported chapter hint: %r' % (chapter,))


def place_chapters(subtitles, chapters, media_duration, min_display,
                   min_gap=0, head_margin=0, tail_margin=0):
    """
    place_chapters(subtitles, chapters, media_duration, min_display, ...) \
-> SubRipFile

    Greedily place chapter hints into the gaps of `subtitles` and return
    a new SubRipFile combining copies of the original cues and the new
    chapter cues, sorted and re-indexed from 1. The original SubRipFile
    is left unchanged.

    `chapters` is an iterable of hints, each either a text string, a
    (text, priority) tuple or a {'text': ..., 'priority': ...} dict.
    Hints with a higher priority are placed first; each is put at the
    start of the earliest gap that can still hold `min_display`
    milliseconds, never overlapping an original cue.

    Raises ChapterPlacementError (with the offending texts in its
    `unplaced` attribute) when some hints fit in no remaining gap, and
    ValueError on illegal margins or a non positive min_display.
    """
    min_display = _to_ordinal(min_display, 'min_display')
    if min_display <= 0:
        raise ValueError('min_display must be positive')

    gaps = find_gaps(subtitles, media_duration, min_gap=min_gap,
                     head_margin=head_margin, tail_margin=tail_margin)
    # mutable [start, end] ordinals, consumed from the left
    slots = [[gap.start.ordinal, gap.end.ordinal] for gap in gaps]

    normalized = [_normalize_chapter(chapter) for chapter in chapters]
    # higher priority first, stable for equal priorities
    ordered = sorted(enumerate(normalized),
                     key=lambda pair: (-pair[1][1], pair[0]))

    placed = []
    unplaced = []
    for _, (text, _priority) in ordered:
        for slot in slots:
            if slot[1] - slot[0] >= min_display:
                placed.append(SubRipItem(
                    index=0,
                    start=SubRipTime.from_ordinal(slot[0]),
                    end=SubRipTime.from_ordinal(slot[0] + min_display),
                    text=text))
                slot[0] += min_display
                break
        else:
            unplaced.append(text)

    if unplaced:
        raise ChapterPlacementError(unplaced)

    items = [copy(item) for item in subtitles] + placed
    new_file = SubRipFile(items=items, eol=subtitles.eol,
                          encoding=subtitles.encoding)
    new_file.clean_indexes()
    return new_file
