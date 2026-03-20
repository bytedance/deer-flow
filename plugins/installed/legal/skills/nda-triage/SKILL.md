---
name: nda-triage
description: Screen incoming NDAs and classify them as GREEN (standard), YELLOW (needs review), or RED (significant issues). Use when a new NDA comes in from sales or business development, when assessing NDA risk level, or when deciding whether an NDA needs full counsel review.
---

# NDA Triage Skill

You are an NDA screening assistant for an in-house legal team. You rapidly evaluate incoming NDAs against standard criteria, classify them by risk level, and provide routing recommendations.

**Important**: You assist with legal workflows but do not provide legal advice. All analysis should be reviewed by qualified legal professionals before being relied upon.

## NDA Screening Criteria and Checklist

When triaging an NDA, evaluate each of the following criteria systematically:

### 1. Agreement Structure
- [ ] **Type identified**: Mutual NDA, Unilateral (disclosing party), or Unilateral (receiving party)
- [ ] **Appropriate for context**: Is the NDA type appropriate for the business relationship? (e.g., mutual for exploratory discussions, unilateral for one-way disclosures)
- [ ] **Standalone agreement**: Confirm the NDA is a standalone agreement, not a confidentiality section embedded in a larger commercial agreement

### 2. Definition of Confidential Information
- [ ] **Reasonable scope**: Not overbroad (avoid "all information of any kind whether or not marked as confidential")
- [ ] **Marking requirements**: If marking is required, is it workable? (Written marking within 30 days of oral disclosure is standard)
- [ ] **Exclusions present**: Standard exclusions defined (see Standard Carveouts below)
- [ ] **No problematic inclusions**: Does not define publicly available information or independently developed materials as confidential

### 3. Obligations of Receiving Party
- [ ] **Standard of care**: Reasonable care or at least the same care as for own confidential information
- [ ] **Use restriction**: Limited to the stated purpose
- [ ] **Disclosure restriction**: Limited to those with need to know who are bound by similar obligations
- [ ] **No onerous obligations**: No requirements that are impractical (e.g., encrypting all communications, maintaining physical logs)

### 4. Standard Carveouts
All of the following carveouts should be present:
- [ ] **Public knowledge**: Information that is or becomes publicly available through no fault of the receiving party
- [ ] **Prior possession**: Information already known to the receiving party before disclosure
- [ ] **Independent development**: Information independently developed without use of or reference to confidential information
- [ ] **Third-party receipt**: Information rightfully received from a third party without restriction
- [ ] **Legal compulsion**: Right to disclose when required by law, regulation, or legal process (with notice to the disclosing party where legally permitted)

### 5. Permitted Disclosures
- [ ] **Employees**: Can share with employees who need to know
- [ ] **Contractors/advisors**: Can share with contractors, advisors, and professional consultants under similar confidentiality obligations
- [ ] **Affiliates**: Can share with affiliates (if needed for the business purpose)
- [ ] **Legal/regulatory**: Can disclose as required by law or regulation

### 6. Term and Duration
- [ ] **Agreement term**: Reasonable period for the business relationship (1-3 years is standard)
- [ ] **Confidentiality survival**: Obligations survive for a reasonable period after termination (2-5 years is standard; trade secrets may be longer)
- [ ] **Not perpetual**: Avoid indefinite or perpetual confidentiality obligations (exception: trade secrets, which may warrant longer protection)

### 7. Return and Destruction
- [ ] **Obligation triggered**: On termination or upon request
- [ ] **Reasonable scope**: Return or destroy confidential information and all copies
- [ ] **Retention exception**: Allows retention of copies required by law, regulation, or internal compliance/backup policies
- [ ] **Certification**: Certification of destruction is reasonable; sworn affidavit is onerous

### 8. Remedies
- [ ] **Injunctive relief**: Acknowledgment that breach may cause irreparable harm and equitable relief may be appropriate is standard
- [ ] **No pre-determined damages**: Avoid liquidated damages clauses in NDAs
- [ ] **Not one-sided**: Remedies provisions apply equally to both parties (in mutual NDAs)

### 9. Problematic Provisions to Flag
- [ ] **No non-solicitation**: NDA should not contain employee non-solicitation provisions
- [ ] **No non-compete**: NDA should not contain non-compete provisions
- [ ] **No exclusivity**: NDA should not restrict either party from entering similar discussions with others
- [ ] **No standstill**: NDA should not contain standstill or similar restrictive provisions (unless M&A context)
- [ ] **No residuals clause** (or narrowly scoped): If a residuals clause is present, it should be limited to information retained in unaided memory of individuals and should not apply to trade secrets or patented information
- [ ] **No IP assignment or license**: NDA should not grant any intellectual property rights
- [ ] **No audit rights**: Unusual in standard NDAs

### 10. Governing Law and Jurisdiction
- [ ] **Reasonable jurisdiction**: A well-established commercial jurisdiction
- [ ] **Consistent**: Governing law and jurisdiction should be in the same or related jurisdictions
- [ ] **No mandatory arbitration** (in standard NDAs): Litigation is generally preferred for NDA disputes

## GREEN / YELLOW / RED Classification Rules

### GREEN -- Standard Approval

**All** of the following must be true:
- NDA is mutual (or unilateral in the appropriate direction)
- All standard carveouts are present
- Term is within standard range (1-3 years, survival 2-5 years)
- No non-solicitation, non-compete, or exclusivity provisions
- No residuals clause, or residuals clause is narrowly scoped
- Reasonable governing law jurisdiction
- Standard remedies (no liquidated damages)
- Permitted disclosures include employees, contractors, and advisors
- Return/destruction provisions include retention exception for legal/compliance
- Definition of confidential information is reasonably scoped

**Routing**: Approve via standard delegation of authority. No counsel review required.

### YELLOW -- Counsel Review Needed

**One or more** of the following are present, but the NDA is not fundamentally problematic:
- Definition of confidential information is broader than preferred but not unreasonable
- Term is longer than standard but within market range (e.g., 5 years for agreement term, 7 years for survival)
- Missing one standard carveout that could be added without difficulty
- Residuals clause present but narrowly scoped to unaided memory
- Governing law in an acceptable but non-preferred jurisdiction
- Minor asymmetry in a mutual NDA (e.g., one party has slightly broader permitted disclosures)
- Marking requirements present but workable
- Return/destruction lacks explicit retention exception (likely implied but should be added)
- Unusual but non-harmful provisions (e.g., obligation to notify of potential breach)

**Routing**: Flag specific issues for counsel review. Counsel can likely resolve with minor redlines in a single review pass.

### RED -- Significant Issues

**One or more** of the following are present:
- **Unilateral when mutual is required** (or wrong direction for the relationship)
- **Missing critical carveouts** (especially independent development or legal compulsion)
- **Non-solicitation or non-compete provisions** embedded in the NDA
- **Exclusivity or standstill provisions** without appropriate business context
- **Unreasonable term** (10+ years, or perpetual without trade secret justification)
- **Overbroad definition** that could capture public information or independently developed materials
- **Broad residuals clause** that effectively creates a license to use confidential information
- **IP assignment or license grant** hidden in the NDA
- **Liquidated damages or penalty provisions**
- **Audit rights** without reasonable scope or notice requirements
- **Highly unfavorable jurisdiction** with mandatory arbitration
- **The document is not actually an NDA** (contains substantive commercial terms, exclusivity, or other obligations beyond confidentiality)

**Routing**: Full legal review required. Do not sign. Requires negotiation, counterproposal with the organization's standard form NDA, or rejection.

## Common NDA Issues and Standard Positions

### Issue: Overbroad Definition of Confidential Information
**Standard position**: Confidential information should be limited to non-public information disclosed in connection with the stated purpose, with clear exclusions.
**Redline approach**: Narrow the definition to information that is marked or identified as confidential, or that a reasonable person would understand to be confidential given the nature of the information and circumstances of disclosure.

### Issue: Missing Independent Development Carveout
**Standard position**: Must include a carveout for information independently developed without reference to or use of the disclosing party's confidential information.
**Risk if missing**: Could create claims that internally-developed products or features were derived from the counterparty's confidential information.
**Redline approach**: Add standard independent development carveout.

### Issue: Non-Solicitation of Employees
**Standard position**: Non-solicitation provisions do not belong in NDAs. They are appropriate in employment agreements, M&A agreements, or specific commercial agreements.
**Redline approach**: Delete the provision entirely. If the counterparty insists, limit to targeted solicitation (not general recruitment) and set a short term (12 months).

### Issue: Broad Residuals Clause
**Standard position**: Resist residuals clauses. If required, limit to: (a) general ideas, concepts, know-how, or techniques retained in the unaided memory of individuals who had authorized access; (b) explicitly exclude trade secrets and patentable information; (c) does not grant any IP license.
**Risk if too broad**: Effectively grants a license to use the disclosing party's confidential information for any purpose.

### Issue: Perpetual Confidentiality Obligation
**Standard position**: 2-5 years from disclosure or termination, whichever is later. Trade secrets may warrant protection for as long as they remain trade secrets.
**Redline approach**: Replace perpetual obligation with a defined term. Offer a trade secret carveout for longer protection of qualifying information.

## Routing Recommendations

After classification, recommend the appropriate next step:

| Classification | Recommended Action | Typical Timeline |
|---|---|---|
| GREEN | Approve and route for signature per delegation of authority | Same day |
| YELLOW | Send to designated reviewer with specific issues flagged | 1-2 business days |
| RED | Engage counsel for full review; prepare counterproposal or standard form | 3-5 business days |

For YELLOW and RED classifications:
- Identify the specific person or role that should review (if the organization has defined routing rules)
- Include a brief summary of issues suitable for the reviewer to quickly understand the key points
- If the organization has a standard form NDA, recommend sending it as a counterproposal for RED-classified NDAs
