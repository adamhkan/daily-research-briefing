from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

AFFILIATION_KEYWORDS = (
    "university",
    "institute",
    "college",
    "school",
    "department",
    "laboratory",
    "lab",
    "centre",
    "center",
    "research",
    "robotics",
    "inc",
    "ltd",
    "corp",
    "gmbh",
)


@dataclass(frozen=True)
class InstitutionSpec:
    canonical: str
    aliases: list[str]


@dataclass
class MatchedInstitution:
    canonical: str
    raw: str
    match_method: str
    confidence: float


@dataclass
class AuthorInstitutionRecord:
    name: str
    institutions: list[MatchedInstitution]


@dataclass
class InstitutionExtractionResult:
    authors: list[AuthorInstitutionRecord]
    paper_level_institutions: list[str]
    unmapped_raw_institutions: list[str]
    filter_match: bool
    filter_match_institutions: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "authors": [
                {
                    "name": author.name,
                    "institutions": [
                        {
                            "canonical": inst.canonical,
                            "raw": inst.raw,
                            "match_method": inst.match_method,
                            "confidence": inst.confidence,
                        }
                        for inst in author.institutions
                    ],
                }
                for author in self.authors
            ],
            "paper_level_institutions": self.paper_level_institutions,
            "unmapped_raw_institutions": self.unmapped_raw_institutions,
            "filter_match": self.filter_match,
            "filter_match_institutions": self.filter_match_institutions,
        }


@dataclass
class ParsedInstitution:
    raw: str
    markers: set[str]
    matched: MatchedInstitution | None


@dataclass
class ParsedAuthor:
    name: str
    markers: set[str]


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized.lower())
    return " ".join(normalized.split())


def build_institution_specs(entries: list[object]) -> list[InstitutionSpec]:
    specs: list[InstitutionSpec] = []
    for entry in entries:
        if isinstance(entry, str):
            canonical = entry.strip()
            if canonical:
                specs.append(InstitutionSpec(canonical=canonical, aliases=[canonical]))
            continue

        if not isinstance(entry, dict):
            continue

        canonical = str(entry.get("canonical", "")).strip()
        if not canonical:
            continue
        aliases_raw = entry.get("aliases", [])
        aliases = [canonical]
        if isinstance(aliases_raw, list):
            aliases.extend(str(a).strip() for a in aliases_raw if str(a).strip())
        specs.append(InstitutionSpec(canonical=canonical, aliases=sorted(set(aliases))))

    return specs


def _match_institution(raw_affiliation: str, specs: list[InstitutionSpec]) -> MatchedInstitution | None:
    text = normalize_text(raw_affiliation)
    if not text:
        return None

    best_fuzzy: tuple[float, str] | None = None
    for spec in specs:
        for alias in spec.aliases:
            alias_norm = normalize_text(alias)
            if not alias_norm:
                continue
            text_padded = f" {text} "
            alias_padded = f" {alias_norm} "
            if alias_padded in text_padded or text_padded in alias_padded:
                return MatchedInstitution(
                    canonical=spec.canonical,
                    raw=raw_affiliation,
                    match_method="exact_alias",
                    confidence=0.98,
                )
            ratio = SequenceMatcher(None, alias_norm, text).ratio()
            if ratio >= 0.9 and (best_fuzzy is None or ratio > best_fuzzy[0]):
                best_fuzzy = (ratio, spec.canonical)

    if best_fuzzy:
        ratio, canonical = best_fuzzy
        return MatchedInstitution(
            canonical=canonical,
            raw=raw_affiliation,
            match_method="fuzzy_alias",
            confidence=round(ratio, 2),
        )

    return None


def _extract_marker_prefix(line: str) -> tuple[set[str], str]:
    line = line.strip()
    match = re.match(r"^([0-9]+|[a-z]|\*|†|‡)[\)\.]?\s+(.+)$", line, flags=re.IGNORECASE)
    if not match:
        return set(), line
    marker = match.group(1).strip().lower()
    return {marker}, match.group(2).strip()


def _looks_like_institution(line: str) -> bool:
    normalized = normalize_text(line)
    if not normalized:
        return False
    return any(keyword in normalized for keyword in AFFILIATION_KEYWORDS) or "@" in line


def _split_pdf_lines(pdf_first_page_text: str) -> list[str]:
    lines = [ln.strip() for ln in pdf_first_page_text.splitlines()]
    return [ln for ln in lines if ln]


def _parse_institutions(lines: list[str], specs: list[InstitutionSpec]) -> list[ParsedInstitution]:
    parsed: list[ParsedInstitution] = []
    for line in lines:
        markers, body = _extract_marker_prefix(line)
        matched = _match_institution(body, specs)
        if not matched and not _looks_like_institution(line):
            continue
        parsed.append(ParsedInstitution(raw=body, markers=markers, matched=matched))
    return parsed


def _parse_author_markers(lines: list[str]) -> list[ParsedAuthor]:
    authors: list[ParsedAuthor] = []
    header = " ".join(lines[:8])
    for chunk in re.split(r",| and ", header):
        candidate = chunk.strip()
        if not candidate or len(candidate.split()) < 2:
            continue
        if _looks_like_institution(candidate):
            continue
        marker_match = re.match(r"^(.+?)([0-9\*†‡a-z](?:,[0-9\*†‡a-z])*)$", candidate, flags=re.IGNORECASE)
        markers: set[str] = set()
        name = candidate
        if marker_match:
            name = marker_match.group(1).strip()
            markers = {m.strip().lower() for m in marker_match.group(2).split(",")}
        name = re.sub(r"\s+", " ", name).strip(" ;")
        if len(name.split()) < 2:
            continue
        authors.append(ParsedAuthor(name=name, markers=markers))
    return authors


def _match_author_name(author: str, parsed_authors: list[ParsedAuthor]) -> ParsedAuthor | None:
    author_norm = normalize_text(author)
    best: tuple[float, ParsedAuthor] | None = None
    for parsed in parsed_authors:
        ratio = SequenceMatcher(None, author_norm, normalize_text(parsed.name)).ratio()
        if ratio >= 0.8 and (best is None or ratio > best[0]):
            best = (ratio, parsed)
    return best[1] if best else None


def _markers_for_author_from_header(author_name: str, lines: list[str]) -> set[str]:
    header = " ".join(lines[:12])
    author_pattern = re.escape(author_name)
    match = re.search(
        rf"{author_pattern}\s*([0-9\*†‡a-z](?:,[0-9\*†‡a-z])*)",
        header,
        flags=re.IGNORECASE,
    )
    if not match:
        return set()
    return {m.strip().lower() for m in match.group(1).split(",")}


def extract_institutions_for_paper(
    author_names: list[str],
    pdf_first_page_text: str,
    institution_specs: list[InstitutionSpec],
) -> InstitutionExtractionResult:
    lines = _split_pdf_lines(pdf_first_page_text)
    parsed_institutions = _parse_institutions(lines, institution_specs)
    parsed_authors = _parse_author_markers(lines)

    paper_level: set[str] = set()
    unmapped: set[str] = set()
    for inst in parsed_institutions:
        if inst.matched:
            paper_level.add(inst.matched.canonical)
        else:
            unmapped.add(inst.raw)

    author_records: list[AuthorInstitutionRecord] = []
    for author_name in author_names:
        parsed_author = _match_author_name(author_name, parsed_authors)
        matched_for_author: list[MatchedInstitution] = []

        author_markers = parsed_author.markers if parsed_author else set()
        if not author_markers:
            author_markers = _markers_for_author_from_header(author_name, lines)

        if author_markers:
            for inst in parsed_institutions:
                if inst.matched and author_markers.intersection(inst.markers):
                    matched_for_author.append(inst.matched)

        if not matched_for_author:
            # Fallback: assign known paper-level institutions if explicit author markers are missing.
            matched_for_author = [
                MatchedInstitution(
                    canonical=canonical,
                    raw=canonical,
                    match_method="paper_level_fallback",
                    confidence=0.65,
                )
                for canonical in sorted(paper_level)
            ]

        author_records.append(
            AuthorInstitutionRecord(
                name=author_name,
                institutions=matched_for_author,
            )
        )

    filter_matches = sorted(paper_level)
    return InstitutionExtractionResult(
        authors=author_records,
        paper_level_institutions=sorted(paper_level),
        unmapped_raw_institutions=sorted(unmapped),
        filter_match=bool(filter_matches),
        filter_match_institutions=filter_matches,
    )
