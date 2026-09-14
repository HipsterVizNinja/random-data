# Tableau build — Retail Sales Activity

A Tableau replica of the Sigma **Retail Sales Activity** data model
(`8c548776-acb2-46ac-b60d-dd5a70781bd2`, playground org), published to the
`concorddemo` Tableau Cloud site.

| | |
|---|---|
| Data source | **Retail Sales Activity** — [open](https://us-east-1.online.tableau.com/#/site/concorddemo/datasources/178815073) |
| LUID | `242c1eb7-254a-42cc-a819-51c8f77b0b49` |
| Project | Retail (`d0162af7-0be2-4fed-9a3a-b43d8ada2443`) |
| Contents | 4,899,866 activity rows + 5 dimensions, 117 MB extract, 74 MB `.tdsx` |

## Rebuild

```bash
python3 tableau/build_sales_activity.py            # build the .tdsx only
python3 tableau/build_sales_activity.py --publish  # build and publish (overwrites)
```

Credentials are read at call time from the `tableau` MCP server entry in
`~/.claude.json`; nothing is stored in this repo. Build artefacts go to
`/tmp/retail_tableau` (`RETAIL_TABLEAU_BUILD_DIR` to change).

| File | Role |
|---|---|
| `prep_sales_activity.py` | Rebuilds the Sigma element chain from the CSVs: `pos_agg` / `ret_agg` → `sale_lines` + `return_lines` → `activity_base`, plus the six dimensions' column picks. Run it directly to self-check against the model's published totals. |
| `hyperwrite.py` | Writes the multi-table `.hyper`, driven by the same column specs as the `.tds`. |
| `tdsbuild.py` | Generates the `.tds` / `.tdsx`: relations, field naming, metadata records, calculated fields, folders, hierarchies, descriptions, object graph. |
| `publish.py` | REST publish, chunked above 60 MB. |
| `tabapi.py` | Sign-in against the site named in the MCP config. |
| `build_pulse_metrics.py` | Creates the 18 Tableau Pulse metric definitions and verifies each value against the data source. |
| `pulse.py` | Pulse definition/metric API. |
| `pulse_bundle.py` | Asks Pulse to compute a metric's current value (the "ban" insight bundle). |
| `vizstate.py` | Builds the `viz_state_specification` Pulse needs for calculation-backed metrics. |
| `vds.py` | Queries the published data source through the VizQL Data Service. |

## Model shape

One logical table: the `Sales Activity` fact with Date, Product, Store, Customer
and Salesperson **left-joined** onto it — the same five joins the Sigma element
performs — and the model's 18 metrics as calculated fields. Fields are foldered
by source table, with Product, Store and Fiscal Calendar hierarchies. Every
metric carries its description from `describe_sales_activity_metrics.py`, so
Sigma and Tableau document the metrics from one source.

### Why joined and not related

Tableau Cloud **mis-binds a hand-written object graph of three or more related
tables**. Objects are paired with physical tables positionally, not by the
`object-id` on the relationship end-points, so every cross-table query fails
with `Logical Query missing field [X] from relationOp [Extract].[Y]` — naming a
table that is not the one the field belongs to. Verified on this site:

- two tables, one relationship — fine;
- three tables — broken, and the query does not even have to touch the third;
- unchanged by object-id format, declaration order, `<cols>` order, ordinals,
  per-table connections, `<columns>` children, or dropping the metadata records;
- broken over packaged Excel as well as `.hyper`, so it is not extract-specific;
- the file the server stores back is byte-for-byte the model that was sent, and a
  Desktop-authored three-table model (Superstore) queries correctly on the same
  site — so it is the hand-authored object graph that is not accepted, not the
  server.

`tdsbuild.Datasource` still supports `relationships=` for the two-table case; the
star uses `joins=`. Because every fact→dimension join is many-to-one and left,
the joined model returns identical numbers, which is what the verification below
checks.

### Two more things a hand-built .tds must get right

Both were found by bisecting a model Pulse refused to read, and both are silent
— VizQL and Desktop accept the file either way:

- **No `<folder>` elements.** Any folder, of any role, with any contents, makes
  Tableau Pulse fail to read the data source entirely (404 `Failed to fetch
  datasource` from `/api/-/pulse/datasources/{luid}`), whatever the layout's
  `show-structure` setting. The published star therefore has no field folders;
  because the dimensions are joined, the data pane still groups fields by source
  table. `tdsbuild` keeps the folder support but documents the cost.
- **`<desc>` goes after `<calculation>`**, not before, inside a calculated
  field. The other order breaks the same Pulse fetch. Descriptions on plain
  columns are fine in either position.

## Verification

Checked against the Sigma model on 2026-09-13, via the Tableau MCP and the Sigma
MCP against the live model:

- all **18 metrics company-wide** match the published figures exactly
  (Gross Sales $1,178,971,663.73, Net Sales $1,114,855,651.92, Order Count
  717,747, Customer Count 4,867, AOV $1,553.27, …);
- **by fiscal year** — Net Sales, Gross Sales, Order Count, Return Rate %, AOV
  match Sigma to the cent for FY2021–FY2025;
- **Store Region × Product Type** — all 30 rows match Sigma to the cent on Net
  Sales, Customer Count and Net Margin %, exercising three different dimensions
  including a distinct count.

`prep_sales_activity.py` re-checks nine of those figures at build time, so a
change in the source CSVs shows up before anything is published.

## Not included

`sales_orders`, `budget` and `markdowns` — the Sigma model's other three
elements — are out of scope for this data source. They sit at different grains
(order, store × fiscal period, product × promotion) and would need either
separate data sources or the multi-fact relationship model that the defect above
rules out for now.

## Tableau Pulse

All 18 metrics are published as Pulse metric definitions on the same data
source. `python3 tableau/build_pulse_metrics.py` prints the plan, `--publish`
creates or updates them and then verifies, `--verify` re-checks what is live,
and `--delete` removes them. Definitions are matched by name, so re-running
updates in place rather than duplicating.

### How the metrics map onto Pulse

Pulse's `basic_specification` expresses exactly one field under one aggregation,
plus filters, so the 18 split in two:

| | Metrics | Mechanism |
|---|---|---|
| **8 basic** | Net Sales, Gross Sales, Net Cost, Net Gross Margin, Net Units, Gross Units, Order Count, Customer Count | field + aggregation, with `Activity Type = Sale` as a filter on the four sale-only ones |
| **10 viz_state** | Returns, Return Rate %, Net Margin %, AOV, Gross AOV, UPT, Frequency, Spend per Customer, AUR, AUC | the model's formula carried in a `viz_state_specification` |

The ten are ratios of two aggregates, or a re-signed sum, which a basic
specification cannot express. **Pulse lists the data source's aggregate
calculated fields and will even accept one as a basic measure — and then fails
to compute it** (`400928` from the insight bundle), so the aggregate calcs on
the data source are not usable as Pulse measures and the formula is carried in a
viz state instead, the same shape Pulse's own UI writes. Both kinds get the full
insight suite: period-over-period, trend, unusual change, and top contributors
across all 14 allowed dimensions.

### The time offset

The data stops on 2025-10-18, so with a live "today" every metric would report
an empty current period. Each definition therefore carries
`extension_options.offset_from_today`, in days, which moves Pulse's anchor to
the end of the data (330 days as of 2026-09-13). The script computes it from
`MAX(Activity Date)` at run time — **re-run `--publish` to refresh it**, since a
fixed day count drifts as real time passes.

### Verification

`--publish` and `--verify` compare every Pulse value against the data source
itself, through the VizQL Data Service, for the last complete month in the data
(September 2025). All 18 matched exactly on 2026-09-13 — for example Net Sales
$26,516,101.72, Order Count 17,504, AOV $1,514.8596, Return Rate % 6.15%.
