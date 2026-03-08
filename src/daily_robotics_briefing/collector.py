from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from .time_utils import eastern_today

ARXIV_URL = "https://arxiv.org/list/cs.RO/recent?skip=0&show=2000"


@dataclass
class Paper:
    arxiv_id: str
    title: str
    authors: list[str]
    subjects: str
    abstract: str
    abs_url: str
    pdf_url: str
    pdf_first_page_text: str = ""

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
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
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
) -> list[Paper]:
    """Scrape arXiv cs.RO and fetch papers submitted on the chosen day.

    By default this targets yesterday's date, which matches the daily-briefing
    requirement to only summarize papers submitted the day before execution.
    """
    target_date = submission_date or (eastern_today() - timedelta(days=1))

    resp = requests.get(ARXIV_URL, timeout=timeout)
    resp.raise_for_status()
    paper_refs = _collect_abs_urls_for_date(resp.text, target_date=target_date)[:max_papers]

    papers: list[Paper] = []
    for arxiv_id, abs_url, pdf_url in paper_refs:
        try:
            p = _fetch_abs_page(arxiv_id, abs_url, pdf_url, timeout=timeout)
            p.pdf_first_page_text = _fetch_pdf_first_page_text(pdf_url=pdf_url, timeout=timeout)
            papers.append(p)
        except requests.RequestException:
            continue

    return papers


def _fetch_abs_page(arxiv_id: str, abs_url: str, pdf_url: str, timeout: int) -> Paper:
    resp = requests.get(abs_url, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title_node = soup.select_one("h1.title")
    authors_node = soup.select_one("div.authors")
    subjects_node = soup.select_one("span.primary-subject")

    title = _clean((title_node.get_text(" ", strip=True) if title_node else "").replace("Title:", ""))
    abstract = _extract_abstract_text(soup)
    authors_text = (authors_node.get_text(" ", strip=True) if authors_node else "").replace("Authors:", "")
    authors = [_clean(x) for x in authors_text.split(",") if _clean(x)]
    subjects = _clean(subjects_node.get_text(" ", strip=True) if subjects_node else "")

    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        subjects=subjects,
        abstract=abstract,
        abs_url=abs_url,
        pdf_url=pdf_url,
    )


def _fetch_pdf_first_page_text(pdf_url: str, timeout: int) -> str:
    """Download a PDF and extract text from the first page only."""
    try:
        resp = requests.get(pdf_url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return ""

    try:
        reader = PdfReader(BytesIO(resp.content))
        if not reader.pages:
            return ""
        raw_text = reader.pages[0].extract_text() or ""
        lines = [" ".join(line.split()) for line in raw_text.splitlines()]
        lines = [line for line in lines if line]
        return "\n".join(lines)
    except Exception:
        return ""
