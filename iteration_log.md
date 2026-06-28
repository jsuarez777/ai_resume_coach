# Iteration Log

| Date | Component | Change | Before | After | Delta | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-06-19 | Validator | Added Pydantic models for Resume and JobDescription with nested sub-models and corner-case tests | Validation tests: 0 | Validation tests: 75 passing | +75 | Keep |
| 2026-06-27 | Generator | Created initial template for casual-startup job description (v0.1) | Job templates: 0 | Job templates: 1 (casual-startup v0.1) | +1 | Keep |
| 2026-06-27 | Generator | Added prose fields (summary, description.overview, description.responsibilities) to JobDescription and refined templates for real-world posting imitation; added formal-corporate and technical-detailed style templates | Prose fields: 0; Job templates: 1 | Prose fields: 3; Job templates: 3 | +3 fields, +2 templates | Keep |
