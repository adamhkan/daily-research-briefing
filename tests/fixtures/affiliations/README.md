# Affiliation source fixtures

These abbreviated arXiv front-matter excerpts and first-page PDF text preserve the layouts that exposed extraction bugs during the October 21 briefing review. Each HTML fixture names its source URL in a comment. The PDF text fixtures correspond to https://arxiv.org/pdf/2610.23872 (DUET) and https://arxiv.org/pdf/2610.26759 (Tactile In-Hand Object Rotation).

The fixtures preserve author names, institutional statements, notes, and superscripts; abstracts are replaced by a placeholder and paper bodies/assets are omitted. They support evidence extraction regression tests, not scientific-content or whole-library accuracy claims. Source papers retain their authorship and original arXiv license terms.

`diagnostic-author-mappings.json` preserves three source records and the corresponding model claims from saved diagnostic response `logs/diagnostics/39714391637-1/response-2.json`: DexOAK (2610.26762), agricultural manipulation (2610.26717), and RoboValue (2610.26663). It covers short institution quotes whose author associations are recorded in separate explicit affiliation fields, unrelated funding text in general context, and numbered author markers whose mappings must remain unassigned without direct evidence. The original source URLs remain in each block; the saved first-page context is retained as supplied to the model.
