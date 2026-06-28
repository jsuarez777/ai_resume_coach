# Iteration Log

| Date | Component | Change | Before | After | Delta | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-06-19 | Validator | Added Pydantic models for Resume and JobDescription with nested sub-models and corner-case tests | Validation tests: 0 | Validation tests: 75 passing | +75 | Keep |
| 2026-06-27 | Generator | Created initial template for casual-startup job description (v0.1) | Job templates: 0 | Job templates: 1 (casual-startup v0.1) | +1 | Keep |
| 2026-06-27 | Generator | Added prose fields (summary, description.overview, description.responsibilities) to JobDescription and refined templates for real-world posting imitation; added formal-corporate and technical-detailed style templates | Prose fields: 0; Job templates: 1 | Prose fields: 3; Job templates: 3 | +3 fields, +2 templates | Keep |
| 2026-06-28 | Generator | Added 3 style templates (mom-and-pop, government-public, ai-generated) covering small-business, public-sector, and low-quality/buzzword postings | Job templates: 3 | Job templates: 6 | +3 templates | Keep |
| 2026-06-28 | Generator | Added batch generation modes (even/random/custom/single) writing one JSONL across styles/roles; record writing_style on each job | Generation modes: 1 (single); style not recorded | Generation modes: 4; writing_style stamped per job | +3 modes, +1 field | Keep |
| 2026-06-28 | Generator | Parallel generation via bounded thread pool with in-place 429 backoff; added --temperature and elapsed-time reporting | Sequential (~6-7 s/job) | Parallel @30 workers (~0.39 s/job; 100 jobs in 39 s) | ~16x faster | Keep |
| 2026-06-28 | Generator | Moved niche classification from a hardcoded categories.yml flag to LLM classification per a niche definition in the output suffix | is_niche_role: hardcoded input (no detection) | is_niche_role: model-classified | detection added | Keep |
| 2026-06-28 | Generator | Expanded role set across diverse industries to improve data-generation diversity | Roles: 8 (7 industries) | Roles: 33 (22 industries) | +25 roles, +15 industries | Keep |
