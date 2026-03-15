---
name: academic-integrity
description: Use this skill to check manuscripts for academic integrity issues before submission. Performs citation verification (checks if cited papers actually exist), reference completeness audit, logical consistency analysis, claim-evidence alignment, and compliance with publication ethics guidelines (COPE, ICMJE, CRediT). Trigger on queries like "check my paper", "academic integrity review", "verify my citations", "pre-submission check", "citation audit", "integrity check", or any request involving manuscript quality assurance before submission.
---

# Academic Integrity Check Skill

## Overview

This skill provides a systematic methodology for checking academic manuscripts for integrity issues before submission. It verifies citation accuracy, checks logical consistency, audits claim-evidence alignment, and ensures compliance with publication ethics standards.

## When to Use This Skill

**Always load this skill when:**

- User asks to review or check their paper before submission
- User wants to verify that all citations are real and accurate
- User needs a pre-submission quality audit
- User asks about publication ethics or academic integrity
- User wants to check claim-evidence alignment
- User is preparing a manuscript for a high-impact venue

## Core Capabilities

| Capability | Description |
|-----------|-------------|
| **Citation Verification** | Verify cited papers exist via Semantic Scholar / CrossRef API |
| **Reference Completeness** | Check for orphan citations and uncited references |
| **Claim-Evidence Audit** | Verify that claims are supported by cited evidence |
| **Logical Consistency** | Check abstract vs. body, data vs. conclusions alignment |
| **Ethics Compliance** | COPE guidelines, CRediT authorship, conflict of interest |
| **Statistical Reporting** | Check completeness of statistical reports |
| **Formatting Audit** | Citation format consistency, figure/table numbering |

## Workflow

### Phase 1: Citation Verification

#### Step 1.1: Extract All Citations

Parse the manuscript to identify all cited references. For each citation, extract:
- Author names
- Year
- Title (or partial title)
- Venue (journal/conference)

#### Step 1.2: Verify Citations Against Academic Databases

**Preferred Method:** If academic tools are available, use `semantic_scholar_search(query="paper title")` and `crossref_lookup(doi="10.xxxx/xxxxx")` directly for faster, more reliable verification.

**Fallback Method:** For each cited paper, verify it exists using Semantic Scholar or CrossRef:

```bash
python -c "
import json, urllib.request, urllib.parse

citations_to_verify = [
    {'authors': 'Vaswani et al.', 'year': 2017, 'title_fragment': 'Attention Is All You Need'},
    {'authors': 'Devlin et al.', 'year': 2019, 'title_fragment': 'BERT'},
]

print('=== Citation Verification Report ===')
for i, cite in enumerate(citations_to_verify, 1):
    query = urllib.parse.quote(cite['title_fragment'])
    url = f'https://api.semanticscholar.org/graph/v1/paper/search?query={query}&limit=3&fields=title,authors,year,venue,externalIds'
    req = urllib.request.Request(url, headers={'User-Agent': 'DeerFlow/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        papers = data.get('data', [])
        if papers:
            best = papers[0]
            match_year = best.get('year') == cite['year']
            doi = (best.get('externalIds') or {}).get('DOI', 'N/A')
            status = '✅ VERIFIED' if match_year else '⚠️ YEAR MISMATCH'
            print(f'{i}. {status}: {cite[\"title_fragment\"]}')
            print(f'   Found: {best[\"title\"]} ({best.get(\"year\")}) DOI: {doi}')
        else:
            print(f'{i}. ❌ NOT FOUND: {cite[\"title_fragment\"]}')
            print(f'   Could not verify this citation — please check manually')
    except Exception as e:
        print(f'{i}. ⚠️ ERROR: {cite[\"title_fragment\"]} — {e}')
    print()
"
```

#### Step 1.3: Generate Verification Report

```markdown
## Citation Verification Report

| # | Citation | Status | DOI | Notes |
|---|---------|:------:|-----|-------|
| 1 | Vaswani et al. (2017) | ✅ Verified | 10.xxx | — |
| 2 | Smith et al. (2023) | ❌ Not Found | — | Cannot locate this paper |
| 3 | Chen et al. (2022) | ⚠️ Year Mismatch | 10.xxx | Published 2021, not 2022 |

**Summary**: X/Y citations verified (Z% verification rate)
**Action Required**: N citations need manual verification
```

### Phase 2: Reference Completeness Audit

#### Step 2.1: Cross-Check Citations vs. Reference List

1. **Orphan In-Text Citations**: References cited in text but missing from the reference list
2. **Uncited References**: Entries in the reference list that are never cited in the text
3. **Numbering Consistency**: For numbered citation styles, verify sequential numbering

#### Step 2.2: Generate Completeness Report

```markdown
## Reference Completeness Report

### Orphan Citations (cited but not in reference list)
- [Author, Year] — cited on page X, not found in references

### Uncited References (in reference list but never cited)
- [Reference entry] — appears in bibliography but never referenced in text

### Citation Format Issues
- Inconsistent format: [details]
- Missing DOIs: [list]
```

### Phase 3: Claim-Evidence Alignment

#### Step 3.1: Identify Key Claims

Scan the manuscript for strong claims (statements of fact, causal assertions, comparisons):
- Claims in Abstract
- Claims in Introduction (especially contributions)
- Claims in Results/Discussion
- Claims in Conclusion

#### Step 3.2: Verify Evidence Support

For each claim, check:
1. Is it supported by data presented in the paper?
2. Is it supported by a citation?
3. Is the claim strength appropriate given the evidence? (overclaiming check)
4. Does the evidence actually support the claim as stated?

```markdown
## Claim-Evidence Audit

| # | Claim | Location | Evidence Type | Status |
|---|-------|----------|:------------:|:------:|
| 1 | "Our method achieves SOTA" | Abstract | Table 2 | ✅ Supported |
| 2 | "X causes Y" | Sec 5.1 | Correlation data | ⚠️ Overclaim — correlation ≠ causation |
| 3 | "This is the first work to..." | Intro | No citation | ❌ Unsupported — needs verification |

### Overclaiming Flags
- Claim 2: Change "causes" to "is associated with" or provide causal evidence
- Claim 3: Add "To the best of our knowledge, ..." hedging
```

### Phase 4: Logical Consistency Check

#### Step 4.1: Abstract-Body Alignment

Verify that:
- All claims in the Abstract appear in the main text
- Quantitative results in Abstract match those in Results tables
- The methodology described in Abstract matches the Methods section
- Conclusions in Abstract are consistent with the Discussion

#### Step 4.2: Data-Conclusion Alignment

- Do the conclusions follow logically from the results?
- Are there results presented but not discussed?
- Are there conclusions not supported by any presented results?
- Are limitations acknowledged that could affect conclusions?

#### Step 4.3: Internal Consistency

- Are the same numbers/statistics used consistently throughout?
- Do cross-references (Fig./Table/Eq. numbers) match?
- Is terminology used consistently (no switching between synonyms without reason)?
- Are abbreviations defined before use and used consistently?

### Phase 5: Publication Ethics Compliance

#### Step 5.1: COPE (Committee on Publication Ethics) Guidelines

Check for compliance with COPE best practices:

- [ ] **Authorship**: All listed authors meet ICMJE criteria (substantial contribution + drafting/revision + approval + accountability)
- [ ] **CRediT Statement**: Author contributions described using CRediT taxonomy (Conceptualization, Methodology, Software, Validation, Formal Analysis, Investigation, Data Curation, Writing—Original Draft, Writing—Review & Editing, Visualization, Supervision, Project Administration, Funding Acquisition)
- [ ] **Conflict of Interest**: COI declaration present (even if "none to declare")
- [ ] **Funding**: All funding sources acknowledged
- [ ] **Ethics Approval**: IRB/Ethics committee approval stated (for human/animal studies)
- [ ] **Informed Consent**: Consent statement present (for human studies)
- [ ] **Data Availability**: Data availability statement present
- [ ] **Code Availability**: Code/software availability statement present
- [ ] **Prior Publication**: Declaration that work is original and not under review elsewhere
- [ ] **AI Disclosure**: Disclosure of AI tool usage in writing (if applicable, per venue policy)

#### Step 5.2: Statistical Reporting Completeness

For empirical papers, verify statistical reporting:

- [ ] All statistical tests report: test statistic, degrees of freedom, p-value
- [ ] Effect sizes reported alongside p-values
- [ ] Confidence intervals provided for key estimates
- [ ] Multiple comparison corrections applied (if applicable)
- [ ] Exact p-values reported (not just "p < 0.05"), except when very small (p < 0.001)
- [ ] Sample sizes reported for all analyses
- [ ] Assumptions tested and reported (normality, homoscedasticity)

### Phase 6: Generate Integrity Report

Compile all findings into a comprehensive report:

```markdown
# Academic Integrity Check Report

**Manuscript**: [Title]
**Date**: [Date]
**Overall Status**: [PASS / PASS WITH WARNINGS / ISSUES FOUND]

## Summary
- Citations verified: X/Y (Z%)
- Reference completeness: [OK / Issues found]
- Claim-evidence alignment: [OK / N overclaims found]
- Logical consistency: [OK / N issues found]
- Ethics compliance: [OK / N items missing]

## Critical Issues (Must Fix)
1. [Issue description and fix]

## Warnings (Should Fix)
1. [Warning description and suggestion]

## Recommendations (Nice to Fix)
1. [Recommendation]

## Detailed Findings
[Sections from Phases 1-5]
```

## Integration with Other Skills

- **academic-writing**: Run integrity check after generating a manuscript
- **literature-review**: Cross-reference citations with the literature database
- **statistical-analysis**: Verify statistical reporting completeness

## Output Files

All outputs saved to `/mnt/user-data/outputs/`:
- `integrity_report.md` — Full integrity check report
- `citation_verification.md` — Citation verification details

Use `present_files` to share outputs with the user.

## Notes

- Citation verification depends on API availability — some papers may not be indexed
- This skill checks for common integrity issues but is NOT a replacement for formal plagiarism detection tools
- For Chinese papers, citation verification may be limited (CNKI is not API-accessible)
- Always recommend the user do a final manual review
- AI disclosure requirements vary by venue — check the specific journal/conference policy
