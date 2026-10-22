from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .time_utils import eastern_today

ARXIV_URL = "https://arxiv.org/list/cs.RO/recent?skip=0&show=2000"
logger = logging.getLogger(__name__)
MAX_PDF_BYTES = 32 * 1024 * 1024


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": "daily-robotics-briefing/1.0"})
    return session

@dataclass
class Paper:
    arxiv_id: str
    title: str
    authors: list[str]
    subjects: str
    abstract: str
    abs_url: str
    pdf_url: str
    html_url: str = ""
    html_author_notes_text: str = ""
    html_author_institutions: list[str] | None = None
    paper_version: str = ""
    affiliation_blocks: list[dict] = field(default_factory=list)
    affiliation_text: str = ""
    affiliation_source: str = "none"
    affiliation_status: str = "unknown"
    affiliation_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _extract_abstract_text(soup: BeautifulSoup) -> str:
    """Extract abstract text from an arXiv abstract page.

    arXiv pages primarily expose the abstract in `blockquote.abstract`, but we
    keep fallbacks for layout drift and metadata variants.
    """
    abstract_node = soup.select_one("blockquote.abstract")
    if abstract_node:
        text = abstract_node.get_text(" ", strip=True)
        return _clean(text.replace("Abstract:", "", 1))

    # Fallback: some pages include an OpenGraph description in metadata.
    og_description = soup.select_one("meta[property='og:description']")
    if og_description and og_description.get("content"):
        content = str(og_description.get("content"))
        return _clean(content.replace("Abstract:", "", 1))

    return ""


def _extract_html_url(soup: BeautifulSoup, abs_url: str) -> str:
    html_link = soup.select_one("a[href*='/html/']")
    if not html_link:
        return ""
    href = str(html_link.get("href") or "").strip()
    if not href:
        return ""
    return urljoin(abs_url, href)


def _looks_like_affiliation_note(line: str) -> bool:
    lowered = re.sub(r"\S+@\S+", "", line.lower())
    if "corresponding author" in lowered or "equal contribution" in lowered:
        return False
    institution_markers = (
        "university",
        "institute",
        "school",
        "college",
        "laboratory",
        "lab",
        "academy",
        "center",
        "centre",
        "hospital",
        "corporation",
        "corp",
        "inc",
        "ltd",
        "école",
        "ecole",
        "polytechnique",
        "université",
        "universität",
        "universidad",
    )
    return any(re.search(rf"\b{marker}\b", lowered) for marker in institution_markers) or bool(
        re.search(r"\b(epfl|eth|mit|cmu|ucsd|ucla|inria|nvidia|kaist)\b", lowered)
    )


def _parse_author_institutions_from_notes(notes_text: str) -> list[str]:
    lines = [" ".join(line.split()) for line in notes_text.splitlines()]
    cleaned_lines = [line.lstrip("*†‡0123456789. ").strip(" ;,.") for line in lines if line.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for line in cleaned_lines:
        if not _looks_like_affiliation_note(line):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)
    return unique


def _html_affiliation_blocks(soup: BeautifulSoup, source_url: str, authors: list[str]) -> list[dict]:
    document = soup.select_one('article.ltx_document') or soup
    boundary = document.select_one('.ltx_abstract, .ltx_section')
    front_nodes = set()
    for node in document.descendants:
        if node is boundary:
            break
        front_nodes.add(id(node))
    blocks: list[dict] = []
    seen = set()

    def add(node, kind: str, text: str | None = None) -> None:
        if id(node) not in front_nodes:
            return
        text = text if text is not None else node.get_text(' ', strip=True)
        if kind == 'affiliation':
            # Project links can be glued to the institution within one HTML text
            # node. Keep them out of dedicated affiliation fields, not context.
            text = re.split(r'Project\s+page\s*:', text, maxsplit=1, flags=re.I)[0]
        text = re.sub(r'^Affiliation:\s*', '', text).strip()
        creator = node.find_parent(class_='ltx_creator')
        linked = []
        if creator and kind == 'affiliation':
            person = creator.select_one('.ltx_personname')
            person_text = person.get_text(' ', strip=True) if person else ''
            names = [a for a in authors if a in person_text]
            # A multi-author group with multiple affiliations does not establish
            # every individual author-to-institution association.
            if len(names) == 1:
                linked = names
        key = (kind, text, tuple(linked))
        if not text or key in seen:
            return
        seen.add(key)
        locator = '#' + node['id'] if node.get('id') else node.name + '.' + '.'.join(node.get('class', []))
        blocks.append(dict(id=f'html-{len(blocks)}', text=text, kind=kind,
                           authors=linked, source_url=source_url, locator=locator))

    for node in document.select('.ltx_role_affiliation, .ltx_affiliation'):
        add(node, 'affiliation')
    for node in document.select('.ltx_author_notes'):
        if not node.select_one('.ltx_role_affiliation, .ltx_affiliation'):
            add(node, 'affiliation')
    for node in document.select('.ltx_note_content, .ltx_thanks, .ltx_note, .ltx_role_thanks'):
        if node.select_one('.ltx_note_content'):
            continue
        add(node, 'author_note')
    for header in document.select('.ltx_authors'):
        # Affiliation tables and numbered header rows do not necessarily have an
        # affiliation CSS class. Keep individual cells instead of the whole table.
        for node in header.select('.ltx_td, .ltx_p'):
            text = node.get_text(' ', strip=True)
            if not node.select_one('.ltx_td, .ltx_p') and _looks_like_affiliation_note(text):
                add(node, 'affiliation')
    for node in soup.select('meta[name="citation_author_institution"]'):
        text = str(node.get('content', '')).strip()
        if text:
            blocks.append(dict(id=f'html-{len(blocks)}', text=text, kind='affiliation', authors=[],
                               source_url=source_url, locator='meta[citation_author_institution]'))
    # General front matter is context for ambiguous cases, not permission to scan
    # body mentions. It also captures notes preceding the author container.
    front_text = []
    context_nodes = document.descendants if boundary is not None else (
        node for header in document.select('.ltx_authors, .ltx_pubnotes') for node in header.descendants
    )
    for node in context_nodes:
        if node is boundary:
            break
        if isinstance(node, str) and node.parent.name not in {'script', 'style'}:
            value = str(node).strip()
            if value:
                front_text.append(value)
    context = ' '.join(front_text)
    if context:
        blocks.append(dict(id=f'html-{len(blocks)}', text=context, kind='header_context', authors=[],
                           source_url=source_url, locator='article front matter before abstract/sections'))
    return blocks


def _fetch_html_author_metadata(
    html_url: str, timeout: int, session: requests.Session, issues: list[str],
    authors: list[str] | None = None,
) -> tuple[str, list[dict]]:
    if not html_url:
        issues.append('html_link_missing')
        return '', []
    try:
        resp = session.get(html_url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        issues.append('html_fetch_failed')
        return '', []
    soup = BeautifulSoup(resp.text, 'html.parser')
    blocks = _html_affiliation_blocks(soup, html_url, authors or [])
    text = '\n'.join(b['text'] for b in blocks if b['kind'] != 'header_context')
    if not blocks:
        issues.append('html_affiliation_missing')
    return text, blocks


def _pdf_affiliation_text(text: str) -> str:
    # Layout extraction and an inline boundary handle collapsed PDF lines. Keep
    # wrapped author footnotes, rather than testing each line in isolation.
    split = re.split(r'\bAbstract\s*[:—–-]?|(?:^|\n)\s*(?:1\.?|I\.?)\s+INTRODUCTION\b', text, maxsplit=1, flags=re.I)
    header = split[0]
    footnotes = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.search(r'\bauthors? (?:is|are) (?:also )?with\b', line, re.I):
            fragment = line.strip()
            for continuation in lines[index + 1:index + 4]:
                if re.search(r'[.!?]\s*$', fragment):
                    break
                if not continuation.strip() or re.match(r'\s*(?:Abstract|Introduction)\b', continuation, re.I):
                    break
                fragment += ' ' + continuation.strip()
                if re.search(r'\.(?:\s|$)', continuation):
                    break
            if fragment not in header:
                footnotes.append(fragment)
    return header.strip() + ('\n' + '\n'.join(footnotes) if footnotes else '')


def _fetch_pdf_affiliations(
    pdf_url: str, timeout: int, session: requests.Session, issues: list[str],
    max_pdf_bytes: int | None = None,
) -> str:
    limit = MAX_PDF_BYTES if max_pdf_bytes is None else max_pdf_bytes
    try:
        with session.get(pdf_url, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            content = bytearray()
            for chunk in resp.iter_content(chunk_size=65536):
                content.extend(chunk)
                if len(content) > limit:
                    issues.append('pdf_too_large')
                    return ''
        reader = PdfReader(BytesIO(content))
        if not reader.pages:
            issues.append('pdf_affiliation_missing')
            return ''
        page = reader.pages[0]
        text = page.extract_text(extraction_mode='layout') or page.extract_text() or ''
        if len(re.sub(r'\W', '', text)) < 20:
            text = _ocr_first_page(bytes(content), issues)
        affiliations = _pdf_affiliation_text(text)
        if not affiliations:
            issues.append('pdf_affiliation_missing')
        return affiliations
    except requests.RequestException:
        issues.append('pdf_fetch_failed')
    except (PyPdfError, ValueError, OSError, IndexError, KeyError):
        issues.append('pdf_unreadable')
    return ''


def _ocr_first_page(content: bytes, issues: list[str]) -> str:
    """Local OCR only when PDF text is absent; one page and bounded runtimes."""
    if not shutil.which('pdftoppm') or not shutil.which('tesseract'):
        issues.append('pdf_ocr_unavailable')
        return ''
    try:
        with tempfile.TemporaryDirectory(prefix='briefing-ocr-') as tmp:
            root = Path(tmp)
            (root / 'source.pdf').write_bytes(content)
            subprocess.run(['pdftoppm', '-f', '1', '-singlefile', '-scale-to', '2000', '-png',
                            str(root / 'source.pdf'), str(root / 'page')],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run(['tesseract', str(root / 'page.png'), 'stdout', '--psm', '3'],
                                    check=True, capture_output=True, text=True, timeout=30)
            issues.append('pdf_ocr_used')
            return result.stdout
    except (OSError, subprocess.SubprocessError):
        issues.append('pdf_ocr_failed')
        return ''


def _enrich_affiliations(paper: Paper, timeout: int, session: requests.Session, max_pdf_bytes: int | None = None) -> None:
    from .affiliations import deterministic_evidence
    from .common_robotics_institutions import COMMON_ROBOTICS_INSTITUTIONS
    from .institution_filter import alias_hits, build_institution_specs

    issues = paper.affiliation_issues
    notes, blocks = _fetch_html_author_metadata(paper.html_url, timeout, session, issues, paper.authors)
    paper.html_author_notes_text = notes
    paper.html_author_institutions = _parse_author_institutions_from_notes(notes)
    paper.affiliation_blocks = blocks
    paper.affiliation_text = notes
    paper.affiliation_source = 'html' if blocks else 'none'
    # Use complete front matter before resorting to a large PDF. Ambiguous HTML
    # can be resolved from its bounded context by the model without downloading.
    useful_html = any(_looks_like_affiliation_note(b['text']) for b in blocks)
    if not useful_html:
        text = _fetch_pdf_affiliations(paper.pdf_url, timeout, session, issues, max_pdf_bytes)
        if text:
            paper.affiliation_text = text
            paper.affiliation_source = 'pdf'
            method = 'OCR' if 'pdf_ocr_used' in issues else 'layout text'
            specs = build_institution_specs(COMMON_ROBOTICS_INSTITUTIONS)
            for line in text.splitlines():
                if _looks_like_affiliation_note(line):
                    residue = line
                    for raw, _ in alias_hits(line, specs):
                        residue = residue.replace(raw, '')
                    # A bare institutional header field is unambiguous. A
                    # sentence/caption mentioning one needs relationship review.
                    kind = 'affiliation' if not re.search(r'[A-Za-z]', residue) else 'pdf_header'
                    blocks.append(dict(id=f'pdf-{len(blocks)}', text=line.strip(), kind=kind,
                                       authors=[], source_url=paper.pdf_url, locator=f'first-page {method} affiliation line', page=1))
            blocks.append(dict(id=f'pdf-{len(blocks)}', text=text, kind='header_context', authors=[],
                               source_url=paper.pdf_url, locator=f'first-page {method} header and author footnotes', page=1))
    evidence, _ = deterministic_evidence(paper.to_dict(), build_institution_specs(COMMON_ROBOTICS_INSTITUTIONS))
    paper.affiliation_status = 'extracted' if any(e['role'] == 'author_affiliation' for e in evidence) else 'unknown'
    if paper.affiliation_status == 'unknown':
        logger.warning('Affiliation unresolved for %s (%s)', paper.arxiv_id, ', '.join(issues) or 'front matter requires review')


def _parse_arxiv_list_header_date(header_text: str) -> date | None:
    """Parse arXiv list header dates like 'Fri, 6 Mar 2026 (showing 123 of 123 entries)'."""
    date_part = " ".join(header_text.split("(", 1)[0].split())
    try:
        return datetime.strptime(date_part, "%a, %d %b %Y").date()
    except ValueError:
        return None


def _extract_ref_from_dt(dt: Any) -> tuple[str, str, str] | None:
    id_link = dt.select_one("a[title='Abstract']")
    if not id_link:
        return None

    arxiv_id = id_link.get_text(strip=True)
    abs_path = id_link.get("href", "")
    abs_url = f"https://arxiv.org{abs_path}"
    canonical_id = abs_path.rsplit("/", 1)[-1].strip()
    pdf_url = f"https://arxiv.org/pdf/{canonical_id}.pdf" if canonical_id else f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return arxiv_id, abs_url, pdf_url


def _collect_abs_urls_for_date(list_page_html: str, target_date: date) -> list[tuple[str, str, str]]:
    """Return (arxiv_id, abs_url, pdf_url) tuples from the exact date section."""
    soup = BeautifulSoup(list_page_html, "html.parser")
    paper_refs: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()

    for h3 in soup.select("h3"):
        parsed = _parse_arxiv_list_header_date(h3.get_text(" ", strip=True))
        if parsed != target_date:
            continue

        # Older arXiv layout: entries were grouped under a <dl> sibling.
        dl = h3.find_next_sibling("dl")
        if dl is not None:
            for dt in dl.select("dt"):
                ref = _extract_ref_from_dt(dt)
                if not ref or ref[0] in seen_ids:
                    continue
                seen_ids.add(ref[0])
                paper_refs.append(ref)
            continue

        # Current arXiv layout: entries appear as direct dt/dd siblings after <h3>
        # until the next <h3> date header.
        node = h3.next_sibling
        while node is not None:
            node_name = getattr(node, "name", None)
            if node_name == "h3":
                break
            if node_name == "dt":
                ref = _extract_ref_from_dt(node)
                if ref and ref[0] not in seen_ids:
                    seen_ids.add(ref[0])
                    paper_refs.append(ref)
            node = node.next_sibling

    return paper_refs


def fetch_csro_recent(
    max_papers: int = 400,
    timeout: int = 30,
    submission_date: date | None = None,
    max_pdf_bytes: int | None = None,
) -> list[Paper]:
    """Scrape arXiv cs.RO and fetch papers submitted on the chosen day.

    By default this targets yesterday's date, which matches the daily-briefing
    requirement to only summarize papers submitted the day before execution.
    """
    target_date = submission_date or (eastern_today() - timedelta(days=1))

    session = _build_session()
    resp = session.get(ARXIV_URL, timeout=timeout)
    resp.raise_for_status()
    all_refs = _collect_abs_urls_for_date(resp.text, target_date=target_date)
    if len(all_refs) > max_papers:
        logger.warning("Collection capped at %s of %s listed papers", max_papers, len(all_refs))
    paper_refs = all_refs[:max_papers]

    papers: list[Paper] = []
    for arxiv_id, abs_url, pdf_url in paper_refs:
        try:
            p = _fetch_abs_page(arxiv_id, abs_url, pdf_url, timeout=timeout, session=session)
            _enrich_affiliations(p, timeout, session, max_pdf_bytes)
            papers.append(p)
        except requests.RequestException:
            logger.warning("Could not collect abstract for %s", arxiv_id)
            continue

    return papers


def _fetch_abs_page(arxiv_id: str, abs_url: str, pdf_url: str, timeout: int, session: requests.Session | None = None) -> Paper:
    http = session or _build_session()
    resp = http.get(abs_url, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title_node = soup.select_one("h1.title")
    authors_node = soup.select_one("div.authors")
    subjects_node = soup.select_one("span.primary-subject")

    title = _clean((title_node.get_text(" ", strip=True) if title_node else "").replace("Title:", ""))
    abstract = _extract_abstract_text(soup)
    authors_text = (authors_node.get_text(" ", strip=True) if authors_node else "").replace("Authors:", "")
    author_links = authors_node.select('a') if authors_node else []
    authors = ([_clean(a.get_text(' ', strip=True)) for a in author_links]
               if author_links else [_clean(x) for x in authors_text.split(',') if _clean(x)])
    subjects = _clean(subjects_node.get_text(" ", strip=True) if subjects_node else "")
    html_url = _extract_html_url(soup, abs_url=abs_url)
    version_urls = [html_url, *[str(a.get('href', '')) for a in soup.select('a[href]')]]
    base_id = arxiv_id.replace('arXiv:', '').split('v')[0]
    versions = [int(m.group(1)) for url in version_urls
                for m in re.finditer(re.escape(base_id) + r'v(\d+)', url)]
    html_version = re.search(re.escape(base_id) + r'v(\d+)', html_url)
    version = f'{base_id}v{html_version.group(1)}' if html_version else f'{base_id}v{max(versions)}' if versions else ''
    if version:
        pdf_url = f'https://arxiv.org/pdf/{version}.pdf'

    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        subjects=subjects,
        abstract=abstract,
        abs_url=abs_url,
        pdf_url=pdf_url,
        html_url=html_url,
        html_author_institutions=[],
        paper_version=version,
    )
