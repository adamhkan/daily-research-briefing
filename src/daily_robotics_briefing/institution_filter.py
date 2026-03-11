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
    "inc",
    "ltd",
    "corp",
    "gmbh",
    "academy",
    "faculty",
    "hospital",
    "company",
    "technologies",
    "technology",
    "technological",
    "universitat",
    "universite",
    "universidad",
)

STRONG_AFFILIATION_KEYWORDS = (
    "university",
    "institute",
    "college",
    "school",
    "laboratory",
    "academy",
    "hospital",
    "faculty",
)

COMPANY_KEYWORDS = (
    "inc",
    "ltd",
    "corp",
    "gmbh",
    "llc",
    "corporation",
    "company",
)

SECTION_BREAK_KEYWORDS = (
    "abstract",
    "introduction",
    "preprint",
)

NON_AFFILIATION_LINE_HINTS = (
    "figure",
    "dataset",
    "algorithm",
    "experiment",
    "copyright",
    "arxiv",
    "code is available",
    "project page",
    "equal contribution",
    "corresponding author",
    "project lead",
    "abstract",
    "keywords",
    "index terms",
)

NON_AFFILIATION_FRAGMENT_HINTS = (
    "proposed",
    "results",
    "benchmark",
    "trajectory",
    "collision",
    "policy",
    "framework",
    "task",
)

COMPANY_SUFFIX_HINTS = (
    " inc",
    " ltd",
    " llc",
    " corp",
    " gmbh",
    " plc",
)

SECTION_BREAK_PREFIXES = (
    "abstract",
    "introduction",
    "1 introduction",
    "i introduction",
    "preprint",
)

ACRONYM_STOPWORDS = {
    "and",
    "at",
    "for",
    "in",
    "of",
    "the",
    "to",
}

ACRONYM_ALLOWLIST = {
    "mit",
    "cmu",
    "epfl",
    "eth",
    "kaist",
    "postech",
    "ntu",
    "nus",
    "hkust",
    "sjtu",
    "ucsd",
    "ucla",
    "uiuc",
    "nvidia",
}


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
    raw_institutions: list[str]


@dataclass
class InstitutionExtractionResult:
    authors: list[AuthorInstitutionRecord]
    paper_level_institutions: list[str]
    paper_level_detected_institutions: list[str]
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
                    "raw_institutions": author.raw_institutions,
                }
                for author in self.authors
            ],
            "paper_level_institutions": self.paper_level_institutions,
            "paper_level_detected_institutions": self.paper_level_detected_institutions,
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


def _contains_word(text: str, word: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", text))


def _contains_any_word(text: str, words: tuple[str, ...]) -> bool:
    return any(_contains_word(text, word) for word in words)


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
                specs.append(InstitutionSpec(canonical=canonical, aliases=sorted(_expand_aliases([canonical]))))
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
        specs.append(InstitutionSpec(canonical=canonical, aliases=sorted(_expand_aliases(aliases))))

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
            is_acronym_alias = _is_acronym_alias(alias, alias_norm)
            if len(alias_norm.split()) == 1 and len(alias_norm) <= 3 and alias_norm not in ACRONYM_ALLOWLIST:
                continue
            text_padded = f" {text} "
            alias_padded = f" {alias_norm} "
            if alias_padded in text_padded or (text_padded in alias_padded and text in ACRONYM_ALLOWLIST):
                return MatchedInstitution(
                    canonical=spec.canonical,
                    raw=raw_affiliation,
                    match_method="exact_alias",
                    confidence=0.98,
                )
            if is_acronym_alias:
                # Acronym aliases (e.g., "MIT") must match as exact standalone
                # tokens only; never use fuzzy/token-overlap matching for them.
                continue
            overlap = _token_overlap(alias_norm, text)
            if overlap >= 0.9 and len(alias_norm.split()) >= 2:
                return MatchedInstitution(
                    canonical=spec.canonical,
                    raw=raw_affiliation,
                    match_method="token_overlap",
                    confidence=round(overlap, 2),
                )
            ratio = SequenceMatcher(None, alias_norm, text).ratio()
            if ratio >= 0.92 and (best_fuzzy is None or ratio > best_fuzzy[0]):
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


def _is_title_like_fragment(normalized: str) -> bool:
    if len(normalized.split()) < 4:
        return False
    return (
        " for " in f" {normalized} "
        or " via " in f" {normalized} "
        or " with " in f" {normalized} "
        or " through " in f" {normalized} "
    ) and not any(keyword in normalized for keyword in AFFILIATION_KEYWORDS)


def _looks_like_institution(line: str) -> bool:
    normalized = normalize_text(line)
    if not normalized:
        return False
    if len(normalized.split()) > 16:
        return False
    if any(hint in normalized for hint in NON_AFFILIATION_LINE_HINTS):
        return False
    if any(hint in normalized for hint in NON_AFFILIATION_FRAGMENT_HINTS) and not _contains_any_word(
        normalized, AFFILIATION_KEYWORDS
    ):
        return False
    if _contains_word(normalized, "robotics") and not _contains_any_word(
        normalized, STRONG_AFFILIATION_KEYWORDS + COMPANY_KEYWORDS
    ):
        return False
    if normalized.startswith("fig ") or normalized.startswith("figure "):
        return False
    if _is_title_like_fragment(normalized):
        return False
    if normalized.endswith(":"):
        return False
    if "." in line and not _contains_any_word(normalized, AFFILIATION_KEYWORDS):
        return False
    if "@" in line:
        return True
    if _has_company_suffix(normalized):
        return True
    return _contains_any_word(normalized, AFFILIATION_KEYWORDS)


def _has_company_suffix(normalized: str) -> bool:
    tokens = normalized.split()
    if len(tokens) < 2:
        return False
    return tokens[-1] in {"inc", "ltd", "llc", "corp", "gmbh", "plc", "corporation", "company"}


def _is_generic_institution_phrase(normalized: str) -> bool:
    tokens = normalized.split()
    if len(tokens) <= 2 and any(token in STRONG_AFFILIATION_KEYWORDS for token in tokens):
        return True
    weak = {"the", "of", "for", "and", "at", "in", "on", "artificial", "intelligence"}
    return bool(tokens) and all(token in weak or token in STRONG_AFFILIATION_KEYWORDS for token in tokens)


def _has_strong_affiliation_signal(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    if _contains_any_word(normalized, STRONG_AFFILIATION_KEYWORDS):
        if _is_generic_institution_phrase(normalized):
            return False
        return True
    if _has_company_suffix(normalized):
        return True
    return _contains_any_word(normalized, COMPANY_KEYWORDS)


def _has_narrative_signal(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    narrative_hints = (" we ", " this ", " propose ", " presents ", " introduce ", " framework ", " benchmark ")
    return any(hint in f" {normalized} " for hint in narrative_hints)




def _strip_leading_author_tokens(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^(?:[A-Z][A-Za-z'’\-]+\s+){1,4}(?=[0-9]\b)", "", cleaned)
    cleaned = re.sub(r"^(?:[0-9]{1,2}|[a-z]|\*|†|‡)\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,;|·")

def _cleanup_affiliation_fragment(text: str) -> str:
    cleaned = re.sub(r"\S+@\S+", "", text)
    cleaned = re.sub(r"\bhttps?://\S+\b", "", cleaned)
    cleaned = re.sub(r"(?<=[0-9])(?=[A-Z])", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;|·")
    cleaned = re.sub(r"^(and|coauthor|authors?)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^author'?s version\.?$", "", cleaned, flags=re.IGNORECASE)
    cleaned = _strip_leading_author_tokens(cleaned)
    cleaned = re.sub(r"^[a-z]\s+(?=[A-Z])", "", cleaned)
    cleaned = re.sub(r"^(?:i+\.?\s*)?introduction\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"project page.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,;|·")


def _split_affiliation_fragments(body: str) -> list[str]:
    body = _cleanup_affiliation_fragment(body)
    if not body:
        return []

    parts = re.split(r"\s*[;|]\s*", body)
    fragments: list[str] = []
    for part in parts:
        subparts = re.split(r"\s*,\s*(?=(?:[0-9]{1,2}|[a-z]|\*|†|‡)\s*[A-Z])", part)
        for subpart in subparts:
            candidate = _cleanup_affiliation_fragment(subpart)
            if candidate:
                fragments.append(candidate)
    return fragments or [body]


def _split_source_lines(source_text: str) -> list[str]:
    lines = [ln.strip() for ln in source_text.splitlines()]
    return [ln for ln in lines if ln]


def _candidate_affiliation_lines(lines: list[str]) -> list[str]:
    candidates: list[str] = []
    saw_abstract = False
    for idx, line in enumerate(lines[:80]):
        normalized = normalize_text(line)
        if normalized in SECTION_BREAK_KEYWORDS or normalized.startswith(SECTION_BREAK_PREFIXES):
            saw_abstract = True
        if saw_abstract and idx > 45:
            break
        if saw_abstract and not (
            re.search(r"\b([0-9]{1,2}|[a-z]|\*|†|‡)\s*[\.:]?\s*[A-Z]", line)
            or "authors are with" in normalized
            or "author is with" in normalized
            or "affiliation" in normalized
            or "department of" in normalized
        ):
            continue
        candidates.append(line)
    return candidates




def _extract_marker_keyword_chunks(line: str) -> list[tuple[set[str], str]]:
    chunks: list[tuple[set[str], str]] = []
    pattern = re.compile(
        r"(?:^|\s)([0-9]{1,2}|[a-z]|\*|†|‡)\s*([A-Z].{2,120}?\b(?:University|Institute|College|School|Laboratory|Lab|Academy|Hospital|Inc\.?|Ltd\.?|Corp\.?|GmbH|Technology|Technological)\b.{0,80}?)(?=(?:\s+[0-9]{1,2}\s*[A-Z])|$)",
        flags=re.IGNORECASE,
    )
    for marker, body in pattern.findall(line):
        cleaned = _cleanup_affiliation_fragment(body)
        if cleaned:
            chunks.append(({marker.lower()}, cleaned))
    return chunks

def _expand_compact_markers(line: str) -> list[tuple[set[str], str]]:
    marker_pattern = re.compile(r"(?<!\w)([0-9]{1,2}|[a-z]|\*|†|‡)(?=[A-Z])")
    matches = list(marker_pattern.finditer(line))
    if not matches:
        marker, body = _extract_marker_prefix(line)
        return [(marker, body)]

    expanded: list[tuple[set[str], str]] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(line)
        marker = match.group(1).lower()
        body = line[start:end].strip(" ,;|")
        if body:
            expanded.append(({marker}, body))

    return expanded or [(_extract_marker_prefix(line))]


def _extract_inline_marker_affiliations(lines: list[str], specs: list[InstitutionSpec]) -> list[ParsedInstitution]:
    extracted: list[ParsedInstitution] = []
    for line in lines[:30]:
        for marker, body in re.findall(r"(?:^|\s)([0-9]{1,2}|[a-z]|\*|†|‡)\s+([^0-9\*†‡]+?)(?=(?:\s+[0-9]{1,2}\s+)|$)", line):
            fragment = _cleanup_affiliation_fragment(body)
            if not fragment:
                continue
            matched = _match_institution(fragment, specs)
            if not matched and not _looks_like_institution(fragment):
                continue
            extracted.append(ParsedInstitution(raw=fragment, markers={marker.lower()}, matched=matched))
    return extracted




def _extract_explicit_affiliation_entities(lines: list[str], specs: list[InstitutionSpec]) -> list[ParsedInstitution]:
    extracted: list[ParsedInstitution] = []
    pattern = re.compile(
        r"([A-Z][A-Za-z&'\-\. ]{2,80}\b(?:University|Institute|College|School|Laboratory|Lab|Academy|Hospital|Center|Centre|Corporation|Corp\.?|Inc\.?|Ltd\.?|GmbH))",
        flags=re.IGNORECASE,
    )
    for line in lines[:25]:
        for candidate in pattern.findall(line):
            fragment = _cleanup_affiliation_fragment(candidate)
            if not fragment:
                continue
            matched = _match_institution(fragment, specs)
            extracted.append(ParsedInstitution(raw=fragment, markers=set(), matched=matched))
    return extracted




def _extract_author_with_affiliations(lines: list[str], specs: list[InstitutionSpec]) -> list[ParsedInstitution]:
    extracted: list[ParsedInstitution] = []
    for line in lines[:45]:
        normalized = normalize_text(line)
        if "authors are with" not in normalized and "author is with" not in normalized:
            continue
        body = re.split(r"authors?\s+are\s+with|author\s+is\s+with", line, flags=re.IGNORECASE)
        if len(body) < 2:
            continue
        for fragment in _split_affiliation_fragments(body[-1]):
            matched = _match_institution(fragment, specs)
            if not matched and not _looks_like_institution(fragment):
                continue
            extracted.append(ParsedInstitution(raw=fragment, markers=set(), matched=matched))
    return extracted

def _extract_affiliation_line_windows(lines: list[str], specs: list[InstitutionSpec]) -> list[ParsedInstitution]:
    extracted: list[ParsedInstitution] = []
    header_lines = _candidate_affiliation_lines(lines)
    for idx in range(max(0, len(header_lines) - 1)):
        first = _cleanup_affiliation_fragment(header_lines[idx])
        second = _cleanup_affiliation_fragment(header_lines[idx + 1])
        if not first or not second:
            continue
        combo = _cleanup_affiliation_fragment(f"{first} {second}")
        if len(combo.split()) > 18:
            continue
        if not _has_strong_affiliation_signal(combo):
            continue
        if _has_narrative_signal(combo):
            continue
        matched = _match_institution(combo, specs)
        if not matched and not _looks_like_institution(combo):
            continue
        extracted.append(ParsedInstitution(raw=combo, markers=set(), matched=matched))
    return extracted

def _parse_institutions(lines: list[str], specs: list[InstitutionSpec]) -> list[ParsedInstitution]:
    parsed: list[ParsedInstitution] = []
    for line in _candidate_affiliation_lines(lines):
        expanded_parts = _expand_compact_markers(line)
        expanded_parts.extend(_extract_marker_keyword_chunks(line))
        for markers, body in expanded_parts:
            for fragment in _split_affiliation_fragments(body):
                matched = _match_institution(fragment, specs)
                if not matched and not _looks_like_institution(fragment):
                    continue
                parsed.append(ParsedInstitution(raw=fragment, markers=markers, matched=matched))

    parsed.extend(_extract_inline_marker_affiliations(lines, specs))
    parsed.extend(_extract_explicit_affiliation_entities(lines, specs))
    parsed.extend(_extract_affiliation_line_windows(lines, specs))
    parsed.extend(_extract_author_with_affiliations(lines, specs))
    filtered = [item for item in parsed if _is_high_quality_institution_candidate(item)]
    return _dedupe_parsed_institutions(filtered)


def _is_high_quality_institution_candidate(item: ParsedInstitution) -> bool:
    raw = item.raw
    normalized = normalize_text(raw)
    if not normalized:
        return False
    if any(token in normalized for token in ("introduction", "project page", "code is available", "index terms", "as a result", "this work", "framework")):
        return False
    if len(normalized.split()) > 14:
        return False
    if item.matched and not _has_narrative_signal(raw):
        return True
    if raw and raw[0].islower():
        return False
    if not _has_strong_affiliation_signal(raw):
        return False
    if _has_narrative_signal(raw):
        return False
    return True


def _dedupe_parsed_institutions(items: list[ParsedInstitution]) -> list[ParsedInstitution]:
    deduped: list[ParsedInstitution] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (normalize_text(item.raw), item.matched.canonical if item.matched else "")
        if not key[0] or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


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


def _scan_known_institutions_in_text(
    lines: list[str],
    specs: list[InstitutionSpec],
) -> list[ParsedInstitution]:
    # Scan the first two PDF pages for any configured/common institution alias.
    # A hit is treated as a paper-level affiliation signal by design.
    scan_text = normalize_text("\n".join(lines[:90]))
    if not scan_text:
        return []

    scanned: list[ParsedInstitution] = []
    padded_scan = f" {scan_text} "
    for spec in specs:
        for alias in spec.aliases:
            alias_norm = normalize_text(alias)
            if not alias_norm:
                continue
            if len(alias_norm.split()) == 1 and len(alias_norm) <= 3 and alias_norm not in ACRONYM_ALLOWLIST:
                continue
            if f" {alias_norm} " not in padded_scan:
                continue
            scanned.append(
                ParsedInstitution(
                    raw=alias,
                    markers=set(),
                    matched=MatchedInstitution(
                        canonical=spec.canonical,
                        raw=alias,
                        match_method="page_alias_scan",
                        confidence=0.72,
                    ),
                )
            )
            break

    return _dedupe_parsed_institutions(scanned)


def extract_institutions_for_paper(
    author_names: list[str],
    source_text: str,
    institution_specs: list[InstitutionSpec],
) -> InstitutionExtractionResult:
    lines = _split_source_lines(source_text)
    parsed_institutions = _parse_institutions(lines, institution_specs)
    parsed_institutions.extend(_scan_known_institutions_in_text(lines, institution_specs))
    parsed_institutions = _dedupe_parsed_institutions(parsed_institutions)
    parsed_authors = _parse_author_markers(lines)

    paper_level: set[str] = set()
    paper_level_detected: set[str] = set()
    unmapped: set[str] = set()
    for inst in parsed_institutions:
        paper_level_detected.add(inst.raw)
        if inst.matched:
            paper_level.add(inst.matched.canonical)
        else:
            unmapped.add(inst.raw)
            if _has_strong_affiliation_signal(inst.raw) and _contains_any_word(normalize_text(inst.raw), STRONG_AFFILIATION_KEYWORDS + COMPANY_KEYWORDS) and not _has_narrative_signal(inst.raw):
                paper_level.add(inst.raw)

    author_records: list[AuthorInstitutionRecord] = []
    for author_name in author_names:
        parsed_author = _match_author_name(author_name, parsed_authors)
        matched_for_author: list[MatchedInstitution] = []
        raw_for_author: set[str] = set()

        author_markers = parsed_author.markers if parsed_author else set()
        if not author_markers:
            author_markers = _markers_for_author_from_header(author_name, lines)

        if author_markers:
            for inst in parsed_institutions:
                if not author_markers.intersection(inst.markers):
                    continue
                raw_for_author.add(inst.raw)
                if inst.matched:
                    matched_for_author.append(inst.matched)

        if not matched_for_author and not raw_for_author and len(paper_level) == 1:
            matched_for_author = [
                MatchedInstitution(
                    canonical=canonical,
                    raw=canonical,
                    match_method="paper_level_fallback",
                    confidence=0.65,
                )
                for canonical in sorted(paper_level)
            ]
            raw_for_author.update(paper_level)

        author_records.append(
            AuthorInstitutionRecord(
                name=author_name,
                institutions=matched_for_author,
                raw_institutions=sorted(raw_for_author),
            )
        )

    filter_matches = sorted(paper_level)
    return InstitutionExtractionResult(
        authors=author_records,
        paper_level_institutions=sorted(paper_level),
        paper_level_detected_institutions=sorted(paper_level_detected),
        unmapped_raw_institutions=sorted(unmapped),
        filter_match=bool(filter_matches),
        filter_match_institutions=filter_matches,
    )


def _token_overlap(alias_norm: str, text_norm: str) -> float:
    generic_tokens = {
        "university",
        "institute",
        "college",
        "school",
        "department",
        "laboratory",
        "lab",
        "center",
        "centre",
        "technology",
        "technologies",
        "research",
    }
    alias_tokens = {token for token in alias_norm.split() if len(token) > 2 and token not in generic_tokens}
    text_tokens = {token for token in text_norm.split() if len(token) > 2}
    if len(alias_tokens) < 2:
        return 0.0
    return len(alias_tokens.intersection(text_tokens)) / len(alias_tokens)


def _is_acronym_alias(alias: str, alias_norm: str) -> bool:
    if len(alias_norm.split()) != 1:
        return False
    token = alias_norm.strip()
    if not token:
        return False
    stripped = re.sub(r"[^A-Za-z0-9]", "", alias)
    if 2 <= len(stripped) <= 6 and stripped.isupper():
        return True
    return token in ACRONYM_ALLOWLIST


def _expand_aliases(aliases: list[str]) -> set[str]:
    expanded: set[str] = {alias for alias in aliases if alias}
    for alias in list(expanded):
        words = [word for word in re.split(r"[\s\-]+", alias) if word]
        acronym = "".join(
            word[0]
            for word in words
            if word[0].isalnum() and normalize_text(word) not in ACRONYM_STOPWORDS
        )
        if len(acronym) >= 4 or acronym.lower() in ACRONYM_ALLOWLIST:
            expanded.add(acronym.upper() if acronym.lower() in ACRONYM_ALLOWLIST else acronym)
        if alias.startswith("UC "):
            expanded.add(alias.replace("UC ", "University of California ", 1))
            expanded.add(alias.replace("UC ", "University of California, ", 1))
    return expanded
