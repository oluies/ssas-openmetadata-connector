<!--
Sync Impact Report
- Version change: (none) → 1.0.0  (initial ratification)
- Principles defined: I No Secret Leakage; II Least Privilege; III Offline-First
  Hermetic Tests; IV Discovery-Driven Modeling; V Spec-Driven with Review Gates
- Added sections: Security & Data-Handling Constraints; Development Workflow & Quality Gates
- Removed sections: none
- Templates reviewed for alignment:
    ✅ .specify/templates/plan-template.md  (Constitution Check gate references these principles)
    ✅ .specify/templates/spec-template.md   (no mandatory-section conflicts)
    ✅ .specify/templates/tasks-template.md   (test-discipline + review-gate task types covered)
- Deferred TODOs: none
-->

# ssas-openmetadata-connector Constitution

## Core Principles

### I. No Secret Leakage (NON-NEGOTIABLE)
Credentials, hostnames and IP addresses MUST come only from a gitignored `.env`. A
credential, hostname, IP address, Windows SID or connection string MUST NEVER appear in
any committed file, test fixture, log line or commit message. Every recorded XMLA fixture
MUST be scrubbed of host, IP, username, machine/NetBIOS name, SID and connection-string
fragments before it is written; the scrub is enforced in `scripts/probe.py` and MUST be
re-verified (zero identifying tokens) whenever fixtures are regenerated. Rationale: the
host is a shared, IP-allowlisted fixture reachable with plain-HTTP Basic auth; a leaked
token or address is a real exposure, and fixtures are committed.

### II. Least Privilege
The connector MUST authenticate as a read-only account and MUST use only
reader-accessible metadata interfaces (MDSCHEMA). It MUST NOT require, request or hold
administrator credentials. TMSCHEMA and any other admin-gated rowset are out of scope.
Rationale: discovery proved a read-only account faults on TMSCHEMA but has full MDSCHEMA
access; holding admin credentials to gain marginal metadata is an unjustified risk.

### III. Offline-First Hermetic Tests (NON-NEGOTIABLE)
Unit tests MUST run against the recorded fixture stub with sockets disabled and MUST NOT
depend on the live host being reachable. The Hetzner host is for integration and
acceptance runs only. A unit-test run MUST pass with no network. Rationale: the operator
IP is allowlisted and changes; a suite that needs the host is not reproducible and blocks
CI.

### IV. Discovery-Driven Modeling
The connector MUST be modeled on observed XMLA behaviour captured under
`tests/fixtures/xmla/`, not on assumptions. Where observed reality and any brief or
document disagree, observed reality wins and the document is corrected. New behavioural
assumptions MUST be backed by a fixture before code depends on them. Rationale: the
original brief's central assumption (TMSCHEMA fallback) was wrong; only probing the real
instance surfaced it.

### V. Spec-Driven with Review Gates
Work MUST proceed through the spec-kit pipeline (constitution → specify → clarify → plan →
tasks). Each implementation task MUST be committed on its own and reviewed by roborev,
and the findings read, before the next task begins. Rationale: small reviewed increments
catch defects early and keep the spec and code aligned.

## Security & Data-Handling Constraints

- Secrets: `.env` only, gitignored; a committed `.env.example` carries placeholders.
- OpenMetadata is pinned to **1.13.3**; the ingestion base image and compose MUST match.
- SQL Server and Analysis Services are remote (Hetzner) and MUST NOT appear in any compose
  file; only OpenMetadata, its datastore, its search backend and the connector run locally.
- Transport to SSAS is plain-HTTP Basic auth to msmdpump; the connector MUST treat this as
  untrusted and never log request bodies or auth headers.

## Development Workflow & Quality Gates

- The fixture stub (`docker/ssas-stub/`) serves recorded responses; unit tests target it
  with sockets disabled.
- Every commit is small and scoped to one task; `roborev review HEAD` + `roborev wait` run
  after each, findings read before proceeding.
- Regenerating fixtures MUST re-run the leak check; a non-zero identifying-token count is a
  release blocker.
- A change that weakens a NON-NEGOTIABLE principle MUST be rejected in review.

## Governance

This constitution supersedes other practices for this project. Amendments MUST be recorded
in this file with a Sync Impact Report and a semantic-version bump: MAJOR for removing or
redefining a principle, MINOR for adding a principle or materially expanding guidance,
PATCH for clarifications. Every review MUST verify compliance with these principles;
added complexity MUST be justified against them. Runtime development guidance for agents
lives in `CLAUDE.md`.

**Version**: 1.0.0 | **Ratified**: 2026-08-19 | **Last Amended**: 2026-08-19
