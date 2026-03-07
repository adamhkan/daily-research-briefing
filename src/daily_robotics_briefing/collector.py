from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import requests
from bs4 import BeautifulSoup

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
    inferred_institutions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(text: str) -> str:
    return " ".join(text.split())


def fetch_csro_recent(max_papers: int = 400, timeout: int = 30) -> list[Paper]:
    """Scrape arXiv recent cs.RO list and fetch abstract pages.

    This intentionally reads from the exact URL requested by the user and then
    follows each abstract page for cleaner abstract/title extraction.
    """
    resp = requests.get(ARXIV_URL, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    dts = soup.select("dl > dt")
    dds = soup.select("dl > dd")
    pairs = list(zip(dts, dds))[:max_papers]

    papers: list[Paper] = []
    for dt, _ in pairs:
        id_link = dt.select_one("a[title='Abstract']")
        if not id_link:
            continue

        arxiv_id = id_link.get_text(strip=True)
        abs_path = id_link.get("href", "")
        abs_url = f"https://arxiv.org{abs_path}"
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        try:
            p = _fetch_abs_page(arxiv_id, abs_url, pdf_url, timeout=timeout)
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
    abstract_node = soup.select_one("blockquote.abstract")
    subjects_node = soup.select_one("span.primary-subject")

    title = _clean((title_node.get_text(" ", strip=True) if title_node else "").replace("Title:", ""))
    abstract = _clean((abstract_node.get_text(" ", strip=True) if abstract_node else "").replace("Abstract:", ""))
    authors_text = (authors_node.get_text(" ", strip=True) if authors_node else "").replace("Authors:", "")
    authors = [_clean(x) for x in authors_text.split(",") if _clean(x)]
    subjects = _clean(subjects_node.get_text(" ", strip=True) if subjects_node else "")

    institutions = infer_institutions_from_openalex(title)

    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        subjects=subjects,
        abstract=abstract,
        abs_url=abs_url,
        pdf_url=pdf_url,
        inferred_institutions=institutions,
    )


def infer_institutions_from_openalex(title: str, timeout: int = 20) -> list[str]:
    """Best-effort institution inference via OpenAlex title search."""
    if not title:
        return []

    url = "https://api.openalex.org/works"
    params = {"search": title, "per-page": 3}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return []

    data = resp.json()
    results = data.get("results", [])
    institutions: set[str] = set()
    for work in results:
        for authorship in work.get("authorships", []):
            for inst in authorship.get("institutions", []):
                name = inst.get("display_name")
                if name:
                    institutions.add(name)

    return sorted(institutions)
