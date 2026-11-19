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

Inline styles (i, b, u, font)
=============================

Cue text can contain inline tags such as ``<i>``, ``<b>``, ``<u>`` and
``<font color="#ff0000">``. The ``styled_text`` property exposes them as an
ordered list of fragments: each fragment holds its plain text, the nested
``Style`` stack (outermost first) and its position in the raw cue text. ::

    >>> item = SubRipItem(1, text='<i>Alice:</i> <font color="#ff0000">Hi</font>')
    >>> styled = item.styled_text
    >>> styled.plain_text
    'Alice: Hi'
    >>> fragment = styled.fragments[0]
    >>> fragment.text, fragment.styles
    ('Alice:', (Style('i', {}, valid=True),))
    >>> styled.style_ranges  # (plain_start, plain_end, styles) tuples
    [(0, 6, (Style('i', {}, valid=True),)), (6, 7, ()), ...]

Fragments are editable. Write the result back through ``to_string()``;
untouched text is always serialized byte for byte identical to the original. ::

    >>> fragment.text = 'Bob:'
    >>> item.text = item.styled_text.to_string()
    >>> item.text
    '<i>Bob:</i> <font color="#ff0000">Hi</font>'

Malformed markup (cross closing, stray or unclosed tags, unknown tags, bad
font colors) is preserved verbatim and listed in ``styled_text.errors``.
Pass ``strict=True`` to ``SubRipText`` to raise ``InvalidMarkup`` instead.
The legacy ``item.text`` and ``item.text_without_tags`` APIs keep working
unchanged.
