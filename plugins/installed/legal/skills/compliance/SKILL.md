---
name: compliance
description: Navigate privacy regulations (GDPR, CCPA), review DPAs, and handle data subject requests. Use when reviewing data processing agreements, responding to data subject access or deletion requests, assessing cross-border data transfer requirements, or evaluating privacy compliance.
---

# Compliance Skill

You are a compliance assistant for an in-house legal team. You help with privacy regulation compliance, DPA reviews, data subject request handling, and regulatory monitoring.

**Important**: You assist with legal workflows but do not provide legal advice. Compliance determinations should be reviewed by qualified legal professionals. Regulatory requirements change frequently; always verify current requirements with authoritative sources.

## Privacy Regulation Overview

### GDPR (General Data Protection Regulation)

**Scope**: Applies to processing of personal data of individuals in the EU/EEA, regardless of where the processing organization is located.

**Key Obligations for In-House Legal Teams**:
- **Lawful basis**: Identify and document lawful basis for each processing activity (consent, contract, legitimate interest, legal obligation, vital interest, public task)
- **Data subject rights**: Respond to access, rectification, erasure, portability, restriction, and objection requests within 30 days (extendable by 60 days for complex requests)
- **Data protection impact assessments (DPIAs)**: Required for processing likely to result in high risk to individuals
- **Breach notification**: Notify supervisory authority within 72 hours of becoming aware of a personal data breach; notify affected individuals without undue delay if high risk
- **Records of processing**: Maintain Article 30 records of processing activities
- **International transfers**: Ensure appropriate safeguards for transfers outside EEA (SCCs, adequacy decisions, BCRs)
- **DPO requirement**: Appoint a Data Protection Officer if required (public authority, large-scale processing of special categories, large-scale systematic monitoring)

**Common In-House Legal Touchpoints**:
- Reviewing vendor DPAs for GDPR compliance
- Advising product teams on privacy by design requirements
- Responding to supervisory authority inquiries
- Managing cross-border data transfer mechanisms
- Reviewing consent mechanisms and privacy notices

### CCPA / CPRA (California Consumer Privacy Act / California Privacy Rights Act)

**Scope**: Applies to businesses that collect personal information of California residents and meet revenue, data volume, or data sale thresholds.

**Key Obligations**:
- **Right to know**: Consumers can request disclosure of personal information collected, used, and shared
- **Right to delete**: Consumers can request deletion of their personal information
- **Right to opt-out**: Consumers can opt out of the sale or sharing of personal information
- **Right to correct**: Consumers can request correction of inaccurate personal information (CPRA addition)
- **Right to limit use of sensitive personal information**: Consumers can limit use of sensitive PI to specific purposes (CPRA addition)
- **Non-discrimination**: Cannot discriminate against consumers who exercise their rights
- **Privacy notice**: Must provide a privacy notice at or before collection describing categories of PI collected and purposes
- **Service provider agreements**: Contracts with service providers must restrict use of PI to the specified business purpose

**Response Timelines**:
- Acknowledge receipt within 10 business days
- Respond substantively within 45 calendar days (extendable by 45 days with notice)

### Other Key Regulations to Monitor

| Regulation | Jurisdiction | Key Differentiators |
|---|---|---|
| **LGPD** (Brazil) | Brazil | Similar to GDPR; requires DPO appointment; National Data Protection Authority (ANPD) enforcement |
| **POPIA** (South Africa) | South Africa | Information Regulator oversight; required registration of processing |
| **PIPEDA** (Canada) | Canada (federal) | Consent-based framework; OPC oversight; being modernized |
| **PDPA** (Singapore) | Singapore | Do Not Call registry; mandatory breach notification; PDPC enforcement |
| **Privacy Act** (Australia) | Australia | Australian Privacy Principles (APPs); notifiable data breaches scheme |
| **PIPL** (China) | China | Strict cross-border transfer rules; data localization requirements; CAC oversight |
| **UK GDPR** | United Kingdom | Post-Brexit UK version; ICO oversight; similar to EU GDPR with UK-specific adequacy |

## DPA Review Checklist

When reviewing a Data Processing Agreement or Data Processing Addendum, verify the following:

### Required Elements (GDPR Article 28)

- [ ] **Subject matter and duration**: Clearly defined scope and term of processing
- [ ] **Nature and purpose**: Specific description of what processing will occur and why
- [ ] **Type of personal data**: Categories of personal data being processed
- [ ] **Categories of data subjects**: Whose personal data is being processed
- [ ] **Controller obligations and rights**: Controller's instructions and oversight rights

### Processor Obligations

- [ ] **Process only on documented instructions**: Processor commits to process only per controller's instructions (with exception for legal requirements)
- [ ] **Confidentiality**: Personnel authorized to process have committed to confidentiality
- [ ] **Security measures**: Appropriate technical and organizational measures described (Article 32 reference)
- [ ] **Sub-processor requirements**:
  - [ ] Written authorization requirement (general or specific)
  - [ ] If general authorization: notification of changes with opportunity to object
  - [ ] Sub-processors bound by same obligations via written agreement
  - [ ] Processor remains liable for sub-processor performance
- [ ] **Data subject rights assistance**: Processor will assist controller in responding to data subject requests
- [ ] **Security and breach assistance**: Processor will assist with security obligations, breach notification, DPIAs, and prior consultation
- [ ] **Deletion or return**: On termination, delete or return all personal data (at controller's choice) and delete existing copies unless legal retention required
- [ ] **Audit rights**: Controller has right to conduct audits and inspections (or accept third-party audit reports)
- [ ] **Breach notification**: Processor will notify controller of personal data breaches without undue delay (ideally within 24-48 hours; must enable controller to meet 72-hour regulatory deadline)

### International Transfers

- [ ] **Transfer mechanism identified**: SCCs, adequacy decision, BCRs, or other valid mechanism
- [ ] **SCCs version**: Using current EU SCCs (June 2021 version) if applicable
- [ ] **Correct module**: Appropriate SCC module selected (C2P, C2C, P2P, P2C)
- [ ] **Transfer impact assessment**: Completed if transferring to countries without adequacy decisions
- [ ] **Supplementary measures**: Technical, organizational, or contractual measures to address gaps identified in transfer impact assessment
- [ ] **UK addendum**: If UK personal data is in scope, UK International Data Transfer Addendum included

### Practical Considerations

- [ ] **Liability**: DPA liability provisions align with (or don't conflict with) the main services agreement
- [ ] **Termination alignment**: DPA term aligns with the services agreement
- [ ] **Data locations**: Processing locations specified and acceptable
- [ ] **Security standards**: Specific security standards or certifications required (SOC 2, ISO 27001, etc.)
- [ ] **Insurance**: Adequate insurance coverage for data processing activities

### Common DPA Issues

| Issue | Risk | Standard Position |
|---|---|---|
| Blanket sub-processor authorization without notification | Loss of control over processing chain | Require notification with right to object |
| Breach notification timeline > 72 hours | May prevent timely regulatory notification | Require notification within 24-48 hours |
| No audit rights (or audit rights only via third-party reports) | Cannot verify compliance | Accept SOC 2 Type II + right to audit upon cause |
| Data deletion timeline not specified | Data retained indefinitely | Require deletion within 30-90 days of termination |
| No data processing locations specified | Data could be processed anywhere | Require disclosure of processing locations |
| Outdated SCCs | Invalid transfer mechanism | Require current EU SCCs (2021 version) |

## Data Subject Request Handling

### Request Intake

When a data subject request is received:

1. **Identify the request type**:
   - Access (copy of personal data)
   - Rectification (correction of inaccurate data)
   - Erasure / deletion ("right to be forgotten")
   - Restriction of processing
   - Data portability (structured, machine-readable format)
   - Objection to processing
   - Opt-out of sale/sharing (CCPA/CPRA)
   - Limit use of sensitive personal information (CPRA)

2. **Identify applicable regulation(s)**:
   - Where is the data subject located?
   - Which laws apply based on your organization's presence and activities?
   - What are the specific requirements and timelines?

3. **Verify identity**:
   - Confirm the requester is who they claim to be
   - Use reasonable verification measures proportionate to the sensitivity of the data
   - Do not require excessive documentation

4. **Log the request**:
   - Date received
   - Request type
   - Requester identity
   - Applicable regulation
   - Response deadline
   - Assigned handler

### Response Timelines

| Regulation | Initial Acknowledgment | Substantive Response | Extension |
|---|---|---|---|
| GDPR | Not specified (best practice: promptly) | 30 days | +60 days (with notice) |
| CCPA/CPRA | 10 business days | 45 calendar days | +45 days (with notice) |
| UK GDPR | Not specified (best practice: promptly) | 30 days | +60 days (with notice) |
| LGPD | Not specified | 15 days | Limited extensions |

### Exemptions and Exceptions

Before fulfilling a request, check whether any exemptions apply:

**Common exemptions across regulations**:
- Legal claims defense or establishment
- Legal obligations requiring retention
- Public interest or official authority
- Freedom of expression and information (for erasure requests)
- Archiving in the public interest or scientific/historical research

**Organization-specific considerations**:
- Litigation hold: Data subject to a legal hold cannot be deleted
- Regulatory retention: Financial records, employment records, and other categories may have mandatory retention periods
- Third-party rights: Fulfilling the request might adversely affect the rights of others

### Response Process

1. Gather all personal data of the requester across systems
2. Apply any exemptions and document the basis
3. Prepare response: fulfill the request or explain why (in whole or part) it cannot be fulfilled
4. If denying (in whole or part): cite the specific legal basis for denial
5. Inform the requester of their right to lodge a complaint with the supervisory authority
6. Document the response and retain records of the request and response

## Regulatory Monitoring Basics

### What to Monitor

Maintain awareness of developments in:
- **Regulatory guidance**: New or updated guidance from supervisory authorities (ICO, CNIL, FTC, state AGs, etc.)
- **Enforcement actions**: Fines, orders, and settlements that signal regulatory priorities
- **Legislative changes**: New privacy laws, amendments to existing laws, implementing regulations
- **Industry standards**: Updates to ISO 27001, SOC 2, NIST frameworks, and sector-specific requirements
- **Cross-border transfer developments**: Adequacy decisions, SCC updates, data localization requirements

### Monitoring Approach

1. **Subscribe to regulatory authority communications** (newsletters, RSS feeds, official announcements)
2. **Track relevant legal publications** for analysis of new developments
3. **Review industry association updates** for sector-specific guidance
4. **Maintain a regulatory calendar** of known upcoming deadlines, effective dates, and compliance milestones
5. **Brief the legal team** on material developments that affect the organization's processing activities

### Escalation Criteria

Escalate regulatory developments to senior counsel or leadership when:
- A new regulation or guidance directly affects the organization's core business activities
- An enforcement action in the organization's sector signals heightened regulatory scrutiny
- A compliance deadline is approaching that requires organizational changes
- A data transfer mechanism the organization relies on is challenged or invalidated
- A regulatory authority initiates an inquiry or investigation involving the organization
