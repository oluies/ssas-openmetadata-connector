# Feature Specification: Measure lineage — what a calculation is built from

**Feature Branch**: `002-measure-lineage`

**Created**: 2026-09-08

**Status**: Draft

**Input**: Users want to see how a calculation is composed — which fields feed into which measure — not merely that a measure exists.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See what a measure is built from (Priority: P1)

An analyst opens a measure in the catalogue — `Total Sales`, say — and sees which columns it
reads. Today they see a name and a data type, which tells them nothing about whether the number
is what they think it is. They should see that it sums `FactInternetSales[SalesAmount]`, and be
able to click through to that column.

**Why this priority**: This is the whole request. Everything else is refinement of it, and a
measure whose inputs are visible is the difference between a catalogue entry and an
explanation.

**Independent Test**: Ingest a model with a simple additive measure and confirm the catalogue
shows an edge from the source column to the measure, and the expression alongside it.

**Acceptance Scenarios**:

1. **Given** a measure defined as a sum over one column, **When** the model is ingested,
   **Then** the catalogue records that column as an input to the measure.
2. **Given** a measure referencing several columns, **When** ingested, **Then** every
   referenced column is recorded, with none invented and none dropped.
3. **Given** a measure whose expression cannot be parsed with confidence, **When** ingested,
   **Then** the expression is still shown, and the absence of extracted inputs is explicit
   rather than looking like "no inputs".

---

### User Story 2 - Read the definition even when the inputs cannot be derived (Priority: P2)

A user looking at a complex calculation sees its actual definition, verbatim, even where
nothing can be reliably extracted from it. Seeing the expression is useful on its own.

**Why this priority**: It is the fallback that makes Story 1 safe to ship. Storing the
expression is nearly free and is never wrong, whereas extraction can be.

**Independent Test**: Ingest a model containing a deliberately gnarly measure and confirm the
expression is present and unaltered, with no fabricated inputs.

**Acceptance Scenarios**:

1. **Given** any measure with a definition, **When** ingested, **Then** the definition is
   stored verbatim.
2. **Given** an expression the extractor does not understand, **When** ingested, **Then** no
   input edges are claimed for it.

---

### User Story 3 - Follow a measure back to the warehouse (Priority: P3)

A user traces a measure past the model's own columns to the relational tables underneath, so
they can see the full path from a number on a report to the source system.

**Why this priority**: Valuable, and it composes with the table-level lineage the connector
already emits — but it is only meaningful once Story 1 works.

**Independent Test**: For a measure over a column whose table already has lineage to a SQL
source, confirm the path from measure to source table is traversable in the catalogue.

**Acceptance Scenarios**:

1. **Given** a measure over a column on a table with existing source lineage, **When**
   ingested, **Then** measure → column → source table is connected.

---

### Edge Cases

- A measure that references only other measures, never a column directly.
- A measure whose expression names a column that no longer exists.
- Two columns of the same name on different tables; an unqualified reference.
- Expressions containing string literals that look like column references.
- Comments inside the expression, including commented-out references.
- A measure defined on a perspective rather than the base model.
- Very long expressions, and expressions containing characters that need escaping.
- A model where the account may read metadata but not the measure definitions.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The connector MUST capture each measure's definition as the server reports it,
  without alteration.
- **FR-002**: The connector MUST extract, where it can do so reliably, the set of columns a
  measure reads, and record each as an input to that measure.
- **FR-003**: The connector MUST NOT claim an input it is not confident about. Under-reporting
  is required behaviour; a fabricated edge is worse than a missing one, because a catalogue is
  trusted.
- **FR-004**: The connector MUST make the difference visible between "this measure reads
  nothing" and "the inputs could not be determined". These MUST NOT look alike.
- **FR-005**: The connector MUST resolve an unqualified column reference only when it is
  unambiguous within the model; otherwise it MUST record no edge for it.
- **FR-006**: The connector MUST work with a read-only account and MUST NOT require an
  admin-gated interface to obtain definitions.
- **FR-007**: The connector MUST handle both model kinds — the tabular and multidimensional
  expression languages are different and MUST NOT share a parser by assumption.
- **FR-008**: Extraction MUST be testable offline against recorded definitions, with no live
  server.
- **FR-009**: The feature MUST be able to be turned off, so a site that does not want
  expressions in its catalogue need not have them.
- **FR-010**: A measure whose definition cannot be read MUST NOT fail the ingestion of the rest
  of the model.

### Key Entities

- **Measure**: A named calculation belonging to a model, carrying a definition expressed in
  that model's language.
- **Definition**: The expression as the server reports it. Stored verbatim; never rewritten.
- **Input reference**: A column a measure has been determined to read. Carries how it was
  determined, so a consumer can weigh it.
- **Determination outcome**: For each measure — inputs found, none found, or not determinable.
  The third is distinct from the second and must remain so.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a model of simple additive measures, every measure shows at least one input,
  and each input is a column that measure genuinely reads.
- **SC-002**: Zero fabricated inputs across the sample corpus — every extracted reference
  corresponds to a real column in the model.
- **SC-003**: Every measure with a definition shows that definition, regardless of whether
  inputs were extracted.
- **SC-004**: A user can go from a measure to a source-system table without leaving the
  catalogue, for measures over columns that already have source lineage.
- **SC-005**: Measures whose inputs could not be determined are identifiable as such, and their
  proportion is reportable after an ingestion.
- **SC-006**: Turning the feature off produces the same catalogue as before the feature existed.

## Assumptions

- **Definitions are metadata, not data.** They are read through the same reader-accessible
  interfaces the connector already uses; no rows are read to obtain them. This is what makes
  the feature safe to run against production.
- **Expressions may name business concepts** — a column called `NetMarginAfterRebate` is itself
  disclosure of a sort. Sites that consider their measure logic sensitive are the reason FR-009
  exists.
- Extraction quality will vary sharply by expression complexity. A simple aggregate over one
  column is near-certain; a multi-branch time-intelligence calculation may yield nothing. The
  design treats a confident subset as the deliverable rather than aiming at completeness.
- **An LLM is not assumed.** A deterministic extractor covers the simple majority and is
  testable offline. Whether to add a model-based extractor for the hard cases is a separate
  decision, deliberately not taken here: it would introduce a non-deterministic dependency into
  an ingestion path whose other outputs are exactly reproducible, and FR-003 would then need a
  confidence policy that FR-002 does not.
- The corpus of real definitions needed to design extraction can be gathered without exporting
  any data — see `docs/extracting-definitions.md`.
