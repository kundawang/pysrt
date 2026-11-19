# -*- coding: utf-8 -*-
"""
Inline style fragment support for SubRip text.

SRT cues may carry inline HTML-like styling tags, the most common being
``<i>``, ``<b>``, ``<u>`` and ``<font color="#ff0000">``. This module parses
a raw cue text into an ordered, possibly nested, sequence of
:class:`Fragment` objects while keeping the original byte layout reachable
through :class:`TextToken` / :class:`TagToken`.

Design rules
------------

* Known tags: ``i``, ``b``, ``u`` and ``font`` (with attributes). Every other
  tag is *unknown*: it is preserved verbatim on round trip but contributes no
  style.
* The parser is forgiving by default: cross closing, stray closing and
  unclosed tags are repaired (HTML style) and reported in
  :attr:`SubRipText.errors`; nothing is dropped. Pass ``strict=True`` to
  raise :class:`~pysrt.srtexc.InvalidMarkup` instead.
* A fragment that was not edited serializes back to its exact original
  characters, so untouched cue text is byte for byte identical.
* Text is stored decoded (HTML entities are resolved); tags keep their raw
  form in their token and are only regenerated when text is edited.
"""

import re

from pysrt.compat import str, is_py2
from pysrt.srtexc import InvalidMarkup

if is_py2:
    unichr = unichr  # noqa: F821
else:
    unichr = chr


#: Tags that produce a :class:`Style`.
KNOWN_TAGS = ('i', 'b', 'u', 'font')

#: Acceptable color values: ``#rgb``, ``#rgba``, ``#rrggbb``, ``#rrggbbaa``
#: and a whitelist of the named CSS colors used by players.
NAMED_COLORS = frozenset((
    'aqua', 'black', 'blue', 'fuchsia', 'gray', 'grey', 'green', 'lime',
    'maroon', 'navy', 'olive', 'orange', 'purple', 'red', 'silver',
    'teal', 'white', 'yellow',
))
COLOR_PATTERN = re.compile(r'#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$')

TAG_RE = re.compile(r'<\s*/?\s*([a-zA-Z][\w:-]*)((?:[^<>"\']|"[^"]*"|\'[^\']*\')*?)(/?)>')
ATTR_RE = re.compile(
    r"""([\w:-]+)\s*(?:=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?"""
)

# Entities players actually emit in SRT files. Everything else is left
# untouched on read, and only bare ``&`` are escaped on regeneration.
_NAMED_ENTITIES = {
    'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'",
    'nbsp': u' ',
}


def decode_entities(text):
    """decode_entities(text) -> unicode

    Resolve ``&amp;``/``&#39;``/``&#x27;`` style entities. Unknown named
    entities are returned unchanged.
    """
    def _replace(match):
        body = match.group(1)
        if body.startswith('#'):
            try:
                if body[1:2] in ('x', 'X'):
                    return unichr(int(body[2:], 16))
                return unichr(int(body[1:]))
            except (ValueError, OverflowError):
                return match.group(0)
        return _NAMED_ENTITIES.get(body.lower(), match.group(0))

    return re.sub(r'&(#?\w+);', _replace, text)


def encode_entities(text):
    """encode_entities(text) -> unicode

    Escape the characters that must not appear raw inside tagged text.
    Already escaped entities (``&amp;`` and friends) are not double escaped.
    """
    text = re.sub(r'&(?!#?\w+;)', '&amp;', text)
    return text.replace('<', '&lt;').replace('>', '&gt;')


def _tokenize(raw):
    """Split *raw* into :class:`TextToken` / :class:`TagToken` objects.

    Anything that does not match a well formed tag is text, including a
    lone ``<`` or an unterminated ``<b``: markup is never guessed.
    """
    tokens = []
    pos = 0
    for match in TAG_RE.finditer(raw):
        if match.start() > pos:
            tokens.append(TextToken(raw[pos:match.start()], pos, match.start()))
        tokens.append(TagToken(match))
        pos = match.end()
    if pos < len(raw):
        tokens.append(TextToken(raw[pos:], pos, len(raw)))
    return tokens


class Style(object):
    """
    Style(tag, attributes=None, valid=True)

    A single inline style layer, e.g. ``<i>`` or
    ``<font color="#ff0000">``.

    tag -> unicode: normalized lower case tag name (``'i'``, ``'font'``...).
    attributes -> dict: tag attributes, keys lower cased, values decoded.
    valid -> bool: False when an attribute value (currently the font color)
        is not recognized. The raw tag is still preserved on round trip.
    """

    def __init__(self, tag, attributes=None, valid=True):
        self.tag = str(tag)
        self.attributes = dict(attributes or {})
        self.valid = valid

    @property
    def color(self):
        """The font color, or ``None`` for non font / colorless tags."""
        return self.attributes.get('color')

    @property
    def italic(self):
        return self.tag == 'i'

    @property
    def bold(self):
        return self.tag == 'b'

    @property
    def underline(self):
        return self.tag == 'u'

    def __eq__(self, other):
        if not isinstance(other, Style):
            return NotImplemented
        return (self.tag == other.tag
                and self.attributes == other.attributes
                and self.valid == other.valid)

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __repr__(self):
        return 'Style(%r, %r, valid=%r)' % (self.tag, self.attributes,
                                            self.valid)


class Fragment(object):
    """
    A maximal run of plain text sharing the same style stack.

    text -> unicode: entity decoded text, editable. Assigning a new value
        marks the owning :class:`SubRipText` as modified.
    styles -> tuple of :class:`Style`: outermost first.
    start, end -> int: raw positions (offsets in the original cue text) of
        the text run, tags excluded.
    plain_start, plain_end -> int: positions in :attr:`SubRipText.plain_text`.
    """

    def __init__(self, text, styles, start, end, plain_start, plain_end,
                 token=None):
        self._text = text
        self.styles = tuple(styles)
        self.start = start
        self.end = end
        self.plain_start = plain_start
        self.plain_end = plain_end
        self._token = token

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = str(value)
        if self._token is not None:
            self._token.text = value

    def __repr__(self):
        return 'Fragment(%r, %r, %d:%d)' % (self._text, self.styles,
                                            self.start, self.end)

    def __eq__(self, other):
        if not isinstance(other, Fragment):
            return NotImplemented
        return (self._text == other._text and self.styles == other.styles
                and self.start == other.start and self.end == other.end)

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result


class TextToken(object):
    """A raw text run between tags.

    ``raw`` keeps the un-decoded original bytes so an untouched cue is
    serialized identically. Once :attr:`text` is assigned (through a
    :class:`Fragment`) the token is marked modified and the new value is
    entity encoded on output.
    """

    def __init__(self, raw, start, end):
        self.raw = raw
        self.start = start
        self.end = end
        self.modified = False
        self._text = decode_entities(raw)

    @property
    def text(self):
        if self.modified:
            return encode_entities(self._text)
        return self.raw

    @text.setter
    def text(self, value):
        self._text = str(value)
        self.modified = True


class TagToken(object):
    """A single ``<...>`` tag, kept verbatim for round trip."""

    def __init__(self, match):
        self.raw = match.group(0)
        self.start = match.start()
        self.end = match.end()
        self.closing = match.group(0).lstrip('<').lstrip().startswith('/')
        self.self_closing = bool(match.group(3))
        self.name = match.group(1).lower()
        self.attributes, self.attr_error = self._parse_attributes(
            match.group(2))

    @staticmethod
    def _parse_attributes(blob):
        attributes = {}
        error = None
        if not blob or not blob.strip():
            return attributes, error
        consumed = 0
        for attr_match in ATTR_RE.finditer(blob):
            if blob[consumed:attr_match.start()].strip():
                error = 'unparseable attribute: %r' % blob.strip()
                break
            name = attr_match.group(1).lower()
            value = attr_match.group(2)
            if value is None:
                value = attr_match.group(3)
            if value is None:
                value = attr_match.group(4)
            if value is None:
                value = ''
            attributes[name] = decode_entities(value)
            consumed = attr_match.end()
        if error is None and blob[consumed:].strip():
            error = 'unparseable attribute: %r' % blob.strip()
        return attributes, error

    @property
    def known(self):
        return self.name in KNOWN_TAGS

    @property
    def text(self):
        return self.raw


class SubRipText(object):
    """
    SubRipText(raw, strict=False)

    Parsed view of a cue text. Build it directly or, more conveniently,
    through :attr:`pysrt.SubRipItem.styled_text`.

    raw -> unicode: the original cue text.
    strict -> bool: when True, raise :class:`InvalidMarkup` on the first
        structural or attribute error instead of collecting it.
    """

    def __init__(self, raw='', strict=False):
        self.raw = str(raw)
        self.strict = strict
        self.tokens = []
        self.fragments = []
        self.errors = []
        self._plain_parts = []
        self._build()

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #
    def _fail(self, error):
        self.errors.append(error)
        if self.strict:
            raise InvalidMarkup(str(error), errors=list(self.errors))

    def _build(self):
        self.tokens = _tokenize(self.raw)
        # Stack entries: (TagToken, Style or None). Unknown tags carry a
        # None style but still participate in open/close matching so that
        # nesting order is preserved.
        stack = []
        plain_offset = 0

        for token in self.tokens:
            if isinstance(token, TextToken):
                decoded = decode_entities(token.raw)
                if decoded:
                    styles = tuple(style for _, style in stack if style)
                    fragment = Fragment(
                        decoded, styles, token.start, token.end,
                        plain_offset, plain_offset + len(decoded), token)
                    self.fragments.append(fragment)
                    plain_offset += len(decoded)
                    self._plain_parts.append(decoded)
                continue

            if token.attr_error:
                self._fail(InvalidMarkup(
                    '%s at position %d' % (token.attr_error, token.start)))

            if token.closing:
                self._handle_close(token, stack)
                continue

            if token.self_closing:
                # Self closing tags open nothing: e.g. <br/>.
                continue

            style = None
            if token.known:
                style = Style(token.name, token.attributes)
                if (token.name == 'font' and 'color' in token.attributes
                        and not self._valid_color(
                            token.attributes['color'])):
                    style.valid = False
                    self._fail(InvalidMarkup(
                        'bad color value %r at position %d'
                        % (token.attributes['color'], token.start)))
            stack.append((token, style))

        for token, _style in stack:
            self._fail(InvalidMarkup(
                'unclosed tag %r opened at position %d'
                % (token.raw, token.start)))

    @staticmethod
    def _valid_color(value):
        if not value:
            return False
        if value.lower() in NAMED_COLORS:
            return True
        return bool(COLOR_PATTERN.match(value))

    def _handle_close(self, token, stack):
        for depth in range(len(stack) - 1, -1, -1):
            if stack[depth][0].name == token.name:
                for implicit in range(len(stack) - 1, depth, -1):
                    opened = stack[implicit][0]
                    self._fail(InvalidMarkup(
                        'cross closing: %r at position %d implicitly closes '
                        '%r opened at position %d'
                        % (token.raw, token.start, opened.raw,
                           opened.start)))
                del stack[depth:]
                return
        self._fail(InvalidMarkup(
            'stray closing tag %r at position %d' % (token.raw, token.start)))

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def plain_text(self):
        """The text with every tag and entity encoding removed."""
        return ''.join(self._plain_parts)

    @property
    def style_ranges(self):
        """
        List of ``(plain_start, plain_end, styles_tuple)`` tuples, one per
        non empty fragment, ordered like the text.
        """
        return [(fragment.plain_start, fragment.plain_end, fragment.styles)
                for fragment in self.fragments]

    @property
    def modified(self):
        """True once a fragment text has been edited."""
        return any(token.modified for token in self.tokens
                   if isinstance(token, TextToken))

    def to_string(self):
        """
        Serialize back to SRT text. When nothing was edited the original
        raw string is returned unchanged; otherwise the token stream is
        re-emitted with the edited (re-encoded) text runs.
        """
        if not self.modified:
            return self.raw
        return ''.join(token.text for token in self.tokens)

    def __str__(self):
        return self.to_string()

    if is_py2:
        __unicode__ = __str__

        def __str__(self):
            raise NotImplementedError('Use unicode() instead!')

    def __eq__(self, other):
        if not isinstance(other, SubRipText):
            return NotImplemented
        return self.to_string() == other.to_string()

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result
