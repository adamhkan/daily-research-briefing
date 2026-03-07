# Manual Institution Filtering Design Plan

This document proposes a deterministic (non-LLM) institution extraction and filtering pipeline that uses two inputs per paper:

1. A configurable institution list (allow-list with aliases)
2. The first page of the paper PDF (text + layout cues)

The goal is to accurately record **all author institutions** per paper and then filter papers by institution membership.

## 1) Objectives and non-goals

### Objectives
- Extract all author names on page 1.
- Extract all institution mentions on page 1.
- Resolve author ↔ institution mappings, especially superscript patterns.
- Produce structured output with confidence scores and audit traces.
- Filter papers by whether any extracted institution matches your configured institution list.

### Non-goals (v1)
- Perfect extraction from scanned/image-only PDFs without OCR fallback.
- Full global institution canonicalization from arbitrary free text.

## 2) Input contract

### Institution list format
Use a YAML/JSON config that supports canonical names and aliases:

```yaml
institutions:
  - canonical: "Massachusetts Institute of Technology"
    aliases: ["MIT", "M.I.T.", "Mass. Institute of Technology"]
  - canonical: "Carnegie Mellon University"
    aliases: ["CMU", "Carnegie Mellon"]
```

Precompute normalized forms for all canonical names and aliases:
- lowercase
- strip punctuation/extra whitespace
- normalize unicode accents
- remove boilerplate suffix variants where safe (e.g., "univ.")

### First-page input
For each paper, store:
- raw first-page text
- optional line/block boundaries from the PDF extractor
- optional positional tokens (x/y coordinates) if available

The design works with text-only extraction first, and improves with layout tokens.

## 3) Extraction pipeline architecture

### Stage A: Page-1 segmentation
Identify likely regions:
- title block
- author line(s)
- affiliation block
- footnotes / correspondence lines

Heuristics:
- Institution indicators: `University`, `Institute`, `Lab`, `Department`, `School`, `Center`, `Centre`, `College`, company suffixes (`Inc`, `Ltd`, `AI Research`, etc.)
- Contact indicators: emails, "@", "corresponding author"
- Marker patterns: superscripts (`1`, `2`, `*`, `†`, `‡`, `a`, `b`)

Output: candidate `author_spans`, `institution_spans`, `marker_tokens`.

### Stage B: Parse authors and markers
Extract author entries using comma/and separators and superscript tags.
Examples:
- `Alice Smith1,2, Bob Lee2, Carol Ng1`
- `Alice Smith*, Bob Lee†`
- `Alice Smitha, Bob Leeb`

For each author record:
- `author_name`
- `author_markers` (set)

### Stage C: Parse institution lines and markers
Extract institution entries and associated markers.
Examples:
- `1 MIT, Cambridge, MA`
- `2 CMU, Pittsburgh, PA`
- `* Stanford University`
- `a University of Tokyo`

For each institution record:
- `raw_affiliation`
- `inst_markers` (set)
- `canonical_match` (nullable)
- `match_method` (`exact_alias`, `fuzzy_alias`, `none`)

### Stage D: Marker-based mapping (primary)
Map authors to institutions where marker overlap exists:
- `author_markers ∩ inst_markers != ∅`

Allow multi-affiliation per author.

### Stage E: Fallback mapping rules
When markers are absent/ambiguous:
1. **Grouped-line heuristic:** if authors appear in one block and institutions listed in same order, map by index.
2. **Email-domain heuristic:** infer institution by domain when explicit (`@mit.edu` → MIT alias map).
3. **Global paper-level institutions:** if author mapping fails, still record paper-level institution set from extracted institution lines.

Every fallback assignment gets lower confidence than marker-based assignments.

## 4) Institution normalization & matching

### Canonicalization strategy
For each extracted affiliation string:
1. normalize text
2. alias exact match against precomputed alias map
3. optional fuzzy match (token-set ratio / Jaccard) above strict threshold
4. if still unmatched, keep as `unmapped_raw_institution`

Recommended matching policy:
- use exact/alias matches for filter decisions (high precision)
- keep fuzzy matches as `candidate_matches` unless score exceeds conservative threshold

## 5) Output schema (per paper)

```json
{
  "paper_id": "arxiv:xxxx.xxxxx",
  "authors": [
    {
      "name": "Alice Smith",
      "institutions": [
        {
          "canonical": "Massachusetts Institute of Technology",
          "raw": "MIT, Cambridge, MA",
          "confidence": 0.98,
          "evidence": "marker_match:1"
        }
      ]
    }
  ],
  "paper_level_institutions": [
    "Massachusetts Institute of Technology",
    "Carnegie Mellon University"
  ],
  "unmapped_raw_institutions": ["Robotics Institute, Pittsburgh"],
  "filter_match": true,
  "filter_match_institutions": ["Massachusetts Institute of Technology"],
  "extraction_confidence": "high"
}
```

## 6) Confidence and auditability

Assign confidence by rule source:
- marker-based mapping: high (0.9-1.0)
- order-based fallback: medium (0.6-0.8)
- email-domain inference: medium (0.6-0.75)
- fuzzy-only institution mapping: low/medium depending threshold

Persist audit traces:
- parsed author tokens
- parsed institution tokens
- matched markers
- fallback rule used

This lets you inspect extraction errors quickly and iteratively improve rules.

## 7) Filtering policy

A paper passes institution filtering when:
- any canonical institution in `paper_level_institutions` intersects allow-list canonical names

Optional strict mode:
- pass only if an **author-level** mapping exists (not paper-level-only fallback)

## 8) Implementation plan (incremental)

### Milestone 1: Deterministic MVP
- Build parser for marker-based patterns.
- Add alias normalization map.
- Output paper-level institution set + author mappings where available.
- Integrate with existing pipeline in place of LLM institution filtering.

### Milestone 2: Robustness
- Add order-based and email-domain fallbacks.
- Add confidence scoring and debug logs.
- Add unmapped institution capture.

### Milestone 3: Quality loop
- Create a gold evaluation set (50-100 papers across formats).
- Track metrics:
  - institution extraction precision/recall
  - author↔institution mapping accuracy
  - filter false positives/false negatives
- Tune alias lists and heuristics.

## 9) Edge cases to explicitly handle

- Consortia papers with many affiliations.
- Mixed symbol systems (`1`, `*`, `a`) on same page.
- Shared footnotes that are not affiliations.
- Multiple departments within same university (should collapse to canonical university when desired).
- Corporate + academic co-authorship.
- Non-English institution strings.

## 10) Operational recommendations

- Keep a versioned institution alias registry in `config/` and review weekly.
- Log unmatched affiliation strings for curation.
- Add a "manual override" file to force-map recurring unmatched institutions.
- Store extraction artifacts so downstream summaries can show transparent institution provenance.

---

If you implement this design, you get a transparent and debuggable institution filter that is typically more reliable than prompt-only LLM extraction for superscript-heavy academic title pages.
