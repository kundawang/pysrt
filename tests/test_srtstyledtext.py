#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import unittest

file_path = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, os.path.abspath(file_path))

from pysrt import SubRipItem, SubRipText, Style, Fragment, InvalidMarkup
from pysrt.srtstyledtext import decode_entities, encode_entities
from pysrt.compat import str


class TestFragmentParsing(unittest.TestCase):

    def test_simple_italic(self):
        styled = SubRipText('<i>Hello</i>')
        self.assertEqual(len(styled.fragments), 1)
        fragment = styled.fragments[0]
        self.assertEqual(fragment.text, 'Hello')
        self.assertEqual(fragment.styles, (Style('i'),))
        self.assertTrue(fragment.styles[0].italic)
        self.assertEqual((fragment.start, fragment.end), (3, 8))
        self.assertEqual((fragment.plain_start, fragment.plain_end), (0, 5))

    def test_bold_underline(self):
        styled = SubRipText('<b>bold</b> plain <u>under</u>')
        self.assertEqual(
            [f.text for f in styled.fragments],
            ['bold', ' plain ', 'under'])
        self.assertTrue(styled.fragments[0].styles[0].bold)
        self.assertTrue(styled.fragments[2].styles[0].underline)
        self.assertEqual(styled.fragments[1].styles, ())

    def test_font_color(self):
        styled = SubRipText('<font color="#ff0000">red</font>')
        style = styled.fragments[0].styles[0]
        self.assertEqual(style.tag, 'font')
        self.assertEqual(style.color, '#ff0000')
        self.assertTrue(style.valid)

    def test_nested_styles_outermost_first(self):
        styled = SubRipText('<b>one,<i>two,<u>three</u></i></b>')
        self.assertEqual(
            [f.styles for f in styled.fragments],
            [
                (Style('b'),),
                (Style('b'), Style('i')),
                (Style('b'), Style('i'), Style('u')),
            ])
        # text order is preserved through nesting
        self.assertEqual(styled.plain_text, 'one,two,three')

    def test_multiline_keeps_order_and_newlines(self):
        raw = '<i>Alice:</i> line one\n<font color="#00ff00">line two\n' \
              'line three</font>'
        styled = SubRipText(raw)
        self.assertEqual(
            styled.plain_text,
            'Alice: line one\nline two\nline three')
        joined = ''.join(f.text for f in styled.fragments)
        self.assertEqual(joined, styled.plain_text)
        # every raw position points at the fragment's own text
        for fragment in styled.fragments:
            self.assertEqual(
                styled.raw[fragment.start:fragment.end], fragment.text)

    def test_mixed_italic_color_newline_cue(self):
        raw = '<i>Bob:</i>\n<font color="#ff0000">red\nblue</font> tail'
        styled = SubRipText(raw)
        self.assertEqual(len(styled.fragments), 4)
        self.assertEqual(styled.fragments[0].styles[0].tag, 'i')
        self.assertEqual(styled.fragments[2].styles[0].color, '#ff0000')
        self.assertEqual(styled.fragments[2].text, 'red\nblue')
        self.assertEqual(styled.fragments[3].styles, ())
        self.assertEqual(
            styled.plain_text, 'Bob:\nred\nblue tail')

    def test_plain_positions_are_contiguous(self):
        styled = SubRipText('a<b>b</b>c<i>d</i>')
        cursor = 0
        for fragment in styled.fragments:
            self.assertEqual(fragment.plain_start, cursor)
            self.assertEqual(fragment.plain_end,
                             cursor + len(fragment.text))
            cursor = fragment.plain_end
        self.assertEqual(cursor, len(styled.plain_text))

    def test_style_ranges(self):
        styled = SubRipText('<b>a</b>b')
        ranges = styled.style_ranges
        self.assertEqual(ranges[0][0:2], (0, 1))
        self.assertEqual(ranges[0][2], (Style('b'),))
        self.assertEqual(ranges[1], (1, 2, ()))


class TestRoundTrip(unittest.TestCase):

    def test_unmodified_is_byte_identical(self):
        samples = [
            '<i>Hello</i>',
            '<b>Bold</b>, <i>italic</i>, <u>underlined</u>\n'
            '<font color="#ff0000">red text</font>',
            '<b>one,<i> two,<u> three</u></i></b>',
            'plain text without any tag',
            '<FONT COLOR="#FF0000">upper case</FONT>',
            'lone < bracket and <unclosed tag',
        ]
        for raw in samples:
            styled = SubRipText(raw)
            self.assertEqual(styled.to_string(), raw)
            self.assertFalse(styled.modified)

    def test_edit_fragment_and_write_back(self):
        raw = '<i>Alice:</i> <font color="#ff0000">Hello</font>'
        styled = SubRipText(raw)
        styled.fragments[0].text = 'Bob:'
        styled.fragments[2].text = 'Goodbye'
        self.assertTrue(styled.modified)
        output = styled.to_string()
        self.assertEqual(
            output,
            '<i>Bob:</i> <font color="#ff0000">Goodbye</font>')

    def test_edited_output_reads_back(self):
        raw = '<i>Alice:</i> <b>Hello</b>'
        styled = SubRipText(raw)
        # fragments: ['Alice:'(i), ' '(), 'Hello'(b)]
        styled.fragments[2].text = 'Hi'
        reread = SubRipText(styled.to_string())
        self.assertEqual(reread.plain_text, 'Alice: Hi')
        self.assertEqual(reread.fragments[0].styles, (Style('i'),))
        self.assertEqual(reread.fragments[2].styles, (Style('b'),))

    def test_item_integration_write_back(self):
        item = SubRipItem(1, text='<i>Alice:</i> Hello')
        item.styled_text.fragments[0].text = 'Bob:'
        item.text = item.styled_text.to_string()
        self.assertEqual(item.text, '<i>Bob:</i> Hello')
        # the styled view is rebuilt from the new raw text
        self.assertEqual(item.styled_text.plain_text, 'Bob: Hello')

    def test_item_unmodified_serialization_unchanged(self):
        raw = '1\n00:01:00,000 --> 00:01:20,000\n<i>Hello</i> world\n'
        item = SubRipItem.from_string(raw)
        self.assertEqual(str(item), raw)
        # touching the styled view must not change the text
        self.assertEqual(item.styled_text.to_string(), '<i>Hello</i> world')
        self.assertEqual(str(item), raw)

    def test_text_setter_resets_styled_view(self):
        item = SubRipItem(1, text='<i>old</i>')
        first = item.styled_text
        item.text = '<b>new</b>'
        self.assertIsNot(item.styled_text, first)
        self.assertEqual(item.styled_text.plain_text, 'new')
        self.assertEqual(item.styled_text.fragments[0].styles,
                         (Style('b'),))

    def test_text_without_tags_backward_compatible(self):
        item = SubRipItem(1, text='<b>Bold</b>, <i>it</i>\n'
                                  '<font color="#ff0000">red</font>')
        self.assertEqual(item.text_without_tags, 'Bold, it\nred')


class TestMalformedMarkup(unittest.TestCase):

    def test_cross_closing_is_repaired_and_reported(self):
        raw = '<b>one,<i>two</b>three</i>'
        styled = SubRipText(raw)
        # nothing dropped: order and bytes preserved
        self.assertEqual(styled.plain_text, 'one,twothree')
        self.assertEqual(styled.to_string(), raw)
        self.assertTrue(any('cross closing' in str(e)
                            for e in styled.errors))
        # after the repair '</i>' has nothing left to close
        self.assertTrue(any('stray closing' in str(e)
                            for e in styled.errors))

    def test_stray_closing_tag(self):
        styled = SubRipText('hello</i> world')
        self.assertEqual(styled.plain_text, 'hello world')
        self.assertTrue(any('stray closing' in str(e)
                            for e in styled.errors))
        self.assertEqual(styled.to_string(), 'hello</i> world')

    def test_unclosed_tag(self):
        raw = '<i>never closed'
        styled = SubRipText(raw)
        self.assertEqual(styled.plain_text, 'never closed')
        self.assertTrue(any('unclosed' in str(e) for e in styled.errors))
        self.assertEqual(styled.to_string(), raw)

    def test_unknown_tag_preserved_without_style(self):
        styled = SubRipText('<weird attr="x">kept</weird> tail')
        self.assertEqual(styled.plain_text, 'kept tail')
        for fragment in styled.fragments:
            self.assertEqual(fragment.styles, ())
        self.assertEqual(styled.to_string(),
                         '<weird attr="x">kept</weird> tail')
        self.assertEqual(styled.errors, [])

    def test_bad_color_marked_invalid_but_kept(self):
        raw = '<font color="zzz">text</font>'
        styled = SubRipText(raw)
        style = styled.fragments[0].styles[0]
        self.assertFalse(style.valid)
        self.assertEqual(style.color, 'zzz')
        self.assertTrue(any('bad color' in str(e)
                            for e in styled.errors))
        self.assertEqual(styled.to_string(), raw)

    def test_valid_color_forms(self):
        for color in ('#f00', '#ff0000', '#ff0000ff', '#f00f', 'red'):
            styled = SubRipText(
                '<font color="%s">x</font>' % color)
            self.assertTrue(styled.fragments[0].styles[0].valid, color)
            self.assertEqual(styled.errors, [])

    def test_strict_mode_raises_with_error_list(self):
        for raw in ('<b>oops', 'oops</b>', '<b>a<i>b</b>c</i>',
                    '<font color="nope">x</font>'):
            with self.assertRaises(InvalidMarkup) as context:
                SubRipText(raw, strict=True)
            self.assertTrue(context.exception.errors)

    def test_strict_mode_accepts_clean_markup(self):
        styled = SubRipText('<i>a</i><b>b</b>', strict=True)
        self.assertEqual(styled.errors, [])


class TestEntities(unittest.TestCase):

    def test_decode_named_decimal_hex(self):
        self.assertEqual(decode_entities('&amp; &lt; &gt; &quot; &apos;'),
                         '& < > " \'')
        self.assertEqual(decode_entities('&#65;&#x42;'), 'AB')

    def test_unknown_entity_left_untouched(self):
        self.assertEqual(decode_entities('&unknown;'), '&unknown;')
        styled = SubRipText('&unknown; <i>x</i>')
        self.assertEqual(styled.plain_text, '&unknown; x')
        self.assertEqual(styled.to_string(), '&unknown; <i>x</i>')

    def test_edit_re_encodes_special_chars(self):
        styled = SubRipText('<i>x</i>')
        styled.fragments[0].text = 'a & b < c > d'
        output = styled.to_string()
        self.assertEqual(output, '<i>a &amp; b &lt; c &gt; d</i>')
        self.assertEqual(SubRipText(output).plain_text,
                         'a & b < c > d')

    def test_existing_entities_not_double_escaped_when_untouched(self):
        raw = 'a &amp; b &#60; c'
        self.assertEqual(SubRipText(raw).to_string(), raw)


class TestEmptyAndEdgeCases(unittest.TestCase):

    def test_empty_text(self):
        styled = SubRipText('')
        self.assertEqual(styled.fragments, [])
        self.assertEqual(styled.plain_text, '')
        self.assertEqual(styled.to_string(), '')

    def test_empty_tags_produce_no_fragments_but_are_kept(self):
        raw = '<i></i><b></b>hi'
        styled = SubRipText(raw)
        self.assertEqual(len(styled.fragments), 1)
        self.assertEqual(styled.fragments[0].text, 'hi')
        self.assertEqual(styled.to_string(), raw)

    def test_whitespace_only_runs_are_fragments(self):
        styled = SubRipText('<i>a</i>   <b>b</b>')
        self.assertEqual(
            [f.text for f in styled.fragments], ['a', '   ', 'b'])

    def test_lone_angle_bracket_is_text(self):
        raw = '2 < 3 and 5 > 4'
        styled = SubRipText(raw)
        self.assertEqual(styled.fragments[0].styles, ())
        self.assertEqual(styled.plain_text, raw)
        self.assertEqual(styled.to_string(), raw)

    def test_unterminated_tag_treated_as_text(self):
        raw = 'hello <i>there'
        styled = SubRipText(raw)
        # '<i>' is well formed; the genuinely unterminated case:
        raw2 = 'hello <i there'
        styled2 = SubRipText(raw2)
        self.assertEqual(styled2.plain_text, raw2)
        self.assertEqual(styled2.to_string(), raw2)
        self.assertEqual(styled.plain_text, 'hello there')

    def test_self_closing_tag(self):
        raw = 'line one<br/>line two'
        styled = SubRipText(raw)
        self.assertEqual(styled.plain_text, 'line oneline two')
        self.assertEqual(styled.to_string(), raw)
        self.assertEqual(styled.errors, [])

    def test_font_keeps_all_attributes(self):
        raw = '<font color="#ff0000" size="4">big red</font>'
        styled = SubRipText(raw)
        self.assertEqual(
            styled.fragments[0].styles[0].attributes,
            {'color': '#ff0000', 'size': '4'})
        self.assertEqual(styled.to_string(), raw)

    def test_unparseable_attribute_is_kept_and_reported(self):
        raw = '<font color=>x</font>'
        styled = SubRipText(raw)
        self.assertTrue(styled.errors)
        self.assertEqual(styled.to_string(), raw)
        self.assertRaises(InvalidMarkup, SubRipText, raw, True)

    def test_duplicate_same_tag_nesting(self):
        raw = '<i>a<i>b</i>c</i>'
        styled = SubRipText(raw)
        self.assertEqual(styled.plain_text, 'abc')
        self.assertEqual(len(styled.fragments[1].styles), 2)
        self.assertEqual(styled.to_string(), raw)

    def test_crlf_and_unicode_preserved(self):
        raw = u'<i>line1\r\nline2 café 中文</i>'
        styled = SubRipText(raw)
        self.assertEqual(styled.plain_text, u'line1\r\nline2 café 中文')
        self.assertEqual(styled.to_string(), raw)

    def test_unknown_tag_inside_known_tag(self):
        raw = '<i>a<custom>b</custom>c</i>'
        styled = SubRipText(raw)
        self.assertEqual(styled.plain_text, 'abc')
        for fragment in styled.fragments:
            self.assertEqual(fragment.styles, (Style('i'),))
        self.assertEqual(styled.to_string(), raw)


class TestSubRipItemEntryPoints(unittest.TestCase):

    def test_styled_text_type_and_lazy(self):
        item = SubRipItem(1, text='<i>x</i>')
        self.assertIsInstance(item.styled_text, SubRipText)
        self.assertIs(item.styled_text, item.styled_text)

    def test_original_text_unchanged_by_parsing(self):
        raw = '<i>Alice:</i>\n<font color="#ff0000">hi</font>'
        item = SubRipItem(1, text=raw)
        self.assertEqual(item.text, raw)
        self.assertEqual(item.text_without_tags, 'Alice:\nhi')

    def test_full_file_roundtrip_with_styles(self):
        from pysrt import SubRipFile
        source = (
            '1\n00:01:00,000 --> 00:01:20,000\n'
            '<i>Alice:</i> <font color="#ff0000">Hello\nworld</font>\n\n'
            '2\n00:02:00,000 --> 00:02:10,000\n'
            '<b>Bold</b> plain\n')
        parsed = SubRipFile.from_string(source)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(str(parsed[0]),
                         '1\n00:01:00,000 --> 00:01:20,000\n'
                         '<i>Alice:</i> <font color="#ff0000">Hello\n'
                         'world</font>\n')
        # edit a fragment on item 1 and write the whole file back.
        # fragments: ['Alice:'(i), ' '(), 'Hello\nworld'(font)]
        parsed[0].styled_text.fragments[2].text = 'Hi\nthere'
        parsed[0].text = parsed[0].styled_text.to_string()
        self.assertIn('<font color="#ff0000">Hi\nthere</font>',
                      str(parsed[0]))
        # untouched items stay byte identical
        self.assertEqual(parsed[1].text, '<b>Bold</b> plain')
        # write_into owns the inter-item blank lines: full file round trip
        import io
        buffer = io.StringIO()
        parsed.write_into(buffer)
        reread = SubRipFile.from_string(buffer.getvalue())
        self.assertEqual(len(reread), 2)
        self.assertEqual(reread[1].text, '<b>Bold</b> plain')
        self.assertEqual(reread[0].styled_text.plain_text,
                         'Alice: Hi\nthere')


if __name__ == '__main__':
    unittest.main()
