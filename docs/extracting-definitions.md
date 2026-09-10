# Extracting measure definitions from production — without extracting data

To design measure lineage ([`specs/002-measure-lineage`](../specs/002-measure-lineage/spec.md))
we need a corpus of **real** measure definitions. Toy examples will not do: the extractor has
to survive whatever your modellers actually wrote, and invented examples are always tidier
than reality.

This describes how to collect those definitions from a production instance **without reading a
single row of data**.

## Why this is safe

A measure's definition is *metadata*. It lives in the same schema rowsets the connector already
reads to list tables and columns. Asking for it retrieves the formula, not the numbers the
formula produces.

The distinction is exact and worth stating plainly:

| Query shape | Returns | Safe |
|---|---|---|
| `SELECT * FROM $SYSTEM.MDSCHEMA_MEASURES` | measure names and their expressions | ✅ metadata |
| `DISCOVER_CSDL_METADATA` | the model's shape, including measure definitions | ✅ metadata |
| `EVALUATE Sales` | **rows from the model** | ❌ data |
| `SELECT ... ON 0 FROM [Cube]` | **cell values** | ❌ data |

Everything below is in the first category. Nothing below evaluates a measure, so no aggregate,
no row and no cell value is produced. **If a command contains `EVALUATE` or an MDX `SELECT`
over a cube, it is not on this page.**

## What you still are disclosing

Being straight about this, because "no data" is not the same as "nothing sensitive":

- **Column and table names**, which may carry business meaning (`GrossMarginPreRebate`).
- **The logic itself** — a measure's formula can encode commercial rules.
- Occasionally **literals inside expressions**: a threshold, a rate, a hard-coded account code.
  These are the one place actual figures can appear.

So review before sending, and scrub if needed. There is a scrubbing step below.

## The single query you need

For a multidimensional model, over the connector's existing HTTP path or from SSMS:

```sql
SELECT [MEASURE_NAME], [EXPRESSION], [MEASURE_IS_VISIBLE]
FROM $SYSTEM.MDSCHEMA_MEASURES
```

For a tabular model, the same rowset works, and `DISCOVER_CSDL_METADATA` also returns measure
definitions inline with the model — which is what the connector already fetches, so nothing new
is being asked of the server.

`EXPRESSION` is empty for a plain aggregate over a column (the aggregation is structural, not a
formula) and populated for calculated measures. Both cases are interesting: the first is the
easy path the extractor must get right, the second is where it will struggle.

**Avoid `$SYSTEM.TMSCHEMA_MEASURES`.** It carries the same information but is admin-gated, and
this connector deliberately holds only a reader account. If you have admin rights it will work,
but designing against it would build a dependency the connector must not have.

## Doing it with tooling you already have

From this repository, using the reader credentials already in `.env`:

```bash
python - <<'EOF'
import os, sys
sys.path.insert(0, "src")
from ssas_om.client import XmlaClient, parse_rowset

c = XmlaClient(url=os.environ["SSAS_HOST"] + "/olap-md/msmdpump.dll",
               user=os.environ["SSAS_USER"], password=os.environ["SSAS_PASSWORD"])
r = c.dmv("MDSCHEMA_MEASURES", catalog="YourCatalog")
for row in parse_rowset(r.text):
    expr = (row.get("EXPRESSION") or "").strip()
    if expr:
        print(f"--- {row.get('MEASURE_NAME')}\n{expr}\n")
EOF
```

That is one `Discover` against a rowset the connector already uses. It reads no fact table and
evaluates nothing.

## Scrub before sending

Two things worth removing, in order of importance:

1. **Numeric literals**, which are the only place real figures can hide. Replacing every number
   with `0` keeps the expression's *shape* — which is all the extractor cares about — while
   removing any embedded rate or threshold.
2. **Names**, if your column and measure names are themselves sensitive. Consistent renaming
   (`Table1[Col1]`) preserves structure but costs realism, so only do it if you need to.

The repository's own scrubber handles hosts, accounts and SIDs but **not** business names or
literals, so this step is manual and deliberate:

```bash
# blunt but effective: keep the shape, drop the values
sed -E 's/[0-9]+(\.[0-9]+)?/0/g' definitions.txt > definitions.scrubbed.txt
```

Then read it. It is a small file and eyes are the last check.

## What is most useful to send

Roughly in order of value to the design:

1. **Ten to twenty measures spanning the range** — a couple of trivial sums, a few mid-weight
   ones, and the two or three your modellers consider genuinely hairy. The hard ones decide the
   design; the easy ones decide the default.
2. **A note on which are correct**, if any are known to be wrong or deprecated.
3. **Whether names are referenced qualified or unqualified** in your house style — this drives
   FR-005, the ambiguity rule, more than anything else.
4. The model kind for each (tabular or multidimensional), since the expression languages differ
   and must not share a parser.

Anonymised is fine. Realistic beats clean: a formula with awkward spacing, a comment and an
inconsistent qualification style is worth more than five tidy ones.

## What is not needed, and should not be sent

- Any query results, row counts or aggregates.
- Extracts, samples or exports of the underlying tables.
- Connection strings, service accounts or keytabs.
- The `.bim` / model file itself, if it carries data source credentials — the rowset above
  gives the definitions without them.
