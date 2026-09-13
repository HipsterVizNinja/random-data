# SQL layer

This folder is the lift-and-shift artifact. The local build runs in pandas
(`Build/build_mart.py`) because the project carries no database dependency;
this SQL is the same transform expressed for Snowflake, and it is what you run
once the flat files have been staged.

Run order:

| File | Purpose |
|---|---|
| `10_snowflake_ddl.sql` | Schemas and landing tables, one per source file |
| `11_snowflake_copy.sql` | `COPY INTO` per table from an internal stage |
| `20_stg.sql` | Typing, trimming, and code conformance. No joins, no business logic |
| `30_xwalk.sql` | Identity resolution across the three patient and three provider key spaces |

Identity resolution stages into its own `raw_mdm` schema rather than being
derived in the warehouse, because an MDM process owns it. The local build
writes those files under `Mart/` only because there is no separate MDM system
to land them from.
| `40_dim.sql` | Conformed dimensions, including both type-2 builds |
| `50_fct.sql` | Facts, including the member-month gaps-and-islands build |
| `60_audit.sql` | The validation suite as SQL, writing to `audit.*` |
| `90_demo_query_pack.sql` | Naive and correct query pairs, side by side |

Conventions, so nothing needs quoting in Sigma or Tableau: all identifiers
lowercase, `<entity>_key` for surrogates, `<entity>_id` for natural keys,
`dim_` / `fct_` / `br_` / `xwalk_` prefixes, money as `NUMBER(12,2)` and never
`FLOAT`. No `ARRAY`, `OBJECT` or `VARIANT` columns anywhere in `mart` - the
diagnosis bridges exist precisely so that arrays are not needed, and a
semi-structured column would break both Tableau extracts and Sigma.
