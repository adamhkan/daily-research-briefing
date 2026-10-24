"""Strict output contracts for the three model tasks."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Classification(StrictOutput):
    paper_id: str
    topic_relevance: Literal[0, 1, 2, 3]
    contribution_score: Literal[0, 1, 2, 3]
    rationale: str


class ClassificationOutput(StrictOutput):
    papers: list[Classification]


class SummaryClaim(StrictOutput):
    claim: str = Field(min_length=1)


class PaperOverview(StrictOutput):
    paper_id: str
    claims: list[SummaryClaim] = Field(min_length=1, max_length=3)


class OverviewOutput(StrictOutput):
    papers: list[PaperOverview]


class SummaryBullet(StrictOutput):
    text: str = Field(min_length=1)
    paper_ids: list[str] = Field(min_length=1)


class ExecutiveOutput(StrictOutput):
    bullets: list[SummaryBullet] = Field(min_length=1, max_length=6)


class AffiliationClaim(StrictOutput):
    institution: str = Field(min_length=1, description=(
        'One clean organization name identified from supplied front matter, without department prefixes or addresses; '
        'retain identity-defining campus, branch, and organization-unit qualifiers. '
        'Keep unfamiliar names and source abbreviations; do not invent a parent or canonical name.'
        ' Restore unambiguous missing word spaces and normalize line breaks.'
    ))
    authors: list[str]
    block_id: str
    role: Literal['author_affiliation', 'work_done_at', 'former_affiliation', 'funder']


class PaperAffiliations(StrictOutput):
    paper_id: str
    complete: bool
    affiliations: list[AffiliationClaim]


class AffiliationOutput(StrictOutput):
    papers: list[PaperAffiliations]
