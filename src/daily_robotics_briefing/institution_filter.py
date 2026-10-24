"""Conservative institution identity matching; source-role extraction lives in affiliations."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class InstitutionSpec:
    canonical: str
    aliases: list[str]


@dataclass
class MatchedInstitution:
    canonical: str
    raw: str
    match_method: str = 'curated_alias'
    confidence: float = 1.0


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
        return asdict(self)


def normalize_text(value: str) -> str:
    value = value.translate(str.maketrans({'’': "'", '‘': "'", 'ʼ': "'"}))
    value = ''.join(c for c in unicodedata.normalize('NFKD', value)
                    if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[\W_]+', ' ', value.casefold()).split())


def _expand_aliases(aliases: list[str]) -> set[str]:
    # Only explicit aliases and the unambiguous UC expansion; never invent acronyms.
    result = set(aliases)
    for alias in aliases:
        if alias.startswith('UC '):
            result.update([alias.replace('UC ', 'University of California ', 1),
                           alias.replace('UC ', 'University of California, ', 1)])
    return result


def build_institution_specs(entries: list[object]) -> list[InstitutionSpec]:
    specs: list[InstitutionSpec] = []
    for entry in entries:
        if isinstance(entry, str):
            canonical, aliases = entry.strip(), []
        elif isinstance(entry, dict):
            canonical = str(entry.get('canonical', '')).strip()
            aliases = [str(a).strip() for a in entry.get('aliases', []) if str(a).strip()]
        else:
            continue
        if not canonical:
            continue
        expanded = _expand_aliases([canonical, *aliases])
        # Configured canonical names take precedence over common-library synonyms.
        prior = next((i for i, spec in enumerate(specs)
                      if normalize_text(canonical) in {normalize_text(a) for a in spec.aliases}
                      or normalize_text(spec.canonical) in {normalize_text(a) for a in expanded}), None)
        if prior is None:
            specs.append(InstitutionSpec(canonical, sorted(expanded)))
        else:
            specs[prior] = InstitutionSpec(specs[prior].canonical, sorted(set(specs[prior].aliases) | expanded))
    return specs


def _cleanup_affiliation_fragment(text: str) -> str:
    # A marker must be separated from the name. Never consume an attached letter.
    text = re.sub(r'^\s*(?:Affiliation:|thanks:)\s*', '', text, flags=re.I)
    text = re.sub(r'^\s*(?:\d+[.)]?\s*|[a-z][.)]\s+|[*†‡]+\s*)', '', text)
    text = re.sub(r'\S+@\S+|https?://\S+', '', text)
    return ' '.join(text.split()).strip(' ,;')


def alias_hits(text: str, specs: list[InstitutionSpec]) -> list[tuple[str, InstitutionSpec]]:
    """Longest nonoverlapping explicit alias hits; no fuzzy/token-subset identities."""
    clean = re.sub(r'\S+@\S+|https?://\S+', lambda m: ' ' * len(m[0]), text)
    clean = clean.translate(str.maketrans({'’': "'", '‘': "'", 'ʼ': "'"}))
    chars, offsets = [], []
    for index, char in enumerate(clean):
        if index and char.isupper() and clean[index - 1].isdigit():
            chars.append(' ')
            offsets.append(index)
        for value in unicodedata.normalize('NFKD', char).encode('ascii', 'ignore').decode().lower():
            value = value if value.isalnum() else ' '
            if value == ' ' and (not chars or chars[-1] == ' '):
                continue
            chars.append(value)
            offsets.append(index)
    normalized = ''.join(chars)
    hits = []
    for spec in specs:
        for alias in spec.aliases:
            needle = normalize_text(alias)
            if not needle:
                continue
            # Geographic shorthand is accepted only as an entire institution field.
            if needle in {'berkeley', 'stanford', 'cambridge', 'oxford', 'penn', 'imperial', 'washington'}:
                if normalized.strip() != needle:
                    continue
            for match in re.finditer(r'(?<!\w)' + re.escape(needle) + r'(?!\w)', normalized):
                raw = text[offsets[match.start()]:offsets[match.end() - 1] + 1]
                hits.append((match.start(), match.end(), raw, spec))
    accepted = []
    for start, end, alias, spec in sorted(hits, key=lambda h: (-(h[1]-h[0]), h[0])):
        if any(start < b and end > a for a, b, _, _ in accepted):
            continue
        accepted.append((start, end, alias, spec))
    return [(alias, spec) for _, _, alias, spec in sorted(accepted)]


def _match_institution(raw_affiliation: str, specs: list[InstitutionSpec]) -> MatchedInstitution | None:
    return resolve_institution(raw_affiliation, specs)


def plausible_institution(value: str) -> bool:
    normalized = normalize_text(value)
    return any(char.isalpha() for char in value) and normalized not in {
        'your institution', 'your university', 'institution name', 'affiliation',
    }


def resolve_institution(raw: str, specs: list[InstitutionSpec]) -> MatchedInstitution | None:
    """Resolve evidence fields without guessing a parent from a qualified name."""
    normalized = normalize_text(raw)
    if not normalized:
        return None
    exact = [s for s in specs if normalized in {normalize_text(a) for a in s.aliases}]
    if len(exact) == 1:
        return MatchedInstitution(exact[0].canonical, raw)
    return None


def extraction_from_evidence(
    author_names: list[str], evidence: list[dict], institution_specs: list[InstitutionSpec],
) -> InstitutionExtractionResult:
    current = [e for e in evidence if e['role'] == 'author_affiliation']
    resolved: list[tuple[dict, str, MatchedInstitution | None]] = []
    for item in current:
        raw = item['institution'].strip()
        # Catalog aliases normalize the model-returned name for filter matching.
        match = resolve_institution(raw, institution_specs)
        resolved.append((item, raw, match))
    institutions = sorted({match.canonical if match else raw for _, raw, match in resolved})
    authors = []
    for name in author_names:
        items = [(raw, match) for item, raw, match in resolved if name in item.get('authors', [])]
        authors.append(AuthorInstitutionRecord(name, [m for _, m in items if m], sorted({raw for raw, _ in items})))
    return InstitutionExtractionResult(
        authors, institutions, sorted({raw for _, raw, _ in resolved}),
        sorted({raw for _, raw, match in resolved if match is None}),
        bool(institutions), institutions,
    )


def extract_institutions_for_paper(
    author_names: list[str], source_text: str, institution_specs: list[InstitutionSpec],
) -> InstitutionExtractionResult:
    """Compatibility helper for explicit affiliation fields, never whole-paper text."""
    evidence = []
    for line in source_text.splitlines():
        if re.search(r'\b(abstract|references|supported|funded|acknowledg\w*)\b', line, re.I):
            continue
        for alias, _ in alias_hits(line, institution_specs):
            evidence.append({'institution': alias, 'role': 'author_affiliation', 'authors': []})
    return extraction_from_evidence(author_names, evidence, institution_specs)
