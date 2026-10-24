import copy
import json
from pathlib import Path
import tempfile
import unittest
from datetime import date

from bs4 import BeautifulSoup

from daily_robotics_briefing.renderer import _display_text, build_dashboard, render_html, render_markdown


class RendererTests(unittest.TestCase):
    def test_report_displays_reader_content_and_preserves_evidence(self):
        overview = r'The authors report $1000\times$ improvement with $\pi_{0.5}$. [reported result]'
        row = dict(paper_id='arXiv:example', title='A paper', institution='MIT',
                   overview=overview, link='https://arxiv.org/abs/example',
                   evidence=[dict(claim=overview, evidence_quote='Original source quote')])
        report = dict(submission_date='2026-10-21', papers_fetched=88, papers_analyzed=88,
                      selected_paper_count=2, filters=dict(institutions=['MIT'], topics=['robotics']),
                      affiliation_coverage=dict(matched=12, no_match=14, unknown=62),
                      briefing=dict(executive_summary=[overview],
                                    executive_summary_evidence=[dict(text=overview, paper_ids=['arXiv:example'])],
                                    institution_matches=[row], topic_matches=[dict(row, paper_id='arXiv:unavailable',
                                        overview='Summary unavailable: source evidence could not be verified; consult the linked paper.',
                                        evidence=[], summary_status='evidence_validation_failed')]))
        original = copy.deepcopy(report)
        arguments = dict(briefing=report['briefing'],
                         matched_institutions=report['filters']['institutions'],
                         matched_topics=report['filters']['topics'],
                         submission_date=date.fromisoformat(report['submission_date']),
                         papers_fetched=report['papers_fetched'], papers_analyzed=report['papers_analyzed'],
                         affiliation_coverage=report['affiliation_coverage'])
        html = render_html(**arguments)
        markdown = render_markdown(**arguments)
        soup = BeautifulSoup(html, 'html.parser')
        for output in [soup.get_text(), markdown]:
            self.assertNotIn('Affiliations:', output)
            self.assertNotIn('Papers analyzed:', output)
            self.assertNotIn('[reported result]', output)
            self.assertNotIn(r'$1000\times$', output)
            self.assertIn('1000×', output)
            self.assertIn('π₀.₅', output)
            self.assertNotIn('source evidence could not be verified', output)
            self.assertIn('Summary unavailable; see the paper for details.', output)
        self.assertEqual(len(soup.select('tbody tr')), report['selected_paper_count'])
        self.assertIn(f'Papers in this briefing: {report["selected_paper_count"]}', soup.get_text())
        self.assertEqual(report, original)
        for bullet in report['briefing']['executive_summary_evidence']:
            for pid in bullet['paper_ids']:
                self.assertTrue(soup.select(f'li a[href="https://arxiv.org/abs/{pid.removeprefix("arXiv:")}"]'))

    def test_formatting_is_bounded_and_preserves_other_content(self):
        self.assertEqual(_display_text(r'Reported $1000\times$ [reported result].'), 'Reported 1000×.')
        self.assertEqual(_display_text(r'$\pi_{0.5}$ and $10^{2}$'), 'π₀.₅ and 10²')
        self.assertEqual(_display_text(r'$\frac{1}{2}$'), r'$\frac{1}{2}$')
        self.assertEqual(_display_text('Costs $5 to $10.'), 'Costs $5 to $10.')
        self.assertEqual(_display_text('73% success [simulation only].'), '73% success [simulation only].')

    def test_formatted_summary_is_still_html_escaped(self):
        text = r'<script>alert(1)</script> $1000\times$ [reported result].'
        html = render_html(dict(executive_summary=[text]), [], [], date(2026, 10, 21), 1, 1)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('1000×.', html)

    def test_title_math_in_both_tables_and_dashboard_preserves_source(self):
        title = r'Progress Probes $P^2$: <Runtime> with $\pi_{0.5}$'
        row = dict(paper_id='arXiv:example', title=title, institution='MIT',
                   overview='A runtime monitor.', link='https://arxiv.org/abs/example')
        briefing = dict(institution_matches=[row], topic_matches=[dict(row)])
        original = copy.deepcopy(briefing)
        args = (briefing, [], [], date(2026, 10, 24), 1, 1)
        html = render_html(*args)
        markdown = render_markdown(*args)
        cells = BeautifulSoup(html, 'html.parser').select('tbody tr td:first-child')
        self.assertEqual([cell.get_text() for cell in cells],
                         ['Progress Probes P²: <Runtime> with π₀.₅'] * 2)
        self.assertEqual(markdown.count('Progress Probes P²: <Runtime> with π₀.₅'), 2)
        self.assertIn('&lt;Runtime&gt;', html)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = dict(submission_date='2026-10-24', briefing=briefing,
                           papers=[dict(arxiv_id='arXiv:example', title=title,
                                        abstract='A runtime monitor.', topic_match=True)])
            (root / '2026-10-24.json').write_text(json.dumps(payload), encoding='utf-8')
            build_dashboard(root, root / 'index.html')
            self.assertIn('Progress Probes P²:', (root / 'index.html').read_text())
            self.assertEqual(payload['papers'][0]['title'], title)
        self.assertEqual(briefing, original)
        self.assertEqual(_display_text(r'$P^12$ and $H_2$'), 'P¹2 and H₂')
        self.assertEqual(_display_text(r'$\frac{1}{2}$'), r'$\frac{1}{2}$')
