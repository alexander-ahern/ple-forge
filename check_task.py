#!/usr/bin/env python3
"""Deterministic deliverable checker for a PLE task.

Runs inside the task container with only the Python standard library. Reads a
JSON list of deliverables and prints a compact JSON report. It checks that each
path exists, is non-empty, and is structurally valid for its format. Deep
engineering validation is the auditor's job; this script is the safety net that
prevents a missing or empty deliverable from scoring zero.

Usage: python3 check_task.py <workdir> <deliverables.json> [scratch]
"""

from __future__ import annotations

import csv
import io
import json
import os
import sys
import zipfile

MAX_DIR_FILES = 60
MAX_ZIP_ENTRIES = 60
MAX_TEXT_HEAD = 400


def norm(workdir: str, path: str) -> str:
    path = path.strip().strip("\"'")
    if not path:
        return path
    if not os.path.isabs(path):
        path = os.path.join(workdir, path)
    return os.path.abspath(path)


def dir_report(
    path: str,
    baseline: dict[str, dict[str, object]],
    changed_only: bool = False,
) -> dict[str, object]:
    files = []
    total = 0
    nonempty = 0
    changed = 0
    try:
        for base, names, filenames in os.walk(path):
            names[:] = [n for n in names if n not in (".git", "__pycache__", "node_modules")]
            for name in filenames:
                if name.startswith(".") and name not in (".env", ".gitignore"):
                    continue
                full = os.path.join(base, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                size = st.st_size
                total += size
                if size > 0:
                    nonempty += 1
                rel = os.path.relpath(full, path).replace(os.sep, "/")
                old = baseline.get(rel)
                if old is None or size != old.get("size") or st.st_mtime > float(old.get("mtime", 0)) + 1:
                    changed += 1
                if len(files) < MAX_DIR_FILES:
                    files.append({"path": rel, "size": size, "changed": old is None or size != old.get("size")})
    except OSError as exc:
        return {"status": "error", "detail": str(exc)}
    if changed_only:
        status = "ok" if changed > 0 else "empty"
    else:
        status = "ok" if nonempty else "empty"
    return {
        "status": status,
        "kind": "dir",
        "file_count": nonempty,
        "changed_only": changed_only,
        "new_or_changed": changed,
        "total_size": total,
        "files": files,
    }


def text_report(path: str, size: int) -> dict[str, object]:
    try:
        with open(path, "rb") as fh:
            data = fh.read(min(size, 400_000))
        text = data.decode("utf-8", "replace")
    except OSError as exc:
        return {"status": "error", "detail": str(exc)}
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    return {
        "status": "ok" if text.strip() else "empty",
        "kind": "text",
        "chars": len(text),
        "lines": lines,
        "head": text[:MAX_TEXT_HEAD],
    }


def zip_report(path: str, required_names: list[str] | None = None) -> dict[str, object]:
    required = [str(n) for n in (required_names or []) if str(n)]
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if not infos:
                return {"status": "empty", "kind": "archive", "detail": "zip has no entries"}
            names = {i.filename for i in infos}
            entries = [{"name": i.filename, "size": i.file_size} for i in infos[:MAX_ZIP_ENTRIES]]
            ooxml = any(n == "[Content_Types].xml" for n in names)
            missing = [n for n in required if n not in names]
            status = "ok" if not missing else "invalid"
            return {
                "status": status,
                "kind": "archive",
                "entry_count": len(infos),
                "entries": entries,
                "ooxml": ooxml,
                "required_members": required,
                "missing_members": missing,
                "detail": ("missing archive members: " + ", ".join(missing)) if missing else "",
            }
    except (zipfile.BadZipFile, OSError) as exc:
        return {"status": "invalid", "kind": "archive", "detail": str(exc)}


def ifc_report(path: str) -> dict[str, object]:
    try:
        with open(path, "rb") as fh:
            data = fh.read(2_000_000)
        text = data.decode("utf-8", "replace")
    except OSError as exc:
        return {"status": "error", "kind": "ifc", "detail": str(exc)}
    first = text.lstrip()[:40]
    entities = sum(1 for line in text.splitlines() if line.startswith("#"))
    schema = ""
    marker = "FILE_SCHEMA"
    idx = text.find(marker)
    if idx >= 0:
        schema = text[idx : idx + 160].replace("\n", " ")
    ok = first.startswith("ISO-10303-21") and entities > 0
    return {
        "status": "ok" if ok else "invalid",
        "kind": "ifc",
        "header": first,
        "entity_count": entities,
        "schema": schema,
        "detail": "" if ok else "not a STEP/IFC file with entities",
    }


def dxf_report(path: str) -> dict[str, object]:
    try:
        with open(path, "rb") as fh:
            data = fh.read(400_000)
        text = data.decode("utf-8", "replace")
    except OSError as exc:
        return {"status": "error", "kind": "dxf", "detail": str(exc)}
    upper = text.upper()
    entities = upper.count("\nENTITIES") + upper.count("\nSECTION")
    ok = "SECTION" in upper and ("ENTITIES" in upper or entities > 0)
    return {
        "status": "ok" if ok else "invalid",
        "kind": "dxf",
        "section_count": entities,
        "head": text[:160].replace("\n", " "),
        "detail": "" if ok else "no SECTION/ENTITIES markers",
    }


def pdf_report(path: str) -> dict[str, object]:
    try:
        with open(path, "rb") as fh:
            head = fh.read(8)
    except OSError as exc:
        return {"status": "error", "kind": "pdf", "detail": str(exc)}
    ok = head.startswith(b"%PDF")
    return {"status": "ok" if ok else "invalid", "kind": "pdf", "header": head.decode("latin1")}


def json_report(path: str) -> dict[str, object]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = json.load(fh)
        return {"status": "ok", "kind": "json", "type": type(data).__name__}
    except Exception as exc:
        return {"status": "invalid", "kind": "json", "detail": str(exc)}


def csv_report(path: str) -> dict[str, object]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            sample = fh.read(200_000)
        rows = list(csv.reader(io.StringIO(sample)))
        nonempty = [r for r in rows if any(c.strip() for c in r)]
        if not nonempty:
            return {"status": "empty", "kind": "csv"}
        return {
            "status": "ok",
            "kind": "csv",
            "rows_seen": len(nonempty),
            "columns": len(nonempty[0]),
            "header": nonempty[0][:12],
        }
    except Exception as exc:
        return {"status": "invalid", "kind": "csv", "detail": str(exc)}


def py_report(path: str) -> dict[str, object]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        compile(source, path, "exec")
        return {"status": "ok", "kind": "python", "chars": len(source)}
    except SyntaxError as exc:
        return {"status": "invalid", "kind": "python", "detail": f"{exc.msg} at line {exc.lineno}"}
    except OSError as exc:
        return {"status": "error", "kind": "python", "detail": str(exc)}


def file_report(path: str, required_names: list[str] | None = None) -> dict[str, object]:
    try:
        st = os.stat(path)
    except OSError:
        return {"status": "missing", "kind": "file", "detail": "path does not exist"}
    if not os.path.isfile(path):
        return {"status": "invalid", "kind": "file", "detail": "not a regular file"}
    size = st.st_size
    ext = os.path.splitext(path)[1].lower()
    if size == 0:
        return {"status": "empty", "kind": ext.lstrip("."), "size": 0}
    if ext in (".zip", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"):
        report = zip_report(path, required_names)
    elif ext == ".ifc":
        report = ifc_report(path)
    elif ext == ".dxf":
        report = dxf_report(path)
    elif ext == ".pdf":
        report = pdf_report(path)
    elif ext == ".json":
        report = json_report(path)
    elif ext in (".csv", ".tsv"):
        report = csv_report(path)
    elif ext == ".py":
        report = py_report(path)
    else:
        report = text_report(path, size)
    report["size"] = size
    report["path"] = path
    return report


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: check_task.py <workdir> <deliverables.json> [scratch]", file=sys.stderr)
        return 2
    workdir = os.path.abspath(sys.argv[1])
    with open(sys.argv[2], "r", encoding="utf-8") as fh:
        deliverables = json.load(fh)
    baseline: dict[str, dict[str, object]] = {}
    if len(sys.argv) > 3:
        inventory_path = os.path.join(os.path.abspath(sys.argv[3]), "inventory.json")
        try:
            with open(inventory_path, "r", encoding="utf-8") as fh:
                inventory = json.load(fh)
            for item in inventory.get("files", []) or []:
                key = str(item.get("path", "")).replace("\\", "/").lstrip("./")
                if key:
                    baseline[key] = item
        except (OSError, ValueError):
            pass
    reports = []
    for item in deliverables:
        path = norm(workdir, str(item.get("path", "")))
        kind = item.get("kind", "file")
        if not path:
            continue
        if os.path.isdir(path) or kind == "dir":
            report = dir_report(
                path, baseline, bool(item.get("changed_only"))
            ) if os.path.isdir(path) else {
                "status": "missing",
                "kind": "dir",
                "detail": "directory does not exist",
            }
        else:
            members = item.get("members") if isinstance(item, dict) else None
            names = [
                str(m.get("name"))
                for m in (members or [])
                if isinstance(m, dict) and m.get("name")
            ]
            report = file_report(path, names)
        report["path"] = path
        report["requested"] = item.get("path")
        report["expected_kind"] = kind
        reports.append(report)
    summary = {
        "workdir": workdir,
        "deliverables": reports,
        "ok": sum(1 for r in reports if r.get("status") == "ok"),
        "missing": sum(1 for r in reports if r.get("status") == "missing"),
        "empty": sum(1 for r in reports if r.get("status") == "empty"),
        "invalid": sum(1 for r in reports if r.get("status") in ("invalid", "error")),
        "new_or_changed": sum(int(r.get("new_or_changed", 0)) for r in reports),
    }
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
