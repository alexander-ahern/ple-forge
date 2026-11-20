#!/usr/bin/env python3
"""Last-resort deliverable scaffolder.

Runs inside the task container with only the Python standard library (optional
openpyxl/python-docx are used when present). It creates a clearly-marked draft
at any required path that is still missing, empty, or an archive missing a
required member. This is not a solution; it is the safety net that prevents a
missing-file zero when the model ran out of time.

Usage: python3 scaffold.py <workdir> <deliverables.json> <scratch>
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import zipfile

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""
ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
SHEET = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>"""
DOCX_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
DOCX_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
DOCX_BODY = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>DRAFT - the model did not finish this deliverable. Replace with the completed content.</w:t></w:r></w:p></w:body>
</w:document>"""
DXF = "0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n"
IFC = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('draft.ifc','2026-01-01T00:00:00',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
ENDSEC;
END-ISO-10303-21;
"""


def write_xlsx(path: str) -> bool:
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", CONTENT_TYPES)
            zf.writestr("_rels/.rels", ROOT_RELS)
            zf.writestr("xl/workbook.xml", WORKBOOK)
            zf.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
            zf.writestr("xl/worksheets/sheet1.xml", SHEET)
        return True
    except OSError:
        return False


def write_docx(path: str) -> bool:
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", DOCX_TYPES)
            zf.writestr("_rels/.rels", DOCX_RELS)
            zf.writestr("word/document.xml", DOCX_BODY)
        return True
    except OSError:
        return False


def placeholder(path: str, fmt: str) -> bool:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return False
    if fmt in (".xlsx", ".xlsm"):
        return write_xlsx(path)
    if fmt in (".docx",):
        return write_docx(path)
    if fmt == ".dxf":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(DXF)
        return True
    if fmt == ".ifc":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(IFC)
        return True
    if fmt == ".json":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{}\n")
        return True
    if fmt == ".csv":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("")
        return True
    if fmt == ".py":
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('"""DRAFT: the model did not finish this deliverable."""\n')
        return True
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(
            "# DRAFT\n\nThe model did not finish this deliverable before the deadline.\n"
        )
    return True


def archive(path: str, members: list[dict[str, object]], workdir: str) -> bool:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scaffold-") as tmp:
        for member in members:
            name = str(member.get("name", "")).strip()
            if not name or "/" in name or "\\" in name:
                continue
            fmt = str(member.get("format", ""))
            placeholder(os.path.join(tmp, name), fmt)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            mode = "a"
        else:
            mode = "w"
        with zipfile.ZipFile(path, mode, zipfile.ZIP_DEFLATED) as zf:
            existing = set(zf.namelist())
            for name in sorted(os.listdir(tmp)):
                if name not in existing:
                    zf.write(os.path.join(tmp, name), arcname=name)
    return True


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: scaffold.py <workdir> <deliverables.json> <scratch>", file=sys.stderr)
        return 2
    workdir = os.path.abspath(sys.argv[1])
    with open(sys.argv[2], "r", encoding="utf-8") as fh:
        deliverables = json.load(fh)
    created = []
    for item in deliverables:
        raw = str(item.get("path", ""))
        if not raw:
            continue
        path = raw if os.path.isabs(raw) else os.path.join(workdir, raw)
        path = os.path.abspath(path)
        kind = item.get("kind", "file")
        if kind == "dir":
            if not os.path.isdir(path):
                os.makedirs(path, exist_ok=True)
                created.append(path)
            continue
        if item.get("format") == ".zip" and item.get("members"):
            if not os.path.exists(path) or os.path.getsize(path) == 0:
                archive(path, item["members"], workdir)
                created.append(path)
            else:
                # Add any missing required members to the existing archive.
                with zipfile.ZipFile(path) as zf:
                    existing = set(zf.namelist())
                missing = [
                    m
                    for m in item["members"]
                    if str(m.get("name", "")) and str(m.get("name")) not in existing
                ]
                if missing:
                    archive(path, missing, workdir)
                    created.append(path)
            continue
        fmt = str(item.get("format", ""))
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            if placeholder(path, fmt):
                created.append(path)
    print(json.dumps({"created": created}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
