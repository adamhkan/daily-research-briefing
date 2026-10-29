# Affiliation failures, October 29, 2026

## Fatal run

Run `40920894598`, attempt 1, failed after two affiliation responses because at
least one returned author name did not exactly match the supplied author list.
This rejected the entire batch, including its institution results. The saved log
does not contain the response or offending name/paper ID, so it cannot establish
whether the mismatch was initials, name order, spelling, or an unrelated name.
The final collection message about `2610.35877` does not identify the bad response.

Author-name equality is no longer a fatal validation check. The prompt requests
exact metadata spellings; raw returned mappings remain in the JSON. Per-author
catalog records still attach only to exact author names, while institution
selection uses the paper-level institution list. Schema, paper-ID coverage, and
source-block references remain checked. There is no replacement model output,
factual filter, or fallback summary.

## Missing institutions in saved reports

| Report | Papers | Reported unknown | Skipped due to source budget |
| --- | ---: | ---: | ---: |
| 2026-10-27 | 64 | 5 | 0 |
| 2026-10-28 | 138 | 54 | 44 |

On October 28, the sequential 120,000-character cap excluded 44 later papers
entirely, even when their saved blocks explicitly named institutions. Examples:

- `2610.33476`: Tongji University.
- `2610.35044`: Tsinghua University and Xiaomi EV.
- `2610.33715`: University of Naples Federico II.

The allocator now distributes the same cap across uncached papers, giving short
inputs their full length and sharing the remainder among longer inputs. Within
each input, dedicated affiliation/note blocks retain priority over header context.
Batch size, model, output limits, per-paper maximum, and total cap are unchanged.

An offline replay of source selection, with no cache and a stub returning empty
affiliations, produced:

| Report | Papers sent to extraction | Source characters | Truncated inputs |
| --- | ---: | ---: | ---: |
| 2026-10-27 | 64 | 73,924 | 3 |
| 2026-10-28 | 138 | 120,000 | 49 |

All 44 previously excluded October 28 papers now receive model input; 32 receive
all their saved blocks. These are input-coverage results, not measured model
accuracy or proof that every affiliation will now be identified. Sharing a fixed
cap necessarily shortens some inputs. Truncated results remain ineligible for
caching, even if the model marks them complete.

## First-page collection

The pinned PDF `2610.32259v1` was downloaded and its first-page layout text
inspected. The footer states that Jiahao Hu, Xiangru Wang, and Weisong Wen are
with The Hong Kong Polytechnic University, and Qian Meng is with Southeast
University. Neither institution was in the saved extraction input: collection
only recognized statements containing the literal words “author(s) is/are with.”

Collection now also recognizes named-author “is/are with” and “is/are affiliated
with” statements. Up to three continuation lines are retained; punctuation in
one column no longer cuts off an institution wrapping in the other column. The
model still decides roles, including distinguishing nearby funding text.

This does not solve every possible first-page layout. Logos without extractable
names, differently phrased notes, PDF size/download failures, and truncated
snippets can still leave institutions unidentified. Some saved empty results
also reflect explicitly independent researchers or inputs containing only authors
and email addresses; empty institution lists alone do not prove extraction errors.

Collection logs now say model extraction is pending when source blocks exist.
The old “Affiliation unresolved” warning was emitted before model extraction and
was not a statement about the final briefing.

## Verification

Regression tests cover nonexact author spellings without a retry, invalid block
references still failing, fair allocation and redistribution under a fixed cap,
zero budget, truncated-cache behavior, named two-column PDF footnotes, and pending
collection logging. The existing offline suite also checks institution-role
handling, full pipeline serialization, selection, and report rendering.
No OpenAI API calls were made, and historical reports were not rewritten.
