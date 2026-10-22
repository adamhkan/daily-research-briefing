import unittest
import shutil
from io import BytesIO
from unittest.mock import Mock, patch

import requests
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from daily_robotics_briefing.collector import (
    Paper, _enrich_affiliations, _fetch_pdf_affiliations, _pdf_affiliation_text, _ocr_first_page, _fetch_abs_page,
)


def paper():
    return Paper('p', 'Robotics', ['Jane Doe'], 'cs.RO', 'An abstract.',
                 'https://arxiv.org/abs/p', 'https://arxiv.org/pdf/p', 'https://arxiv.org/html/p')


def response(html='', content=b''):
    resp = Mock(text=html)
    resp.__enter__ = Mock(return_value=resp)
    resp.__exit__ = Mock(return_value=False)
    resp.iter_content.return_value = [content]
    return resp


def pdf_bytes():
    writer = PdfWriter()
    for institution in ['EPFL', 'Massachusetts Institute of Technology']:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({
            NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'),
            NameObject('/BaseFont'): NameObject('/Helvetica'),
        })
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})
        })
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 40 750 Td ({institution}) Tj 0 -20 Td (Abstract) Tj 0 -20 Td (We compare to Stanford University.) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


class CollectorTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('pdftoppm') and shutil.which('tesseract'), 'OCR tools not installed')
    def test_real_first_page_render_and_ocr(self):
        issues = []
        text = _ocr_first_page(pdf_bytes(), issues)
        self.assertIn('EPFL', text)
        self.assertIn('pdf_ocr_used', issues)

    def test_abs_author_links_and_pdf_version_are_preserved(self):
        session = Mock()
        session.get.return_value = response('''<h1 class="title">Title: Paper</h1>
          <div class="authors">Authors: <a>Doe, Jane</a>, <a>John Smith</a></div>
          <a href="/html/2610.00001v2">HTML</a><a href="/abs/2610.00001v1">v1</a>''')
        p = _fetch_abs_page('arXiv:2610.00001', 'https://arxiv.org/abs/2610.00001',
                            'https://arxiv.org/pdf/2610.00001.pdf', 10, session)
        self.assertEqual(p.authors, ['Doe, Jane', 'John Smith'])
        self.assertEqual(p.paper_version, '2610.00001v2')
        self.assertEqual(p.pdf_url, 'https://arxiv.org/pdf/2610.00001v2.pdf')

    def test_html_affiliation_skips_pdf(self):
        session = Mock()
        session.get.return_value = response('<div class="ltx_author_notes">Affiliation: EPFL</div>')
        p = paper()
        _enrich_affiliations(p, 10, session)
        self.assertEqual((p.affiliation_status, p.affiliation_source), ('extracted', 'html'))
        self.assertEqual(session.get.call_count, 1)

    def test_alternative_html_affiliation_metadata(self):
        for html in ['<div class="ltx_affiliation">EPFL</div>',
                     '<meta name="citation_author_institution" content="EPFL">']:
            with self.subTest(html=html):
                session = Mock()
                session.get.return_value = response(html)
                p = paper()
                _enrich_affiliations(p, 10, session)
                self.assertEqual(p.affiliation_source, 'html')
                self.assertEqual(session.get.call_count, 1)

    def test_missing_html_uses_actual_first_page_pdf_extraction(self):
        session = Mock()
        session.get.side_effect = [response('<html></html>'), response(content=pdf_bytes())]
        p = paper()
        _enrich_affiliations(p, 10, session)
        # PDF front matter is available; semantic extraction happens later.
        self.assertEqual((p.affiliation_status, p.affiliation_source), ('unknown', 'pdf'))
        self.assertIn('EPFL', p.affiliation_text)
        self.assertNotIn('Massachusetts', p.affiliation_text)
        self.assertNotIn('Stanford', p.affiliation_text)
        self.assertIn('html_affiliation_missing', p.affiliation_issues)

    def test_fetch_failure_remains_unknown_and_records_both_failures(self):
        session = Mock()
        session.get.side_effect = requests.ConnectionError('offline')
        p = paper()
        with self.assertLogs('daily_robotics_briefing.collector', level='WARNING'):
            _enrich_affiliations(p, 10, session)
        self.assertEqual(p.affiliation_status, 'unknown')
        self.assertEqual(p.affiliation_text, '')
        self.assertEqual(p.affiliation_issues, ['html_fetch_failed', 'pdf_fetch_failed'])

    def test_malformed_pdf_remains_unknown(self):
        session = Mock()
        session.get.side_effect = [response(), response(content=b'%PDF-1.4 invalid')]
        p = paper()
        with self.assertLogs(level='WARNING'):
            _enrich_affiliations(p, 10, session)
        self.assertEqual(p.affiliation_status, 'unknown')
        self.assertIn('pdf_unreadable', p.affiliation_issues)

    def test_pdf_download_limit_is_enforced(self):
        session = Mock()
        session.get.return_value = response(content=b'12345')
        issues = []
        with patch('daily_robotics_briefing.collector.MAX_PDF_BYTES', 4):
            text = _fetch_pdf_affiliations('https://arxiv.org/pdf/p', 10, session, issues)
        self.assertEqual(text, '')
        self.assertEqual(issues, ['pdf_too_large'])

    def test_affiliation_footnotes_are_kept_without_scanning_body_mentions(self):
        text = '''A robotics paper
Jane Doe
Abstract -- We compare a system from Stanford University.
Our experiments use a University of Washington dataset.
1 The authors are with EPFL, Lausanne.
This work was supported by MIT.
'''
        result = _pdf_affiliation_text(text)
        self.assertIn('EPFL', result)
        self.assertNotIn('Stanford', result)
        self.assertNotIn('Washington', result)
        self.assertNotIn('MIT', result)


if __name__ == '__main__':
    unittest.main()
