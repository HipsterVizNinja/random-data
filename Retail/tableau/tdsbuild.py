"""Generate a Tableau .tdsx holding a multi-table relationship model over a packaged .hyper.

The XML dialect mirrors a datasource downloaded from the target site (Superstore,
build 20243.25) rather than being invented: same document-format-change-manifest,
same <cols> uniquification, same metadata-record shape, same <object-graph>.
"""
import hashlib
import os
import zipfile

# tds local-type -> (remote-type code, default aggregation, tds 'type')
TYPES = {
    "integer": (20, "Sum", "quantitative"),
    "real": (5, "Sum", "quantitative"),
    "string": (129, "Count", "nominal"),
    "date": (133, "Year", "ordinal"),
    "datetime": (135, "Year", "ordinal"),
    "boolean": (11, "Count", "nominal"),
}

DATA_DIR = "Data/Datasources"


def esc(value):
    """Escape for a single-quoted XML attribute."""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("'", "&apos;").replace('"', "&quot;"))


class Col:
    def __init__(self, remote, dtype, role="dimension", caption=None, desc=None,
                 fmt=None, hidden=False, semantic_role=None, agg=None):
        self.remote = remote
        self.dtype = dtype
        self.role = role
        self.caption = caption or remote
        self.desc = desc
        self.fmt = fmt
        self.hidden = hidden
        self.semantic_role = semantic_role
        self.agg = agg or TYPES[dtype][1]
        self.dsname = None  # assigned by Datasource (may be uniquified)


class Table:
    def __init__(self, name, columns, caption=None):
        self.name = name
        self.caption = caption or name
        self.columns = columns
        self.object_id = "%s_%s" % (
            name.replace(" ", ""), hashlib.md5(name.encode()).hexdigest().upper())


class Calc:
    def __init__(self, name, formula, dtype="real", role="measure", desc=None,
                 fmt=None, caption=None, type_=None):
        self.name = name
        self.caption = caption or name
        self.formula = formula
        self.dtype = dtype
        self.role = role
        self.desc = desc
        self.fmt = fmt
        self.type = type_ or TYPES[dtype][2]


def _desc_xml(text, indent):
    pad = " " * indent
    return (f"{pad}<desc>\n{pad}  <formatted-text>\n{pad}    <run>{esc(text)}</run>\n"
            f"{pad}  </formatted-text>\n{pad}</desc>\n")


class Datasource:
    def __init__(self, name, hyper_file, tables, relationships=(), joins=(),
                 calcs=(), folders=(), drill_paths=(), description=None):
        self.name = name
        self.hyper_file = hyper_file          # local path to the .hyper
        self.tables = tables
        self.relationships = list(relationships)  # (ltable, lcol, rtable, rcol), remote names
        # Physical left-deep joins, same tuple shape. A joined model is ONE
        # logical table; Tableau Cloud mis-binds hand-written object graphs of
        # three or more related tables, so the star is joined, not related.
        self.joins = list(joins)
        if self.joins and self.relationships:
            raise ValueError("a datasource is either joined or related, not both")
        self.calcs = list(calcs)
        self.folders = list(folders)           # (folder name, role, [field ds-names])
        self.drill_paths = list(drill_paths)   # (name, [field ds-names])
        self.description = description
        self.conn = "hyper.retail"
        self._assign_dsnames()

    def _assign_dsnames(self):
        """Reproduce Tableau's field-name uniquification: later duplicates get ' (Table)'."""
        taken = set()
        for table in self.tables:
            for col in table.columns:
                name = col.remote
                if name in taken:
                    name = f"{col.remote} ({table.caption})"
                    suffix = 2
                    while name in taken:
                        name = f"{col.remote} ({table.caption} {suffix})"
                        suffix += 1
                taken.add(name)
                col.dsname = name

    def dsname(self, table_name, remote):
        for table in self.tables:
            if table.name == table_name:
                for col in table.columns:
                    if col.remote == remote:
                        return col.dsname
        raise KeyError(f"{table_name}.{remote}")

    # ---- XML sections -------------------------------------------------
    def _table_relation(self, table, indent):
        return (f"{' ' * indent}<relation connection='{self.conn}' name='{esc(table.name)}' "
                f"table='[Extract].[{esc(table.name)}]' type='table' />")

    def _join_tree(self, indent):
        """Left-deep join tree over the tables, in the order the joins are given."""
        tree = self._table_relation(self.tables[0], indent + 2 * len(self.joins))
        for depth, (ltable, lcol, rtable, rcol) in enumerate(reversed(self.joins)):
            pad = " " * (indent + 2 * (len(self.joins) - depth - 1))
            right = next(t for t in self.tables if t.name == rtable)
            tree = (f"{pad}<relation join='left' type='join'>\n"
                    f"{pad}  <clause type='join'>\n"
                    f"{pad}    <expression op='='>\n"
                    f"{pad}      <expression op='[{esc(ltable)}].[{esc(lcol)}]' />\n"
                    f"{pad}      <expression op='[{esc(rtable)}].[{esc(rcol)}]' />\n"
                    f"{pad}    </expression>\n"
                    f"{pad}  </clause>\n"
                    f"{tree}\n"
                    f"{self._table_relation(right, indent + 2 * (len(self.joins) - depth))}\n"
                    f"{pad}</relation>")
        return tree

    def _relations(self):
        if self.joins:
            return ("    <relation type='collection'>\n" + self._join_tree(6)
                    + "\n    </relation>")
        out = ["    <relation type='collection'>"]
        for t in self.binding_order():
            out.append(self._table_relation(t, 6))
        out.append("    </relation>")
        return "\n".join(out)

    def _col_maps(self):
        """The <cols> entries, sorted the way the server stores them."""
        rows = []
        for t in self.tables:
            for c in t.columns:
                rows.append((f"      <map key='[{esc(c.dsname)}]' "
                             f"value='[{esc(t.name)}].[{esc(c.remote)}]' />", t))
        return sorted(rows, key=lambda row: row[0])

    def binding_order(self):
        """Tables in the order the query engine binds objects to them.

        The engine pairs object-graph objects with physical tables positionally,
        in the order each table first appears in the sorted <cols> map -- it does
        not honour the object-id on the relationship end-points. Emitting the
        objects in any other order silently binds every table to the wrong one
        and every cross-table query then fails to resolve its join fields.
        """
        seen = []
        for _, table in self._col_maps():
            if table not in seen:
                seen.append(table)
        return seen + [t for t in self.tables if t not in seen]

    def _cols(self):
        return ("    <cols>\n" + "\n".join(row for row, _ in self._col_maps())
                + "\n    </cols>")

    def _metadata_records(self):
        out = ["    <metadata-records>"]
        ordinal = 0
        for t in self.tables:
            for c in t.columns:
                remote_type = TYPES[c.dtype][0]
                out.append("      <metadata-record class='column'>")
                out.append(f"        <remote-name>{esc(c.remote)}</remote-name>")
                out.append(f"        <remote-type>{remote_type}</remote-type>")
                out.append(f"        <local-name>[{esc(c.dsname)}]</local-name>")
                out.append(f"        <parent-name>[{esc(t.name)}]</parent-name>")
                out.append(f"        <remote-alias>{esc(c.remote)}</remote-alias>")
                out.append(f"        <ordinal>{ordinal}</ordinal>")
                out.append(f"        <local-type>{c.dtype}</local-type>")
                out.append(f"        <aggregation>{c.agg}</aggregation>")
                out.append("        <contains-null>true</contains-null>")
                if c.dtype == "string":
                    out.append("        <collation flag='1' name='LEN_RUS_S2' />")
                out.append(f"        <object-id>[{t.object_id}]</object-id>")
                out.append("      </metadata-record>")
                ordinal += 1
        out.append("    </metadata-records>")
        return "\n".join(out)

    def _columns(self):
        out = []
        for t in self.tables:
            for c in t.columns:
                attrs = [f"caption='{esc(c.caption)}'", f"datatype='{c.dtype}'"]
                if c.fmt:
                    attrs.append(f"default-format='{esc(c.fmt)}'")
                if c.hidden:
                    attrs.append("hidden='true'")
                attrs.append(f"name='[{esc(c.dsname)}]'")
                attrs.append(f"role='{c.role}'")
                if c.semantic_role:
                    attrs.append(f"semantic-role='{esc(c.semantic_role)}'")
                type_ = TYPES[c.dtype][2] if c.role == "measure" else (
                    "ordinal" if c.dtype in ("date", "datetime") else "nominal")
                attrs.append(f"type='{type_}'")
                head = "  <column " + " ".join(attrs)
                if c.desc:
                    out.append(head + ">\n" + _desc_xml(c.desc, 4) + "  </column>")
                else:
                    out.append(head + " />")
        for calc in self.calcs:
            attrs = [f"caption='{esc(calc.caption)}'", f"datatype='{calc.dtype}'"]
            if calc.fmt:
                attrs.append(f"default-format='{esc(calc.fmt)}'")
            attrs += [f"name='[{esc(calc.name)}]'", f"role='{calc.role}'",
                      f"type='{calc.type}'"]
            # Order matters: a <desc> placed before <calculation> makes the whole
            # data source unreadable to Tableau Pulse (404 from its datasource
            # fetch), while VizQL and Desktop accept either order.
            body = f"    <calculation class='tableau' formula='{esc(calc.formula)}' />\n"
            if calc.desc:
                body += _desc_xml(calc.desc, 4)
            out.append("  <column " + " ".join(attrs) + ">\n" + body + "  </column>")
        return "\n".join(out)

    def _drill_paths(self):
        if not self.drill_paths:
            return ""
        out = ["  <drill-paths>"]
        for name, fields in self.drill_paths:
            out.append(f"    <drill-path name='{esc(name)}'>")
            for f in fields:
                out.append(f"      <field>[{esc(f)}]</field>")
            out.append("    </drill-path>")
        out.append("  </drill-paths>")
        return "\n".join(out)

    def _folders(self):
        """Field folders.

        WARNING: any <folder> element makes Tableau Pulse fail to fetch the data
        source (404 "Failed to fetch datasource"), whatever the folder's role,
        contents, or the layout's show-structure setting. A joined model already
        groups fields by source table in the data pane, so folders are left out
        of the published star. Keep this method for models that never need Pulse.
        """
        out = []
        for name, role, fields in self.folders:
            out.append(f"  <folder name='{esc(name)}' role='{role}'>")
            for f in fields:
                out.append(f"    <folder-item name='[{esc(f)}]' type='field' />")
            out.append("  </folder>")
        return "\n".join(out)

    def _object_graph(self):
        if self.joins:
            primary = self.tables[0]
            return ("  <object-graph>\n    <objects>\n"
                    f"      <object caption='{esc(primary.caption)}' id='{primary.object_id}'>\n"
                    "        <properties context=''>\n"
                    + self._join_tree(10) + "\n"
                    "        </properties>\n      </object>\n"
                    "    </objects>\n  </object-graph>")
        out = ["  <object-graph>", "    <objects>"]
        for t in self.binding_order():
            out.append(f"      <object caption='{esc(t.caption)}' id='{t.object_id}'>")
            out.append("        <properties context=''>")
            out.append(f"          <relation connection='{self.conn}' name='{esc(t.name)}' "
                       f"table='[Extract].[{esc(t.name)}]' type='table' />")
            out.append("        </properties>")
            out.append("      </object>")
        out.append("    </objects>")
        out.append("    <relationships>")
        for ltable, lcol, rtable, rcol in self.relationships:
            left = next(t for t in self.tables if t.name == ltable)
            right = next(t for t in self.tables if t.name == rtable)
            out.append("      <relationship>")
            out.append("        <expression op='='>")
            out.append(f"          <expression op='[{esc(self.dsname(ltable, lcol))}]' />")
            out.append(f"          <expression op='[{esc(self.dsname(rtable, rcol))}]' />")
            out.append("        </expression>")
            out.append(f"        <first-end-point object-id='{left.object_id}' />")
            out.append(f"        <second-end-point object-id='{right.object_id}' />")
            out.append("      </relationship>")
        out.append("    </relationships>")
        out.append("  </object-graph>")
        return "\n".join(out)

    def tds(self):
        hyper_rel = f"{DATA_DIR}/{os.path.basename(self.hyper_file)}"
        parts = [
            "<?xml version='1.0' encoding='utf-8' ?>\n",
            f"<datasource formatted-name='{esc(self.name)}' inline='true' source-platform='mac' "
            "version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>",
            "  <document-format-change-manifest>",
            "    <ObjectModelEncapsulateLegacy />",
            "    <ObjectModelTableType />",
            "    <SchemaViewerObjectModel />",
            "  </document-format-change-manifest>",
            "  <connection class='federated'>",
            "    <named-connections>",
            f"      <named-connection caption='{esc(self.name)}' name='{self.conn}'>",
            "        <connection access_mode='readonly' authentication='auth-none' "
            f"class='hyper' dbname='{esc(hyper_rel)}' default-settings='yes' "
            "schema='Extract' sslmode='' tablename='' username='tableau_internal_user' />",
            "      </named-connection>",
            "    </named-connections>",
            self._relations(),
            self._cols(),
            self._metadata_records(),
            "  </connection>",
            "  <aliases enabled='yes' />",
            self._columns(),
        ]
        if self.description:
            parts.append(_desc_xml(self.description, 2).rstrip("\n"))
        for section in (self._drill_paths(), self._folders()):
            if section:
                parts.append(section)
        parts.append("  <layout dim-ordering='alphabetic' measure-ordering='alphabetic' "
                     "show-structure='true' />")
        parts.append(self._object_graph())
        parts.append("</datasource>\n")
        return "\n".join(parts)

    def write_tdsx(self, path):
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{self.name}.tds", self.tds())
            z.write(self.hyper_file, f"{DATA_DIR}/{os.path.basename(self.hyper_file)}")
        return path
