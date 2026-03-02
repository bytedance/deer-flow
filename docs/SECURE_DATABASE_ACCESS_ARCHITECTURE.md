# Secure Database Access Architecture for Government Deployments

> Proposed protocols and design patterns for Thinktank.ai agents accessing sensitive relational databases via MCP in government settings.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [MCP Transport and Authorization](#2-mcp-transport-and-authorization)
3. [MCP Server Isolation and Sandboxing](#3-mcp-server-isolation-and-sandboxing)
4. [MCP Gateway and Proxy Patterns](#4-mcp-gateway-and-proxy-patterns)
5. [Known Vulnerabilities and Attack Vectors](#5-known-vulnerabilities-and-attack-vectors)
6. [Government Compliance Frameworks](#6-government-compliance-frameworks)
7. [Zero Trust Architecture for AI Agents](#7-zero-trust-architecture-for-ai-agents)
8. [Confidential Computing for AI Workloads](#8-confidential-computing-for-ai-workloads)
9. [Data Loss Prevention for LLM Systems](#9-data-loss-prevention-for-llm-systems)
10. [Secure Database Proxy and Access Broker Patterns](#10-secure-database-proxy-and-access-broker-patterns)
11. [Dynamic Credential Management](#11-dynamic-credential-management)
12. [SQL Injection Prevention in AI-Generated Queries](#12-sql-injection-prevention-in-ai-generated-queries)
13. [Multi-Tenant Database Isolation Patterns](#13-multi-tenant-database-isolation-patterns)
14. [Data Masking and Tokenization](#14-data-masking-and-tokenization)
15. [Semantic Layers and Data Virtualization](#15-semantic-layers-and-data-virtualization)
16. [Human-in-the-Loop Patterns](#16-human-in-the-loop-patterns)
17. [Differential Privacy for Query Results](#17-differential-privacy-for-query-results)
18. [Audit Logging and Compliance](#18-audit-logging-and-compliance)
19. [Tool Use Sandboxing Patterns](#19-tool-use-sandboxing-patterns)
20. [Proposed Reference Architecture](#20-proposed-reference-architecture)
21. [Responsibility Matrix: Agent-Side vs Client-Side](#21-responsibility-matrix-agent-side-vs-client-side)
22. [References](#22-references)

---

## 1. Executive Summary

This report synthesizes research on securing AI agent access to sensitive government
databases. The architecture follows a defense-in-depth model with 8 distinct security
layers, each designed to catch failures in the layers above it.

The core principles are:

- **No single layer is sufficient.** Each layer assumes the ones above it can be breached.
- **The LLM is untrusted.** Generated SQL, tool selections, and natural-language responses
  are all treated as potentially dangerous outputs requiring validation.
- **Credentials are ephemeral.** No standing database access; just-in-time credentials
  with short TTLs, auto-revoked after use.
- **Audit everything.** Every tool invocation, query, and response is logged in
  tamper-evident storage for compliance and forensics.

---

## 2. MCP Transport and Authorization

### 2.1 Transport Options

The MCP specification (June 2025 revision) defines three transports:

| Transport | Use Case | Security Model |
|-----------|----------|----------------|
| **stdio** | Local servers (dev/testing) | OS-level process isolation; no network exposure |
| **Streamable HTTP** | Remote servers (production) | TLS 1.2+, session management, Origin validation |
| **SSE** | Deprecated | Replaced by Streamable HTTP |

For production government deployments, **Streamable HTTP with mutual TLS** is the
recommended transport for remote database MCP servers.

### 2.2 OAuth 2.1 Authorization

The June 2025 MCP spec revision reclassified MCP servers as **OAuth 2.1 Resource Servers**:

| Requirement | Mandate |
|-------------|---------|
| OAuth 2.1 implementation | MUST |
| PKCE (Proof Key for Code Exchange) | MUST for all clients |
| Protected Resource Metadata (RFC 9728) | MUST for MCP servers |
| Authorization Server Metadata (RFC 8414) | MUST |
| Dynamic Client Registration (RFC 7591) | SHOULD |
| Resource Indicators (RFC 8707) | MUST for clients |
| Bearer tokens via Authorization header | MUST (never in URL query strings) |
| Token audience validation | MUST |
| Token passthrough | EXPLICITLY FORBIDDEN |

Resource Indicators (RFC 8707) bind tokens to specific MCP server audiences, preventing
a compromised server from reusing tokens to access other resources.

### 2.3 Credential Patterns

- Short-lived access tokens with refresh token rotation for public clients.
- Scope minimization: start with minimal scopes, use incremental elevation via
  `WWW-Authenticate` challenges.
- For stdio transports: retrieve credentials from environment variables, not OAuth.

**Sources:**
- [MCP Authorization Specification (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
- [MCP Spec Updates (Auth0)](https://auth0.com/blog/mcp-specs-update-all-about-auth/)
- [MCP, OAuth 2.1, PKCE (Aembit)](https://aembit.io/blog/mcp-oauth-2-1-pkce-and-the-future-of-ai-authorization/)

---

## 3. MCP Server Isolation and Sandboxing

### 3.1 Container Isolation

Running MCP servers in Docker containers is the primary recommended isolation pattern:

- Use minimal base images (e.g., `python:3.12-slim`)
- Create and run as non-root users
- Drop unnecessary Linux capabilities (`CAP_NET_ADMIN`, `CAP_SYS_ADMIN`)
- Apply seccomp profiles restricting allowed system calls
- Enforce AppArmor/SELinux mandatory access controls
- Set strict CPU/memory/I/O quotas per container
- Use read-only root filesystem with writable volumes only where necessary

### 3.2 Privilege Separation

- Each MCP server runs in its own container with access to only what it explicitly needs.
- Each server receives only the credentials it requires (no shared credential stores).
- Separate read and write scopes; never mix in a single token.
- Distinct MCP server instances for development, testing, and production.

### 3.3 Kubernetes Deployment

For production scale:
- NetworkPolicies to restrict inter-pod communication
- Service meshes (Istio) for mutual TLS and identity-based traffic control
- Pod security standards (restricted profile)
- Secrets management integration (Vault, cloud KMS)

**Sources:**
- [MCP Server Best Practices (Docker)](https://www.docker.com/blog/mcp-server-best-practices/)
- [How to Sandbox MCP Servers (MCP Manager)](https://mcpmanager.ai/blog/sandbox-mcp-servers/)

---

## 4. MCP Gateway and Proxy Patterns

An MCP Gateway sits between AI clients and MCP servers as a session-aware reverse proxy
and control plane, transforming point-to-point connections into a centralized
hub-and-spoke architecture.

### Core Security Functions

| Function | Details |
|----------|---------|
| Centralized Authentication | OAuth 2.0, OIDC, SAML; integrates with enterprise IdPs |
| Zero Trust Enforcement | Every request verified with device posture, location, behavioral analytics |
| RBAC / ABAC | Role-based and attribute-based access control at tool level |
| Content Filtering | PII detection, API key redaction, sensitive data masking in transit |
| Rate Limiting | Per-source, per-user, per-endpoint throttling |
| Request/Response Inspection | Deep packet inspection, protocol compliance, tool poisoning detection |
| Audit Logging | Complete trail of every API call |
| Service Discovery | Automatic server registration and capability broadcasting |

### Enterprise Deployment Patterns

1. **Dedicated Security Zone**: All MCP components in restricted network segments with
   separate IAM. Best for stringent compliance.
2. **API Gateway-Centric**: Leverage existing gateways (Kong, Envoy) for unified auth,
   rate limiting, WAF, and logging.
3. **Containerized Microservices**: Kubernetes with NetworkPolicies, service meshes,
   secrets management, and auto-scaling.

### Gateway Products

- Kong (native MCP gateway support)
- Envoy AI Gateway (announced MCP implementation)
- Lunar.dev MCPX (enterprise governance with tool-level RBAC)
- Docker MCP Toolkit (signed images, intelligent gateway, egress controls)

**Sources:**
- [What is an MCP Gateway? (Kong)](https://konghq.com/blog/learning-center/what-is-a-mcp-gateway)
- [MCP Gateway: Secure Enterprise AI (InfraCloud)](https://www.infracloud.io/blogs/mcp-gateway/)

---

## 5. Known Vulnerabilities and Attack Vectors

### 5.1 Critical Vulnerability Categories

**Prompt Injection (OWASP #1 LLM Risk):**
MCP amplifies prompt injection from text generation to automated action execution.
Indirect prompt injection through tool results is particularly dangerous.

**Tool Poisoning:**
Malicious instructions embedded in tool descriptions, parameter names, or metadata.
Rug-pull redefinitions: tool definitions silently altered post-approval.

**Confused Deputy Attacks:**
Exploits MCP proxy servers using static client IDs with third-party authorization servers.

**Session Hijacking:**
Injecting malicious payloads through shared session queues, or reusing guessed/stolen
session IDs.

**Server-Side Request Forgery (SSRF):**
During OAuth metadata discovery, malicious servers can direct clients to fetch internal
URLs (cloud metadata endpoints at 169.254.169.254).

### 5.2 Statistics

- 43% of tested MCP server implementations contained command injection flaws.
- 30% permitted unrestricted URL fetching.
- CVE-2025-6514: Command injection in mcp-remote.
- CVE in Anthropic's own PostgreSQL MCP server (SQL injection, now archived).

### 5.3 Multi-Server / Supply Chain Risks

- Tool name collision attacks trick models into selecting malicious tool versions.
- Cross-tool coordination allows poisoned descriptions to influence unrelated tools.
- Supply chain attacks on MCP server packages can compromise servers post-installation.

**Sources:**
- [MCP Security Best Practices (Official)](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices)
- [MCP Attack Vectors (Unit 42/Palo Alto)](https://unit42.paloaltonetworks.com/model-context-protocol-attack-vectors/)
- [MCP Security Vulnerabilities (Elastic Security Labs)](https://www.elastic.co/security-labs/mcp-tools-attack-defense-recommendations)
- [Prompt Injection Meets MCP (Snyk Labs)](https://labs.snyk.io/resources/prompt-injection-mcp/)

---

## 6. Government Compliance Frameworks

### 6.1 FedRAMP 20x

As of August 2025, FedRAMP launched a dedicated initiative to fast-track AI-based cloud
services for federal use. Requirements include:

- Enterprise-grade features: SSO, SCIM provisioning, RBAC, real-time analytics
- Data isolation: AI models trained on agency data must remain isolated
- Compliance-as-code: controls engineered into CI/CD pipelines with machine-readable
  evidence (NIST OSCAL or JSON)
- Some controls require minute-by-minute validation

### 6.2 FISMA / NIST SP 800-53 Rev. 5

Relevant control families for AI-database access:
- **AC (Access Control)**: Restricting database access to authorized AI processes
- **AU (Audit and Accountability)**: Tamper-proof audit records for all interactions
- **SC (System and Communications Protection)**: Encryption in transit
- **SI (System and Information Integrity)**: Input validation, output filtering
- **SA (System and Services Acquisition)**: Supply chain controls for AI model provenance

### 6.3 NIST AI Risk Management Framework (AI RMF)

Four core functions: GOVERN, MAP, MEASURE, MANAGE.

NIST AI 600-1 (Generative AI Profile) addresses 12 risks unique to generative AI:
- Data Privacy, Information Security, Confabulation
- Value Chain/Component Integration, Human-AI Configuration

### 6.4 OMB M-24-10

Mandatory AI governance for federal agencies:
- Enterprise AI strategy addressing responsible use
- Annual AI use case inventory (publicly posted)
- Minimum risk management practices for AI impacting rights

**Sources:**
- [FedRAMP AI](https://www.fedramp.gov/ai/)
- [NIST SP 800-53 Rev. 5](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final)
- [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)
- [NIST AI 600-1 (GenAI Profile)](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)

---

## 7. Zero Trust Architecture for AI Agents

### NIST SP 800-207 Core Components

- **Policy Engine (PE)**: Makes access decisions using policy, risk scores, identity, telemetry
- **Policy Administrator (PA)**: Translates PE decisions into action (configure/tear down channels)
- **Policy Enforcement Point (PEP)**: Gateway between agent and database; every query passes through

### Application to AI Agents

1. **Per-query authentication and authorization**: No persistent database sessions
2. **Least-privilege scoping**: Access only to specific tables/columns needed for current task
3. **Behavioral baselining**: Anomalous query patterns trigger real-time policy re-evaluation
4. **Micro-segmentation**: AI inference, database, and response generation in separate network segments

### CISA Zero Trust Maturity Model (v2.0)

The Data Pillar specifically calls out the risk of sensitive data leaking through AI
tools. At the Advanced maturity level: automated data tagging, real-time DLP, and
granular access controls considering requester identity, device posture, and behavioral
context.

**Sources:**
- [NIST SP 800-207](https://csrc.nist.gov/pubs/sp/800/207/final)
- [CISA Zero Trust Maturity Model](https://www.cisa.gov/zero-trust-maturity-model)
- [NSA Data Pillar Zero Trust Guidance (April 2024)](https://media.defense.gov/2024/Apr/09/2003434442/-1/-1/0/CSI_DATA_PILLAR_ZT.PDF)

---

## 8. Confidential Computing for AI Workloads

Hardware-based Trusted Execution Environments (TEEs) protect data-in-use.

| Technology | Scope | GPU Support | Best For |
|------------|-------|-------------|----------|
| Intel SGX | Process-level enclave | No (CPU only) | Small workloads, PII filtering |
| Intel TDX | VM-level isolation | Via passthrough | Medium AI inference |
| AMD SEV-SNP | VM-level encryption | Via passthrough | Large VM-based inference |
| NVIDIA H100 TEE | GPU-level enclave | Native | Full LLM inference at scale |
| AWS Nitro Enclaves | Instance-level isolation | No | Serverless-style inference |

NVIDIA H100 confidential computing adds **less than 5% overhead** for typical LLM
inference. Azure NCCads_H100_v5 VMs provide confidential GPUs.

For classified networks: Google Distributed Cloud air-gapped appliance has DoD IL6 and
Top Secret authorization.

**Sources:**
- [AWS Nitro Enclaves for LLM Inference](https://aws.amazon.com/blogs/machine-learning/large-language-model-inference-over-confidential-data-using-aws-nitro-enclaves/)
- [NVIDIA Confidential Computing on H100](https://developer.nvidia.com/blog/confidential-computing-on-h100-gpus-for-secure-and-trustworthy-ai/)
- [Azure Confidential Computing](https://azure.microsoft.com/en-us/solutions/confidential-compute)

---

## 9. Data Loss Prevention for LLM Systems

### Input Guardrails (Pre-query)

- Prompt injection detection
- PII masking on input (NER or regex)
- Query scope validation against user authorization level

### Output Guardrails (Post-response)

- PII/PHI/PCI scanning of every LLM response before delivery
- Classification-aware filtering (match response data to user clearance)
- Contextual DLP tracking data flow through prompts, agents, and memory

### Detection Technologies

- AI-powered classifiers (95%+ accuracy vs 5-25% for legacy regex)
- Named Entity Recognition (NER)
- Semantic analysis (context-aware sensitivity detection)

### Tools

- Amazon Bedrock Guardrails, NVIDIA NeMo Guardrails, Meta Llama Guard
- Microsoft Presidio (open-source, 180+ entity types)
- Lakera Guard, LLM Guard, Nightfall AI

**Sources:**
- [Palo Alto Unit 42 - LLM Guardrails](https://unit42.paloaltonetworks.com/comparing-llm-guardrails-across-genai-platforms/)
- [Datadog - LLM Guardrails Best Practices](https://www.datadoghq.com/blog/llm-guardrails-best-practices/)

---

## 10. Secure Database Proxy and Access Broker Patterns

### Proxy Comparison

| Proxy | Multiplexing | Credential Rotation | Query Firewall | Cloud Lock-in |
|-------|-------------|--------------------:|----------------|---------------|
| PgBouncer | No | Manual | No | None |
| ProxySQL | Yes | Manual | Yes (regex rules) | None |
| AWS RDS Proxy | Yes | Native (Secrets Manager + IAM) | No | AWS |
| Azure SQL Gateway | N/A | Native (Key Vault + AAD) | Built-in ACL | Azure |

### Security Gateway Functions

- **Query allowlisting/denylisting** (AcraCensor: AST-based SQL firewall)
- **Row-level security / column-level masking**
- **Read-only enforcement** at proxy and database levels
- **Query complexity limits** (EXPLAIN-before-execute, cost threshold rejection)
- **Result set size limits** (enforced LIMIT clauses)

**Sources:**
- [AcraCensor SQL Firewall (Cossack Labs)](https://www.cossacklabs.com/blog/how-to-build-sql-firewall-acracensor/)
- [Control Runaway Postgres Queries (Crunchy Data)](https://www.crunchydata.com/blog/control-runaway-postgres-queries-with-statement-timeout)

---

## 11. Dynamic Credential Management

### HashiCorp Vault Database Secrets Engine

- Creates unique username/password pairs on demand with configurable TTL
- Dynamic secrets do not exist until read
- Automatic revocation after TTL expiry
- Published validated pattern for AI agent identity

### Comparison

| Feature | Vault | AWS Secrets Manager | Azure Key Vault |
|---------|-------|--------------------:|-----------------|
| Dynamic DB credentials | Native, on-demand | Via Lambda rotation | Via Event Grid + Functions |
| TTL-based expiry | Seconds to hours | Days (configurable) | Event-driven |
| Multi-cloud | Yes | AWS only | Azure only |
| AI agent pattern | Validated | Via RDS Proxy | Via managed identity |

**Sources:**
- [Vault Dynamic Secrets Tutorial](https://developer.hashicorp.com/vault/tutorials/db-credentials/database-secrets)
- [Secure AI Agent Auth with Vault](https://developer.hashicorp.com/validated-patterns/vault/ai-agent-identity-with-hashicorp-vault)

---

## 12. SQL Injection Prevention in AI-Generated Queries

### The Threat

- **ToxicSQL (SIGMOD 2025)**: 0.44% poisoned training data achieves 79.41% attack success rate
- **P2SQL (ICSE 2025)**: Prompt-to-SQL injection is a formal attack category
- **CVE in Anthropic's own PostgreSQL MCP server** (now archived)
- Traditional WAFs do NOT catch AI-generated SQL payloads

### Defense Layers

1. **Semantic Layer**: LLM generates Semantic SQL; compiler translates deterministically
2. **Stored procedures / parameterized templates**: LLM fills parameters, never crafts raw SQL
3. **SQL AST validation**: Parse into AST, validate against allowlist of operations
4. **Read-only database roles**: SELECT-only permissions
5. **Row-Level Security**: Database enforces tenant isolation regardless of query
6. **Runtime monitoring**: Query firewall (AcraCensor), EXPLAIN-before-execute

**Sources:**
- [ToxicSQL (arXiv:2503.05445)](https://arxiv.org/abs/2503.05445)
- [P2SQL Injections (ICSE 2025)](https://dl.acm.org/doi/10.1109/ICSE55347.2025.00007)
- [MCP PostgreSQL SQL Injection (Datadog Security Labs)](https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/)

---

## 13. Multi-Tenant Database Isolation Patterns

### Pattern Comparison

| Pattern | Isolation | Cost | AI Agent Fit |
|---------|-----------|------|--------------|
| Shared DB + RLS | Row-level (weakest) | Lowest | Best starting point; DB enforces isolation regardless of LLM query |
| Separate schemas | Schema-level | Moderate | Proxy must manage `search_path` per request |
| Separate databases | Full (strongest) | Highest | Requires dynamic connection routing; best for stringent compliance |

### Tenant ID Propagation

Regardless of pattern, the tenant ID must flow from user request through the agent to
the database layer:

```sql
-- Set per-request in the connection proxy
SET app.current_tenant = 'tenant-uuid';

-- RLS policy enforces isolation
CREATE POLICY tenant_isolation ON orders
  USING (tenant_id = current_setting('app.current_tenant')::uuid);
```

**Sources:**
- [Multi-Tenant Data Isolation with PostgreSQL RLS (AWS)](https://aws.amazon.com/blogs/database/multi-tenant-data-isolation-with-postgresql-row-level-security/)
- [RLS for Tenants in Postgres (Crunchy Data)](https://www.crunchydata.com/blog/row-level-security-for-tenants-in-postgres)

---

## 14. Data Masking and Tokenization

### PII Masking Before the AI Sees Data

**Microsoft Presidio** (open-source):
- 180+ entity types via NER, regex, rule-based logic, contextual analysis
- Supports redaction, hashing, masking, encryption, and synthetic replacement
- Reversible anonymization (tokenization) for authorized de-tokenization

**Database-Level Dynamic Masking:**
- PostgreSQL Anonymizer extension: dynamic masking, static masking, anonymous dumps
- Amazon Aurora pg_columnmask: column-level policies complementing RLS
- View-based masking: `CASE WHEN current_user = 'admin' THEN email ELSE '***' END`

### LLM-Specific Masking Pattern

1. Identify sensitive values in query results using NER
2. Replace with placeholder tokens (`[PERSON_1]`, `[SSN_REDACTED]`)
3. Send masked text to LLM for processing
4. Reintroduce original data only for authorized users (de-tokenization)

**Sources:**
- [Microsoft Presidio (GitHub)](https://github.com/microsoft/presidio)
- [PostgreSQL Anonymizer](https://postgresql-anonymizer.readthedocs.io/)

---

## 15. Semantic Layers and Data Virtualization

### Why Semantic Layers Are Essential

Gartner 2025 identified semantic technology as non-negotiable for AI success.
The fundamental security advantage: the LLM never generates raw SQL against production
schemas. Instead, it generates requests in business-level terms, which the semantic
layer compiler deterministically translates to valid, optimized, access-controlled SQL.

### Key Tools

- **Cube (formerly Cube.js)**: AI agents query via "Semantic SQL"; runtime validates
  every request; compiler generates optimized SQL
- **dbt Semantic Layer (MetricFlow)**: Open-source (Apache 2.0); single source of truth
  for metric definitions

### Architectural Philosophies

- **Warehouse-native** (Snowflake, Databricks): Semantic layer inside the data warehouse
- **Platform-agnostic / Headless** (Cube, dbt MetricFlow): Decoupled metric definitions
  independent of any specific database or dashboard

**Sources:**
- [Semantic Layer and AI (Cube Blog)](https://cube.dev/blog/semantic-layer-and-ai-the-future-of-data-querying-with-natural-language)
- [Headless vs Native Semantic Layer (VentureBeat)](https://venturebeat.com/ai/headless-vs-native-semantic-layer-the-architectural-key-to-unlocking-90-text)

---

## 16. Human-in-the-Loop Patterns

### LangGraph interrupt()

LangGraph natively supports pausing agent execution for human approval:
- Pauses graph execution mid-flow, waits for human input, resumes cleanly
- State saved via persistence layer (AsyncPostgresSaver)
- Three decisions: approve, edit (modify before running), reject (with feedback)

### Risk-Based Routing

| Risk Level | Action | Example |
|------------|--------|---------|
| Low | Auto-execute | Analytics dashboards, simple counts |
| Medium | Notify | Cross-table JOINs, data exports |
| High | Require approval | Queries touching PII, classified columns |
| Critical | Recommendation mode | Agent suggests SQL; DBA must execute |

**Sources:**
- [Human-in-the-Loop (LangChain Docs)](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)
- [HITL AI Agents with LangGraph (Elastic)](https://www.elastic.co/search-labs/blog/human-in-the-loop-hitllanggraph-elasticsearch)

---

## 17. Differential Privacy for Query Results

Differential privacy adds structured random noise to query results, making it
statistically unlikely to trace outputs back to specific individuals.

- **Epsilon** controls the privacy-utility tradeoff (smaller = more privacy = more noise)
- Privacy budget is consumed per query; when exhausted, no further queries permitted
- Typical range: epsilon 0.1-10 depending on data sensitivity

### Production Implementations

- Google BigQuery: Native DP aggregate functions (`ANON_COUNT`, `ANON_SUM`, `ANON_AVG`)
- AWS Clean Rooms: DP policies with budget tracking
- Snowflake Data Clean Rooms: DP for multi-party collaboration

The U.S. Census Bureau uses differential privacy at scale for census data.

**Sources:**
- [Differential Privacy and AI (Springer)](https://link.springer.com/article/10.1186/s13635-025-00203-9)
- [Google BigQuery Differential Privacy](https://cloud.google.com/bigquery/docs/differential-privacy)

---

## 18. Audit Logging and Compliance

### What to Log

| Category | Data Points |
|----------|-------------|
| Agent Actions | Request triggers, tool selection, agent ID, user context, timestamps |
| Tool Invocations | Tool name, operation type, parameters (sanitized), outcome, row count |
| Data Access | Tables/columns accessed, query predicates, access type, data classification |
| Authorization | Auth attempts, permission checks, allow/deny decisions, policies applied |
| Correlation | Request ID, session ID, trace ID (W3C Trace Context) |

### Retention Requirements

| Framework | Retention |
|-----------|-----------|
| HIPAA | Minimum 6 years |
| SOX | 7+ years |
| PCI-DSS | 1 year (3 months immediately available) |
| EU AI Act | Minimum 6 months |

### Implementation

- **pgAudit**: Detailed session/object audit logging for PostgreSQL
- **Distributed tracing**: OpenTelemetry with W3C Trace Context
- **WORM storage**: Write Once, Read Many for immutability
- **SIEM integration**: Centralized logs with anomaly detection

**Sources:**
- [MCP Audit Logging (Tetrate)](https://tetrate.io/learn/ai/mcp/mcp-audit-logging)
- [pgAudit](https://www.pgaudit.org/)

---

## 19. Tool Use Sandboxing Patterns

### Framework Comparison

| Framework | Built-in Sandboxing | Notes |
|-----------|-------------------|-------|
| AutoGen | Yes | Azure AD integration, sandboxed execution |
| Google ADK | Yes | Multi-layered: in-tool guardrails, Gemini-as-a-Judge, hermetic environments |
| LangChain/LangGraph | No | Developer responsibility; relies on LangSmith for tracing |
| CrewAI | Partial | RBAC, encryption; code sandboxing is manual |

### Docker-Based Isolation Tiers

1. **MicroVMs** (Firecracker, Kata): Strongest; dedicated kernels per workload
2. **gVisor**: User-space kernel; syscall interception without full VMs
3. **Hardened containers**: Suitable only for trusted code; shared host kernel

Execution sandboxing alone is insufficient. A complete solution requires
**execution isolation + authorization controls + output validation**.

**Sources:**
- [Docker Sandboxes](https://docs.docker.com/ai/sandboxes)
- [Google ADK Safety and Security](https://google.github.io/adk-docs/safety/)
- [Docker Sandboxes Alone Aren't Enough (Arcade.dev)](https://blog.arcade.dev/docker-sandboxes-arent-enough-for-agent-safety)

---

## 20. Proposed Reference Architecture

### 20.1 High-Level Summary

```
User --> [ZTA Policy Engine (NIST 800-207)]
           |
           v
         [MCP Gateway (Kong/Envoy)]
           | OAuth 2.1 + RBAC
           v
         [Input Guardrails + Prompt Injection Detection]
           |
           v
         [Semantic Layer (Cube.js)]  <-- Agent generates Semantic SQL
           | deterministic SQL compilation
           v
         [SQL AST Firewall (AcraCensor)]  <-- allowlist validation (1st pass)
           |
           v
         [HITL Gate]  <-- risk-based: auto / notify / approve
           |
           v
         [MCP Gateway]  --> Streamable HTTP + mTLS (port 443)
           |
     ======|====== NETWORK BOUNDARY (no DB protocol crosses) ======
           |
           v
   CLIENT NETWORK PERIMETER:
         [Client MCP Server (postgres-mcp)]  <-- hardened OCI container
           |
           v
         [SQL AST Firewall (2nd pass)]  <-- client-side validation
           |
           v
         [Vault / Secrets Manager] --> JIT credentials (5min TTL)
           |
           v
         [PostgreSQL Read Replica]
           |-- RLS (tenant isolation)
           |-- Column masking (PII redaction)
           |-- statement_timeout = 30s
           |-- pgAudit (full query logging)
           |
           v
         [Client-side DLP / Result Filter]
           |
     ======|====== NETWORK BOUNDARY (filtered result returns) ======
           |
           v
         [Output DLP (Presidio)]  <-- agent-side PII scan (2nd pass)
           |
           v
         [Differential Privacy]  <-- noise on aggregates (optional)
           |
           v
         [Audit Log (WORM)]  <-- full trace, 7-year retention
           |
           v
         User receives sanitized response
```

### 20.2 Detailed End-to-End Workflow Diagram

The diagram below traces a complete request lifecycle from user input through the
LangGraph agent loop, MCP tool dispatch over the network to the client's MCP server,
database interaction inside the client's perimeter, and back to the user's screen.
Each numbered step (S1-S24) is a distinct processing stage.

**Key architectural decision:** The MCP server runs **inside the client's network
perimeter**, not on our platform. This ensures:
- No database protocol (port 5432) ever crosses the public internet.
- The client controls all database access, credential provisioning, and data filtering
  at the source.
- Different government agencies can deploy customized MCP servers with their own
  security policies, network structures, and access control logic.
- Our platform communicates with the client MCP server exclusively via
  **Streamable HTTP + mTLS** (port 443), carrying only MCP protocol messages.

Components are grouped into three zones:
- **AGENT PLATFORM (Our Side)**: Everything we build, deploy, and guarantee.
- **NETWORK BOUNDARY**: The trust boundary — only Streamable HTTP + mTLS crosses.
  No database protocol. No raw unfiltered data.
- **CLIENT INFRASTRUCTURE (Client Side)**: MCP server, database, credential store,
  and client-side security controls — all inside the client's network perimeter.

```
+==========================================================================+
|                                                                          |
|   AGENT PLATFORM (Our Side)                                              |
|                                                                          |
|   +---------------------------+                                          |
|   |       FRONTEND            |                                          |
|   |  +---------------------+  |                                          |
|   |  |  S1  User types     |  |                                          |
|   |  |  natural-language   |  |                                          |
|   |  |  query in chat UI   |  |                                          |
|   |  +---------------------+  |                                          |
|   |           |               |                                          |
|   |           | WebSocket / HTTP POST                                    |
|   |           | { messages, context: { thread_id, model_name,            |
|   |           |   user_id, database_id, thinking_enabled } }             |
|   |           v               |                                          |
|   |  +---------------------+  |                                          |
|   |  |  S2  ZTA Policy     |  |  NIST 800-207 Policy Decision Point      |
|   |  |  Engine evaluates:  |  |  - Verify user identity (OIDC/SAML)      |
|   |  |  identity, device,  |  |  - Check device posture                  |
|   |  |  context, risk      |  |  - Evaluate risk score                   |
|   |  +---------------------+  |  - Deny / Allow / Step-up MFA            |
|   |           |               |                                          |
|   +-----------|---------------+                                          |
|               | ALLOW (with scoped authorization token)                  |
|               v                                                          |
|   +-----------------------------------------------------------------------+
|   |       BACKEND  (LangGraph Server)                                     |
|   |                                                                       |
|   |   +-------------------------+                                         |
|   |   |  S3  Middleware Chain   |  Runs before agent loop starts          |
|   |   |  (before_agent hooks)   |                                         |
|   |   |                         |                                         |
|   |   |  ThreadDataMiddleware   |  Create thread workspace dirs           |
|   |   |  UploadsMiddleware      |  Inject uploaded files                  |
|   |   |  SandboxMiddleware      |  Acquire sandboxed environment          |
|   |   |  DanglingToolCallMW     |  Patch missing ToolMessages             |
|   |   |  UsageTrackingMW        |  Initialize token counters              |
|   |   |  SummarizationMW        |  Trim context if needed                 |
|   |   |  TitleMiddleware        |  Generate thread title                  |
|   |   |  MemoryMiddleware       |  Load conversation memory               |
|   |   +-------------------------+                                         |
|   |               |                                                       |
|   |               v                                                       |
|   |   +========================+                                          |
|   |   ||  S4  INPUT           ||                                          |
|   |   ||  GUARDRAILS          ||                                          |
|   |   ||                      ||  - Prompt injection detection            |
|   |   ||  Scan user message   ||  - Pattern matching (known attacks)      |
|   |   ||  for adversarial     ||  - Semantic analysis (intent vs content) |
|   |   ||  content             ||  - BLOCK if malicious, LOG + continue    |
|   |   +========================+    if clean                              |
|   |               |                                                       |
|   |               v                                                       |
|   |   +==========================================================+        |
|   |   ||                                                        ||        |
|   |   ||           LANGGRAPH AGENT LOOP                         ||        |
|   |   ||         (iterates until done)                          ||        |
|   |   ||                                                        ||        |
|   |   ||   +--------------------------------------------------+ ||        |
|   |   ||   |  S5  LLM Node (Claude claude-sonnet-4-6)         | ||        |
|   |   ||   |                                                  | ||        |
|   |   ||   |  Input:  system prompt + conversation history    | ||        |
|   |   ||   |          + available tools (MCP + builtins)      | ||        |
|   |   ||   |          + skills (sql-queries SKILL.md)         | ||        |
|   |   ||   |                                                  | ||        |
|   |   ||   |  Output: EITHER                                  | ||        |
|   |   ||   |    (a) tool_calls: [{name, args}, ...]  --+      | ||        |
|   |   ||   |    (b) final text response  -------------|--+    | ||        |
|   |   ||   +------------------------------------------|--|----+ ||        |
|   |   ||                                              |  |      ||        |
|   |   ||                          +-------------------+  |      ||        |
|   |   ||                          |  (if tool_calls)     |      ||        |
|   |   ||                          v                      |      ||        |
|   |   ||   +--------------------------------------------------+ ||        |
|   |   ||   |  S6  MCP GATEWAY (Tool Dispatch)                 | ||        |
|   |   ||   |                                                  | ||        |
|   |   ||   |  For each tool_call:                             | ||        |
|   |   ||   |   - Authenticate: validate OAuth 2.1 token       | ||        |
|   |   ||   |   - Authorize: RBAC check (user X can call       | ||        |
|   |   ||   |     tool Y with scope Z?)                        | ||        |
|   |   ||   |   - Rate limit: per-user, per-tool throttling    | ||        |
|   |   ||   |   - Route: dispatch to correct client MCP server | ||        |
|   |   ||   |                                                  | ||        |
|   |   ||   |  Tool call:   { name: "execute_sql",             | ||        |
|   |   ||   |                 args: { sql: "SELECT ..." } }    | ||        |
|   |   ||   +--------------------------------------------------+ ||        |
|   |   ||                          |                             ||        |
|   |   ||                          v                             ||        |
|   |   ||   +-------------------------------------------------+  ||        |
|   |   ||   |  S7  SEMANTIC LAYER (Cube.js / dbt MetricFlow)  |  ||        |
|   |   ||   |  [Only if agent generates semantic queries]     |  ||        |
|   |   ||   |                                                 |  ||        |
|   |   ||   |  Business query:                                |  ||        |
|   |   ||   |    "revenue by department, last 6 months"       |  ||        |
|   |   ||   |              |                                  |  ||        |
|   |   ||   |              v                                  |  ||        |
|   |   ||   |  Compiled SQL (deterministic, safe):            |  ||        |
|   |   ||   |    SELECT d.name, SUM(oi.quantity * oi.price)   |  ||        |
|   |   ||   |    FROM departments d JOIN ...                  |  ||        |
|   |   ||   |    WHERE o.order_date >= NOW() - INTERVAL '6m'  |  ||        |
|   |   ||   |    GROUP BY d.name ORDER BY 2 DESC              |  ||        |
|   |   ||   +-------------------------------------------------+  ||        |
|   |   ||                          |                             ||        |
|   |   ||                          v                             ||        |
|   |   ||   +=================================================+  ||        |
|   |   ||   ||  S8  SQL AST FIREWALL (1st pass, agent-side)  ||  ||        |
|   |   ||   ||                                               ||  ||        |
|   |   ||   ||  Parse SQL into Abstract Syntax Tree:         ||  ||        |
|   |   ||   ||   - REJECT: INSERT, UPDATE, DELETE, DROP,     ||  ||        |
|   |   ||   ||     ALTER, GRANT, TRUNCATE, COPY              ||  ||        |
|   |   ||   ||   - REJECT: pg_catalog, information_schema    ||  ||        |
|   |   ||   ||     access (unless allowlisted)               ||  ||        |
|   |   ||   ||   - REJECT: UNION-based injection patterns    ||  ||        |
|   |   ||   ||   - REJECT: queries without LIMIT clause      ||  ||        |
|   |   ||   ||   - REJECT: stacked queries (;)               ||  ||        |
|   |   ||   ||   - ALLOW:  SELECT on permitted tables only   ||  ||        |
|   |   ||   ||                                               ||  ||        |
|   |   ||   ||  If REJECT --> return error to LLM, re-loop   ||  ||        |
|   |   ||   +=================================================+  ||        |
|   |   ||                          |                             ||        |
|   |   ||                          | ALLOW                       ||        |
|   |   ||                          v                             ||        |
|   |   ||   +-------------------------------------------------+  ||        |
|   |   ||   |  S9  RISK CLASSIFIER                            |  ||        |
|   |   ||   |                                                 |  ||        |
|   |   ||   |  Evaluate query risk:                           |  ||        |
|   |   ||   |   LOW:  Simple counts, aggregates, lookups      |  ||        |
|   |   ||   |   MED:  Multi-table JOINs, exports              |  ||        |
|   |   ||   |   HIGH: PII columns, classified data            |  ||        |
|   |   ||   |   CRIT: Bulk extraction, cross-tenant queries   |  ||        |
|   |   ||   +-------------------------------------------------+  ||        |
|   |   ||                          |                             ||        |
|   |   ||                          v                             ||        |
|   |   ||   +-------------------------------------------------+  ||        |
|   |   ||   |  S10  HITL GATE (LangGraph interrupt())         |  ||        |
|   |   ||   |                                                 |  ||        |
|   |   ||   |  LOW  --> auto-execute (no pause)               |  ||        |
|   |   ||   |  MED  --> notify reviewer, continue             |  ||        |
|   |   ||   |  HIGH --> PAUSE execution, wait for approval    |  ||        |
|   |   ||   |           Reviewer sees: query, tables, risk    |  ||        |
|   |   ||   |           Actions: Approve / Edit / Reject      |  ||        |
|   |   ||   |  CRIT --> BLOCK, require DBA manual execution   |  ||        |
|   |   ||   +-------------------------------------------------+  ||        |
|   |   ||                          |                             ||        |
|   |   ||                          | APPROVED                    ||        |
|   |   ||                          v                             ||        |
|   |   ||   +-------------------------------------------------+  ||        |
|   |   ||   |  S11  DISPATCH TO REMOTE MCP SERVER             |  ||        |
|   |   ||   |                                                 |  ||        |
|   |   ||   |  MCP Gateway sends Streamable HTTP POST:        |  ||        |
|   |   ||   |                                                 |  ||        |
|   |   ||   |   POST https://mcp.client.gov/mcp               |  ||        |
|   |   ||   |   Authorization: Bearer <session-token>         |  ||        |
|   |   ||   |   Content-Type: application/json                |  ||        |
|   |   ||   |   X-Trace-ID: abc-123-def                       |  ||        |
|   |   ||   |                                                 |  ||        |
|   |   ||   |   { "jsonrpc": "2.0",                           |  ||        |
|   |   ||   |     "method": "tools/call",                     |  ||        |
|   |   ||   |     "params": {                                 |  ||        |
|   |   ||   |       "name": "execute_sql",                    |  ||        |
|   |   ||   |       "arguments": { "sql": "SELECT ..." }      |  ||        |
|   |   ||   |     } }                                         |  ||        |
|   |   ||   |                                                 |  ||        |
|   |   ||   |  Connection: mTLS (client cert + server cert)   |  ||        |
|   |   ||   |  Envelope encryption: AES-256-GCM payload       |  ||        |
|   |   ||   +-------------------------------------------------+  ||        |
|   |   ||                          |                             ||        |
|   |   ||                          | Streamable HTTP + mTLS      ||        |
|   |   ||                          | (port 443 only)             ||        |
|   |   ||                          |                             ||        |
|   |   +==========================================================+        |
|   |                               |                                       |
+---|-------------------------------|---------------------------------------+
    |                               |
====|===============================|===========================================
    |  NETWORK BOUNDARY             |   Only Streamable HTTP + mTLS crosses.
    |  (Public Internet / Dedicated |   No database protocol (5432).
    |   Link / VPN)                 |   No raw unfiltered data.
====|===============================|===========================================
    |                               |
+---|-------------------------------|---------------------------------------+
|   |                               |                                       |
|   |   CLIENT INFRASTRUCTURE       |                                       |
|   |   (Client's Network           v                                       |
|   |    Perimeter)                                                         |
|   |                                                                       |
|   |   +===================================================+               |
|   |   ||  S12  CLIENT EDGE / FIREWALL                    ||               |
|   |   ||                                                 ||               |
|   |   ||  Inbound rules:                                 ||               |
|   |   ||   - Allowlist: only agent platform IPs/certs    ||               |
|   |   ||   - Port: 443 (HTTPS only, NOT 5432)            ||               |
|   |   ||   - mTLS: verify agent platform client cert     ||               |
|   |   ||   - WAF: inspect MCP JSON-RPC payloads          ||               |
|   |   ||   - IDS/IPS: anomaly detection on request       ||               |
|   |   ||     patterns                                    ||               |
|   |   ||                                                 ||               |
|   |   ||  Outbound rules:                                ||               |
|   |   ||   - DENY ALL except response to authenticated   ||               |
|   |   ||     inbound connection                          ||               |
|   |   +===================================================+               |
|   |                               |                                       |
|   |                               v                                       |
|   |   +--------------------------------------------------+                |
|   |   |  S13  MCP SERVER (postgres-mcp)                  |                |
|   |   |  [Client-deployed, hardened OCI container]       |                |
|   |   |                                                  |                |
|   |   |  Shipped as: "Database Connector Kit"            |                |
|   |   |   - Signed OCI image from our curated catalog    |                |
|   |   |   - Client pulls and deploys inside their VPC    |                |
|   |   |   - Runs as non-root, read-only rootfs           |                |
|   |   |   - Dropped capabilities, seccomp profile        |                |
|   |   |   - CPU/memory limits set by client              |                |
|   |   |                                                  |                |
|   |   |  Inbound: Streamable HTTP (from agent platform)  |                |
|   |   |   - Validates OAuth 2.1 token (audience-bound)   |                |
|   |   |   - Validates X-Trace-ID for correlation         |                |
|   |   |   - Decrypts envelope payload (AES-256-GCM)      |                |
|   |   |                                                  |                |
|   |   |  Outbound: PostgreSQL wire protocol (localhost   |                |
|   |   |   or private subnet only — NEVER internet)       |                |
|   |   +--------------------------------------------------+                |
|   |                               |                                       |
|   |                               v                                       |
|   |   +==================================================+                |
|   |   ||  S14  SQL AST FIREWALL (2nd pass, client-side) ||                |
|   |   ||                                                ||                |
|   |   ||  Client's own validation rules:                ||                |
|   |   ||   - Re-validate SQL AST (defense-in-depth)     ||                |
|   |   ||   - Enforce client-specific table allowlists   ||                |
|   |   ||   - Apply agency-specific query policies       ||                |
|   |   ||   - Check against client's data classification ||                |
|   |   ||                                                ||                |
|   |   ||  If REJECT --> return error via MCP response   ||                |
|   |   +==================================================+                |
|   |                               |                                       |
|   |                               | ALLOW                                 |
|   |                               v                                       |
|   |   +--------------------------------------------------+                |
|   |   |  S15  CREDENTIAL ACQUISITION (Client Vault)      |                |
|   |   |                                                  |                |
|   |   |  MCP server requests JIT credentials from        |                |
|   |   |  client's credential store (co-located in VPC):  |                |
|   |   |                                                  |                |
|   |   |  HashiCorp Vault / AWS Secrets Manager /         |                |
|   |   |  Azure Key Vault / agency-specific store         |                |
|   |   |                                                  |                |
|   |   |   POST /v1/database/creds/agent-readonly-role    |                |
|   |   |                                                  |                |
|   |   |   Response:                                      |                |
|   |   |    { username: "v-agent-readonly-abc123",        |                |
|   |   |      password: "s.Kj8x...",                      |                |
|   |   |      ttl: "300s" }                               |                |
|   |   |                                                  |                |
|   |   |  Credentials stay inside client network.         |                |
|   |   |  NEVER transmitted to agent platform.            |                |
|   |   +--------------------------------------------------+                |
|   |                               |                                       |
|   |                               v                                       |
|   |   +===================================================+               |
|   |   ||  S16  DATABASE QUERY EXECUTION                  ||               |
|   |   ||                                                 ||               |
|   |   ||  MCP server connects to PostgreSQL using        ||               |
|   |   ||  JIT credentials over private network:          ||               |
|   |   ||                                                 ||               |
|   |   ||   postgresql://v-agent-abc123:***@              ||               |
|   |   ||     db-replica.internal:5432/erp_production     ||               |
|   |   ||                                                 ||               |
|   |   ||  EXPLAIN-before-execute:                        ||               |
|   |   ||   - Run EXPLAIN first, check cost estimate      ||               |
|   |   ||   - REJECT if cost > threshold                  ||               |
|   |   ||   - Execute only if cost is acceptable          ||               |
|   |   +===================================================+               |
|   |                               |                                       |
|   |                               v                                       |
|   |   +===================================================+               |
|   |   ||  S17  PostgreSQL READ REPLICA                   ||               |
|   |   ||                                                 ||               |
|   |   ||  Connection properties:                         ||               |
|   |   ||   - default_transaction_read_only = on          ||               |
|   |   ||   - statement_timeout = 30000 (30s)             ||               |
|   |   ||   - work_mem = 64MB (prevent runaway sorts)     ||               |
|   |   ||   - ssl = on, sslmode = verify-full             ||               |
|   |   ||                                                 ||               |
|   |   ||  Row-Level Security (RLS):                      ||               |
|   |   ||   CREATE POLICY tenant_isolation ON orders      ||               |
|   |   ||     USING (tenant_id = current_setting(         ||               |
|   |   ||       'app.current_tenant')::uuid);             ||               |
|   |   ||                                                 ||               |
|   |   ||  Column-Level Masking:                          ||               |
|   |   ||   - SSN: '***-**-' || RIGHT(ssn, 4)             ||               |
|   |   ||   - Email: LEFT(email,2) || '***@***'           ||               |
|   |   ||   - Phone: '(***) ***-' || RIGHT(phone, 4)      ||               |
|   |   ||                                                 ||               |
|   |   ||  pgAudit logging:                               ||               |
|   |   ||   pgaudit.log = 'read'                          ||               |
|   |   ||   pgaudit.log_parameter = on                    ||               |
|   |   ||   pgaudit.log_relation = on                     ||               |
|   |   ||                                                 ||               |
|   |   ||  Query execution:                               ||               |
|   |   ||   SQL --> RLS filter --> column mask -->        ||               |
|   |   ||   result set (with statement_timeout)           ||               |
|   |   +===================================================+               |
|   |                               |                                       |
|   |                               | Result set (filtered by RLS + masks)  |
|   |                               v                                       |
|   |   +==================================================+                |
|   |   ||  S18  CLIENT-SIDE DLP / RESULT FILTER           ||               |
|   |   ||                                                 ||               |
|   |   ||  Client's own output scanning (1st pass):       ||               |
|   |   ||   - Agency-specific PII rules                   ||               |
|   |   ||   - Classification-aware filtering              ||               |
|   |   ||   - Result set size limits                      ||               |
|   |   ||   - Domain-specific entity redaction            ||               |
|   |   ||                                                 ||               |
|   |   ||  Actions: REDACT / TRUNCATE / PASS              ||               |
|   |   +==================================================+                |
|   |                               |                                       |
|   |                               v                                       |
|   |   +--------------------------------------------------+                |
|   |   |  S19  CLIENT-SIDE AUDIT LOG                      |                |
|   |   |                                                  |                |
|   |   |  Record in client's SIEM / audit system:         |                |
|   |   |   - Trace ID (from X-Trace-ID header)            |                |
|   |   |   - SQL executed, tables accessed                |                |
|   |   |   - Row count returned, columns accessed         |                |
|   |   |   - Credential used, TTL remaining               |                |
|   |   |   - Firewall decision (ALLOW/REJECT)             |                |
|   |   |   - DLP actions taken (REDACT/PASS)              |                |
|   |   |   - Timestamp, source IP                         |                |
|   |   |                                                  |                |
|   |   |  Client owns retention policy per their          |                |
|   |   |  compliance framework (FedRAMP, HIPAA, etc.)     |                |
|   |   +--------------------------------------------------+                |
|   |                               |                                       |
|   |                               | Filtered CallToolResult               |
|   |                               | (MCP JSON-RPC response)               |
|   |                               |                                       |
+---|-------------------------------|---------------------------------------+
    |                               |
====|===============================|===========================================
    |  NETWORK BOUNDARY             |   Filtered result returns over mTLS.
    |  (same channel as request)    |   Already scanned by client-side DLP.
====|===============================|===========================================
    |                               |
+---|-------------------------------|---------------------------------------+
|   |                               |                                       |
|   |   AGENT PLATFORM (Our Side)   |  RESPONSE PATH                        |
|   |           |                   v                                       |
|   |           |   +--------------------------------------------------+    |
|   |           |   |  S20  MCP GATEWAY receives CallToolResult        |    |
|   |           |   |                                                  |    |
|   |           |   |  Decrypt envelope (AES-256-GCM)                  |    |
|   |           |   |  Validate trace ID correlation                   |    |
|   |           |   |  Log received result with latency metrics        |    |
|   |           |   |                                                  |    |
|   |           |   |  CallToolResult:                                 |    |
|   |           |   |   { rows: [...], row_count: 25, columns: [...] } |    |
|   |           |   +--------------------------------------------------+    |
|   |           |                   |                                       |
|   |           |                   v                                       |
|   |           |   +==================================================+    |
|   |           |   ||  S21  OUTPUT DLP (Presidio / NER, 2nd pass)    ||    |
|   |           |   ||                                                ||    |
|   |           |   ||  Agent-side PII scan (defense-in-depth):       ||    |
|   |           |   ||   - SSN patterns (XXX-XX-XXXX)                 ||    |
|   |           |   ||   - Email addresses                            ||    |
|   |           |   ||   - Phone numbers                              ||    |
|   |           |   ||   - Credit card numbers                        ||    |
|   |           |   ||   - Names in sensitive context                 ||    |
|   |           |   ||   - Domain-specific entities (client rules)    ||    |
|   |           |   ||                                                ||    |
|   |           |   ||  Catches anything client-side DLP missed.      ||    |
|   |           |   ||  Actions: REDACT / FLAG / PASS                 ||    |
|   |           |   +==================================================+    |
|   |           |                   |                                       |
|   |           |                   v                                       |
|   |           |   +--------------------------------------------------+    |
|   |           |   |  S22  CLASSIFICATION FILTER +                    |    |
|   |           |   |       DIFFERENTIAL PRIVACY                       |    |
|   |           |   |                                                  |    |
|   |           |   |  Classification check:                           |    |
|   |           |   |   UNCLASSIFIED --> pass                          |    |
|   |           |   |   CUI          --> pass if user has CUI access   |    |
|   |           |   |   SECRET       --> BLOCK, log violation          |    |
|   |           |   |                                                  |    |
|   |           |   |  Differential privacy (optional):                |    |
|   |           |   |   - Add calibrated Laplace/Gaussian noise        |    |
|   |           |   |     to aggregate results on sensitive data       |    |
|   |           |   |   - Track epsilon budget per user/session        |    |
|   |           |   |   - Reject query if budget exhausted             |    |
|   |           |   +--------------------------------------------------+    |
|   |           |                   |                                       |
|   |           |                   |  Tool result (double-sanitized)       |
|   |           |                   |  returned to LangGraph as ToolMessage |
|   |           |                   v                                       |
|   |   +==========================================================+        |
|   |   ||           LANGGRAPH AGENT LOOP (continued)              ||       |
|   |   ||                                                         ||       |
|   |   ||   +---------------------------------------------------+ ||       |
|   |   ||   |  S23  LLM Node receives ToolMessage(s)            | ||       |
|   |   ||   |                                                   | ||       |
|   |   ||   |  LLM synthesizes tool results into natural-       | ||       |
|   |   ||   |  language response for the user.                  | ||       |
|   |   ||   |                                                   | ||       |
|   |   ||   |  Output: AIMessage (final text response)          | ||       |
|   |   ||   |                                                   | ||       |
|   |   ||   |  If LLM needs more data --> emit new tool_calls   | ||       |
|   |   ||   |  and LOOP BACK to S6 (MCP Gateway)                | ||       |
|   |   ||   +---------------------------------------------------+ ||       |
|   |   ||                                                         ||       |
|   |   +==========================================================+        |
|   |                               |                                       |
|   |                               | Final AIMessage (no tool_calls)       |
|   |                               v                                       |
|   |   +---------------------------------------------------+               |
|   |   |  S24a  MIDDLEWARE CHAIN (after_agent hooks)       |               |
|   |   |                                                   |               |
|   |   |  UsageTrackingMW    --> Record token consumption  |               |
|   |   |  MemoryMiddleware   --> Queue memory update       |               |
|   |   |  TitleMiddleware    --> Generate thread title     |               |
|   |   |  TimelineLoggingMW  --> Snapshot message timeline |               |
|   |   |  ClarificationMW   --> Check if clarification     |               |
|   |   |                        needed                     |               |
|   |   +--------------------------------------------------—+               |
|   |                               |                                       |
|   |                               v                                       |
|   |   +===================================================+               |
|   |   ||  S24b  AGENT-SIDE AUDIT LOG (WORM Storage)      ||               |
|   |   ||                                                 ||               |
|   |   ||  Record written for EVERY interaction:          ||               |
|   |   ||                                                 ||               |
|   |   ||  { trace_id:       "abc-123-def",               ||               |
|   |   ||    thread_id:      "thread-789",                ||               |
|   |   ||    user_id:        "user-456",                  ||               |
|   |   ||    timestamp:      "2026-02-26T15:24:18Z",      ||               |
|   |   ||    user_query:     "What are top categories?",  ||               |
|   |   ||    model:          "claude-sonnet-4-6",         ||               |
|   |   ||    thinking_tokens: 1024,                       ||               |
|   |   ||    tool_calls: [                                ||               |
|   |   ||      { tool: "list_schemas", latency_ms: 120,   ||               |
|   |   ||        params: {}, row_count: 3 },              ||               |
|   |   ||      { tool: "execute_sql", latency_ms: 285,    ||               |
|   |   ||        params: { sql: "SELECT ..." },           ||               |
|   |   ||        row_count: 25,                           ||               |
|   |   ||        remote_mcp: "mcp.client.gov",            ||               |
|   |   ||        client_trace_ack: true }                 ||               |
|   |   ||    ],                                           ||               |
|   |   ||    guardrail_actions: [                         ||               |
|   |   ||      { type: "sql_firewall_agent", result: "ALLOW" },  ||        |
|   |   ||      { type: "sql_firewall_client", result: "ALLOW" }, ||        |
|   |   ||      { type: "pii_scan_client", result: "PASS" },      ||        |
|   |   ||      { type: "pii_scan_agent", result: "PASS" }        ||        |
|   |   ||    ],                                           ||               |
|   |   ||    hitl_decision:  "auto-approved",             ||               |
|   |   ||    response_length: 342 }                       ||               |
|   |   ||                                                 ||               |
|   |   ||  Retention: 7 years (SOX) / 6 years (HIPAA)     ||               |
|   |   ||  Storage:   Append-only, cryptographically      ||               |
|   |   ||             hashed chain, SIEM export           ||               |
|   |   +===================================================+               |
|   |                               |                                       |
|   |                               v                                       |
|   |   +--------------------------------------------------+                |
|   |   |         FRONTEND                                 |                |
|   |   |  +---------------------------------------------+ |                |
|   |   |  |  Sanitized response streamed to user via    | |                |
|   |   |  |  WebSocket. User sees natural-language      | |                |
|   |   |  |  answer with tables, charts, analysis.      | |                |
|   |   |  |                                             | |                |
|   |   |  |  No raw SQL, no raw row data, no PII        | |                |
|   |   |  |  in the final response.                     | |                |
|   |   |  +---------------------------------------------+ |                |
|   |   +--------------------------------------------------+                |
|   |                                                                       |
+---------------------------------------------------------------------------+
```

### 20.3 Step Reference

| Step | Component | Zone | Purpose |
|------|-----------|------|---------|
| S1   | Chat UI | Agent (Frontend) | User submits natural-language query |
| S2   | ZTA Policy Engine | Agent (Frontend) | Identity verification, device posture, risk scoring |
| S3   | Middleware Chain (before) | Agent (Backend) | Thread setup, sandbox acquisition, context loading |
| S4   | Input Guardrails | Agent (Backend) | Prompt injection detection and blocking |
| S5   | LLM Node | Agent (Backend) | Claude processes query, decides tool calls or final response |
| S6   | MCP Gateway | Agent (Backend) | OAuth validation, RBAC, rate limiting, routing to client MCP |
| S7   | Semantic Layer | Agent (Backend) | Business query to deterministic SQL compilation |
| S8   | SQL AST Firewall (1st pass) | Agent (Backend) | Parse and validate SQL; reject DML/DDL/injection |
| S9   | Risk Classifier | Agent (Backend) | Classify query risk level (LOW/MED/HIGH/CRIT) |
| S10  | HITL Gate | Agent (Backend) | Pause for human approval if risk exceeds threshold |
| S11  | Dispatch to Remote MCP | Agent (Backend) | Send Streamable HTTP + mTLS request to client MCP server |
| S12  | Client Edge / Firewall | **Client** | mTLS verification, WAF inspection, port 443 only |
| S13  | MCP Server (postgres-mcp) | **Client** | Hardened OCI container deployed inside client VPC |
| S14  | SQL AST Firewall (2nd pass) | **Client** | Client-specific validation, table allowlists, policies |
| S15  | Credential Acquisition | **Client** | JIT credentials from client's Vault (stays in network) |
| S16  | Database Query Execution | **Client** | EXPLAIN-before-execute, cost validation, query run |
| S17  | PostgreSQL Read Replica | **Client** | RLS, column masking, pgAudit, statement timeout |
| S18  | Client-side DLP | **Client** | Agency-specific PII rules, result filtering |
| S19  | Client-side Audit Log | **Client** | Client's SIEM, trace ID correlation, retention |
| S20  | MCP Gateway (response) | Agent (Backend) | Receive + decrypt filtered result from client |
| S21  | Output DLP (2nd pass) | Agent (Backend) | Agent-side PII scan (catches what client missed) |
| S22  | Classification + Differential Privacy | Agent (Backend) | Clearance check, optional noise on aggregates |
| S23  | LLM Node (continued) | Agent (Backend) | Synthesize tool results into natural-language response |
| S24a | Middleware Chain (after) | Agent (Backend) | Usage tracking, memory update, title generation |
| S24b | Audit Log | Agent (Backend) | WORM storage, full trace (agent + client actions), 7yr retention |

### 20.4 What Crosses the Network Boundary

| Direction | Content | Format | Encryption |
|-----------|---------|--------|------------|
| Agent → Client | MCP tool call (e.g., `execute_sql` with SQL string) | JSON-RPC 2.0 over Streamable HTTP | mTLS + AES-256-GCM envelope |
| Client → Agent | MCP tool result (filtered rows, metadata) | JSON-RPC 2.0 over Streamable HTTP | mTLS + AES-256-GCM envelope |
| **Never crosses** | Database credentials | — | Stays inside client network |
| **Never crosses** | PostgreSQL wire protocol | — | Localhost/private subnet only |
| **Never crosses** | Raw unfiltered query results | — | Client DLP filters before return |

### 20.5 Dual-Side Security Enforcement

Critical security controls run on **both** sides for defense-in-depth:

| Control | Agent-Side (S8) | Client-Side (S14) | Why Both? |
|---------|----------------|-------------------|-----------|
| SQL AST Firewall | 1st pass: reject DML/DDL, injection patterns | 2nd pass: agency-specific rules, table allowlists | Client may have stricter policies than agent defaults |
| DLP / PII Scanning | 2nd pass (S21): Presidio, standard entities | 1st pass (S18): agency-specific rules | Client scans first with domain knowledge; agent catches residual |
| Audit Logging | Full trace log (S24b): WORM, 7yr retention | Client SIEM (S19): agency compliance | Both parties need independent, tamper-evident records |
| Rate Limiting | Per-user, per-tool throttling (S6) | Per-connection, per-query limits (S12) | Prevents abuse at both API and database levels |

### 20.6 Security Boundary Legend

```
+---------------------------+
|  Standard component       |   Regular processing block
+---------------------------+

+===========================+
||  Security-critical      ||  Blocks with double borders are
||  component              ||  hard security enforcement points
+===========================+  that CANNOT be bypassed

=============================
    NETWORK BOUNDARY            Only Streamable HTTP + mTLS crosses.
=============================   No database protocol. No raw data unfiltered.

  AGENT PLATFORM zone:         Everything we build, deploy, and guarantee
  CLIENT INFRASTRUCTURE zone:  Everything deployed inside client's network
```

---

## 21. Responsibility Matrix: Agent-Side vs Client-Side

See [SECURE_DATABASE_RESPONSIBILITY_MATRIX.md](./SECURE_DATABASE_RESPONSIBILITY_MATRIX.md)
for the detailed breakdown of which security layers are the agent developer's
responsibility versus the client's database team.

---

## 22. References

### MCP Specification and Security
- [MCP Authorization Spec (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)
- [MCP Security Best Practices](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices)
- [MCP Server Best Practices (Docker)](https://www.docker.com/blog/mcp-server-best-practices/)
- [Enterprise-Grade Security for MCP (arXiv:2504.08623)](https://arxiv.org/abs/2504.08623)

### Government Compliance
- [FedRAMP AI](https://www.fedramp.gov/ai/)
- [NIST SP 800-53 Rev. 5](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final)
- [NIST SP 800-207 (Zero Trust)](https://csrc.nist.gov/pubs/sp/800/207/final)
- [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)
- [NIST AI 600-1 (GenAI Profile)](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)
- [CISA Zero Trust Maturity Model](https://www.cisa.gov/zero-trust-maturity-model)
- [OMB M-24-10](https://www.whitehouse.gov/wp-content/uploads/2024/03/M-24-10-Advancing-Governance-Innovation-and-Risk-Management-for-Agency-Use-of-Artificial-Intelligence.pdf)

### Security Research
- [ToxicSQL (arXiv:2503.05445)](https://arxiv.org/abs/2503.05445)
- [P2SQL Injections (ICSE 2025)](https://dl.acm.org/doi/10.1109/ICSE55347.2025.00007)
- [MCP Attack Vectors (Unit 42)](https://unit42.paloaltonetworks.com/model-context-protocol-attack-vectors/)
- [MCP PostgreSQL SQL Injection (Datadog)](https://securitylabs.datadoghq.com/articles/mcp-vulnerability-case-study-SQL-injection-in-the-postgresql-mcp-server/)
- [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications/)

### Tools and Platforms
- [HashiCorp Vault Dynamic Secrets](https://developer.hashicorp.com/vault/tutorials/db-credentials/database-secrets)
- [Microsoft Presidio (PII Detection)](https://github.com/microsoft/presidio)
- [AcraCensor SQL Firewall](https://www.cossacklabs.com/blog/how-to-build-sql-firewall-acracensor/)
- [pgAudit](https://www.pgaudit.org/)
- [PostgreSQL Anonymizer](https://postgresql-anonymizer.readthedocs.io/)
- [Cube.js Semantic Layer](https://cube.dev/blog/semantic-layer-and-ai-the-future-of-data-querying-with-natural-language)

### Academic Papers (2024-2026)
- [AI Agent Systems: Architectures (arXiv:2601.01743)](https://arxiv.org/html/2601.01743v1)
- [Agentic AI Security: Threats, Defenses (arXiv:2510.23883)](https://arxiv.org/html/2510.23883v1)
- [AI Agents Under Threat (ACM Computing Surveys)](https://dl.acm.org/doi/10.1145/3716628)
- [Differential Privacy and AI (Springer)](https://link.springer.com/article/10.1186/s13635-025-00203-9)
- [Penetration Testing of Agentic AI (arXiv:2512.14860)](https://arxiv.org/pdf/2512.14860)
