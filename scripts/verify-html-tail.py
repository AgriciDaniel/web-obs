#!/usr/bin/env python3
"""Content after the closing tags is kept, and closing tag text that is not a tag is left alone.

Linux and macOS parsers keep content after </html>, so a normal run there cannot show the loss seen
on Windows. These tests stand in for a parser that drops it: they cut the markup at the first
closing body or html tag before BeautifulSoup sees it. That is an emulation, not the Windows parser.
With TAIL_HELPER=off the helper is replaced by one that changes nothing, and the parser tests fail.
"""
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
import bs4  # noqa: E402
import brand_and_dns  # noqa: E402
import extractor  # noqa: E402
import html_tail  # noqa: E402
import markdown_converter  # noqa: E402

if os.environ.get('TAIL_HELPER') == 'off':
    for module in (extractor, markdown_converter, brand_and_dns):
        module.keep_trailing_content = lambda html: html

keep = html_tail.keep_trailing_content
_FIRST_CLOSER = re.compile(r'</(?:body|html)\s*>', re.I)
_RealSoup = bs4.BeautifulSoup


def _dropping_soup(markup, *args, **kwargs):
    """BeautifulSoup over a parser that ignores everything after the first closing tag."""
    if isinstance(markup, str):
        first = _FIRST_CLOSER.search(markup)
        if first:
            markup = markup[:first.end()]
    return _RealSoup(markup, *args, **kwargs)


PAGE = ('<html><head><title>Tail</title></head><body><h1>Tail</h1><p>Body text for the page.</p></body></html>'
        '<a href="/late-link">Late link</a><img src="/late.png" alt="Late image"><p>Late paragraph text.</p>')


class LeftAsSent(unittest.TestCase):
    """Pages with no real content after their closing tags come back as the same object."""

    CASES = {
        'whitespace': '<html><body><p>x</p></body>\n</html>\n  \n',
        'empty': '',
        'closer only': '</html>',
        'no closers': '<p>x</p>',
        'cache comment': '<html><body>x</body></html>\n<!-- page cached 0.12s -->\n',
        'title': '<html><head><title>Close </body> tags</title></head><body><p>x</p></body></html>',
        'attribute': '<html><body><a title="ends with </html>">x</a></body></html>',
        'single quotes': "<html><body><a title='ends with </html>'>x</a></body></html>",
        'comment': '<html><body><!-- old </body> --><p>x</p></body></html>',
        'script': '<html><head><script>var s="</body></html>";</script></head><body>x</body></html>',
        'style': '<html><head><style>/* </body> */</style></head><body>x</body></html>',
        'textarea': '<html><body><textarea>type </html> here</textarea></body></html>',
        'template': '<html><body><template><div></body></div></template>x</body></html>',
        'srcdoc': '<html><body><iframe srcdoc="<html><body>inner</body></html>"></iframe></body></html>',
        'json-ld': '<html><head><script type="application/ld+json">{"text":"</body>"}</script></head><body>x</body></html>',
    }

    def test_each_case_is_the_same_object(self):
        for name, page in self.CASES.items():
            with self.subTest(name):
                self.assertIs(keep(page), page)

    def test_bytes_are_returned_unchanged(self):
        page = b'<html><body>x</body></html><p>late</p>'
        self.assertIs(keep(page), page)


class MovedInside(unittest.TestCase):
    def test_trailing_content_moves_inside_the_body(self):
        fixed = keep(PAGE)
        self.assertTrue(fixed.endswith('</body></html>'))
        inner = fixed[:-len('</body></html>')]
        self.assertIsNone(_FIRST_CLOSER.search(inner), 'no closing tag before the end')
        self.assertIn('<a href="/late-link">Late link</a>', inner)

    def test_closing_tags_in_any_case_and_spacing(self):
        self.assertEqual(keep('<HTML><BODY>x</BoDy ></HtMl\n>tail'), '<HTML><BODY>xtail</body></html>')

    def test_only_real_closers_are_removed(self):
        page = ('<html><head><title>Close </body> tags</title><script>var s="</html>";</script></head>'
                '<body><a title="a </body> b">x</a></body></html><p>late</p>')
        fixed = keep(page)
        self.assertIn('<title>Close </body> tags</title>', fixed)
        self.assertIn('var s="</html>";', fixed)
        self.assertIn('title="a </body> b"', fixed)
        self.assertTrue(fixed.endswith('x</a><p>late</p></body></html>'))

    def test_a_script_after_the_closers_keeps_its_text(self):
        self.assertEqual(keep('</html><script>var a="</body>"</script>'), '<script>var a="</body>"</script></body></html>')

    def test_a_quote_inside_an_unquoted_value_does_not_open_a_string(self):
        self.assertEqual(keep('<a href=x"y>q</a></body></html>z'), '<a href=x"y>q</a>z</body></html>')

    def test_tricky_markup_still_finds_the_real_closers(self):
        cases = {
            'svg self-closing title': ('<body><svg><title/></svg>x</body></html><p>late</p>', 'x<p>late</p></body></html>'),
            'svg style': ('<body><svg><style/><rect/></svg>x</body></html><p>late</p>', '<p>late</p></body></html>'),
            'empty comment': ('<body><!-->x</body></html><p>late</p>', 'x<p>late</p></body></html>'),
            'comment ending --!>': ('<body><!-- a --!>x</body></html><p>late</p>', 'x<p>late</p></body></html>'),
            'quote in an unquoted value': ('<body><a href=/p?x=">a</a></body></html><p>late</p>', 'a</a><p>late</p></body></html>'),
            'quote in a doctype': ("<!DOCTYPE html x='><body>a</body></html><p>late</p>", 'a<p>late</p></body></html>'),
            'cdata outside svg': ('<body><![CDATA[ x="> </body></html><p>late</p>', '<p>late</p></body></html>'),
        }
        for name, (page, ending) in cases.items():
            with self.subTest(name):
                fixed = keep(page)
                self.assertTrue(fixed.endswith(ending), fixed)
                self.assertEqual(fixed.count('</body>'), 1, fixed)

    def test_a_no_break_space_after_the_closers_is_content(self):
        self.assertEqual(keep('<body>x</body></html>\xa0'), '<body>x\xa0</body></html>')

    def test_many_unfinished_closers_take_linear_time(self):
        import time
        for page in ('</body ' * 300_000, '<a ' * 300_000 + '</body></html>x', '<!-- ' * 300_000 + '</html>x'):
            started = time.perf_counter()
            keep(page)
            self.assertLess(time.perf_counter() - started, 3.0, page[:20])

    def test_the_title_reaches_the_capture_unchanged(self):
        page = ('<html><head><title>How to close </body> tags</title></head>'
                '<body><h1>Closing tags</h1><p>Some words here.</p></body></html>')
        data = extractor.extract_page_data(page, 'https://tail.test/', 'tail.test', {})
        self.assertEqual(data['title'], 'How to close </body> tags')


class DroppingParser(unittest.TestCase):
    def test_extractor_and_markdown_keep_late_content_when_the_parser_drops_it(self):
        with patch.object(extractor, 'BeautifulSoup', _dropping_soup), \
             patch.object(markdown_converter, 'BeautifulSoup', _dropping_soup):
            data = extractor.extract_page_data(PAGE, 'https://tail.test/', 'tail.test', {})
        self.assertIn('https://tail.test/late-link', [link['url'] for link in data['internal_links']])
        self.assertIn('https://tail.test/late.png', [image['url'] for image in data['images']])
        self.assertIn('Late paragraph text.', data['markdown'])

    def test_markdown_converter_alone_keeps_late_content(self):
        with patch.object(markdown_converter, 'BeautifulSoup', _dropping_soup):
            md = markdown_converter.convert_html_to_markdown(PAGE, 'https://tail.test/', parser='lxml')
        self.assertIn('Late paragraph text.', md)
        self.assertIn('/late-link', md)


if __name__ == '__main__':
    unittest.main(verbosity=1)
