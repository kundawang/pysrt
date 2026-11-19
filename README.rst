pysrt
=============

pysrt is a Python library used to edit or create SubRip files.

.. image:: https://secure.travis-ci.org/byroot/pysrt.png?branch=master
  :target: http://travis-ci.org/byroot/pysrt
.. image:: https://coveralls.io/repos/byroot/pysrt/badge.png?branch=master
  :target: https://coveralls.io/r/byroot/pysrt?branch=master
.. image:: https://img.shields.io/pypi/v/pysrt.svg
  :target: https://crate.io/packages/pysrt/

Foreword
====================

pysrt is mainly designed as a library, but if you are experiencing troubles
with bad subtitles you can first try to use `ruby-osdb <https://github.com/byroot/ruby-osdb>`_
which will try to find the best subtitle for your movie. If you are still unlucky
pysrt also provide an ``srt`` command useful for either shift, split, or rescale a
*.srt* file.

Command Usage
=====================

Shifting: ::
  
    $ srt -i shift 2s500ms movie.srt

Spliting: ::

    $ srt split 58m26s movie.srt

Rescaling: ::

    $ srt -i rate 23.9 25 movie.srt

Installation
=================

pysrt is available on pypi. To install it you can use either

pip: ::
    
    $ sudo pip install pysrt
    
or distutils: ::

    $ sudo easy_install pysrt


It is compatible with python >= 2.6 and 3.


Library Usage
=============

Import: ::

    >>> import pysrt
    
Parsing: ::

    >>> subs = pysrt.open('some/file.srt')
    # If you get a UnicodeDecodeError try to specify the encoding
    >>> subs = pysrt.open('some/file.srt', encoding='iso-8859-1')
    
SubRipFile are list-like objects of SubRipItem instances: ::
    
    >>> len(subs)
    >>> first_sub = subs[0]
    
SubRipItem instances are editable just like pure Python objects: ::
    
    >>> first_sub.text = "Hello World !"
    >>> first_sub.start.seconds = 20
    >>> first_sub.end.minutes = 5
    
Shifting: ::

    >>> subs.shift(seconds=-2) # Move all subs 2 seconds earlier
    >>> subs.shift(minutes=1)  # Move all subs 1 minutes later
    >>> subs.shift(ratio=25/23.9) # convert a 23.9 fps subtitle in 25 fps
    >>> first_sub.shift(seconds=1) # Move the first sub 1 second later
    >>> first_sub.start += {'seconds': -1} # Make the first sub start 1 second earlier
    
Removing: ::
    
    >>> del subs[12]
    
Slicing: ::
    
    >>> part = subs.slice(starts_after={'minutes': 2, 'seconds': 30}, ends_before={'minutes': 3, 'seconds': 40})
    >>> part.shift(seconds=-2)
    
Saving changes: ::
    
    >>> subs.save('other/path.srt', encoding='utf-8')

SMPTE timecodes
===============

Subtitles can be exchanged with editors and NLEs as SMPTE timecodes.
``SubRipTime`` converts to and from ``HH:MM:SS:FF`` (non drop-frame) and
``HH:MM:SS;FF`` (drop-frame). Supported rates are 24, 25, 30 and 30000/1001
(29.97). ::

    >>> from pysrt import SubRipTime
    >>> SubRipTime(1, 0, 0, 0).to_timecode(25)
    '01:00:00:00'
    >>> SubRipTime(1, 0, 0, 0).to_timecode('30000/1001')
    '01:00:00;00'
    >>> SubRipTime.from_timecode('01:00:00:00', 25)
    SubRipTime(1, 0, 0, 0)

A :class:`pysrt.FrameRate` can be passed instead of a raw rate; it carries
the drop-frame flag and the matching separator. Rates may be given as
``24``, ``25``, ``30``, ``30000/1001``, ``29.97`` or a ``Fraction``. ::

    >>> from pysrt import FrameRate
    >>> FrameRate('30000/1001').timecode_separator
    ';'

Whole files export and import as ``(start, end)`` timecode pairs, keeping
file order and frame-accurate durations: ::

    >>> exported = subs.to_timecodes(25)
    >>> exported[0]
    ('01:00:00:00', '01:00:02:00')
    >>> subs.from_timecodes(exported, 25)  # updates subs in place

Frame conversion rules, stated explicitly:

* **Rounding to a frame.** ``SubRipTime`` values are rounded to the nearest
  frame; an exact half-frame gap rounds to the later frame. Millisecond
  values that do not land on a frame are snapped to the closest frame, never
  truncated or rejected.
* **Rounding to a millisecond.** Reading a timecode rounds to the nearest
  millisecond, ties upwards. SubRip itself only stores milliseconds, so a
  timecode finer than that cannot be represented exactly, but re-exporting
  the stored value reproduces the original timecode.
* **Invalid frames.** A frame field greater than or equal to the rate
  (``00:00:00:24`` at 24 fps, ``00:00:00:30`` at 30) raises
  ``InvalidTimecode``, as do out of range minutes/seconds and hours >= 24.
* **Skipped drop-frame codes.** ``HH:MM:00;00`` and ``HH:MM:00;01`` for
  minutes that are not multiples of ten do not exist in drop-frame counting;
  they raise ``DroppedFrameCode`` (a subclass of ``InvalidTimecode``).
* **Separators must match.** ``:`` before frames means non drop-frame and
  ``;`` means drop-frame; mixing them raises ``InvalidTimecode``.
* **Negative times.** SRT can hold negative offsets internally but they have
  no timecode; converting one raises ``InvalidTimecode``. ``str()`` on a
  negative ``SubRipTime`` still clamps to zero as before.
* **24 hour wrap.** Timecodes are 24 hour cyclic. ``to_timecode`` raises
  ``InvalidTimecode`` at or beyond 24 hours rather than wrapping silently;
  pass ``wrap=True`` to take the time modulo 24 hours (``24:00:00,000``
  becomes ``00:00:00:00`` at every rate, drop-frame included).
  ``SubRipFile.to_timecodes(rate, wrap=True)`` applies the same rule to a
  whole file.
* **Frame rates.** Non finite (``nan``/``inf``) or unsupported rates raise
  ``InvalidFrameRate``, a ``ValueError`` subclass. ``InvalidTimecode`` is a
  subclass of the existing ``InvalidTimeString``.

Drop-frame timecodes count at 30000/1001 fps, so an exact timecode such as
``01:00:00;00`` is a touch less than one hour of wall time (3599996 ms). That
drift is inherent to 29.97 and is preserved by the conversion.
