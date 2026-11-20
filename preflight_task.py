#!/usr/bin/env python3
"""Deterministic workspace inventory for a PLE task.

Runs inside the task container with only the Python standard library. Writes a
full inventory to <scratch>/inventory.json and prints a compact summary to
stdout so the harness can build a brief without blowing the 100 KB exec limit.

Usage: python3 preflight_task.py <workdir> [scratch]
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import zipfile

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "site-packages",
    "dist",
    "build",
    ".cache",
    ".npm",
    ".local",
}
TEXT_EXT = {
    ".md",
    ".txt",
    ".rst",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".py",
    ".js",
    ".ts",
    ".html",
    ".xml",
    ".sql",
    ".sh",
}
ZIP_EXT = {".zip", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}
KEY_WORDS = (
    "readme",
    "instruction",
    "brief",
    "scope",
    "spec",
    "criteria",
    "schedule",
    "drawing",
    "plan",
    "basis",
    "task",
    "requirement",
    "notes",
    "comment",
    "rfi",
    "submittal",
)
OUTPUT_NAMES = {"output", "outputs", "submission", "submissions", "deliverables", "out", "result", "results"}
MAX_FILES = 2500
MAX_KEY = 80
MAX_TOP = 120
MAX_ZIP = 40


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in ZIP_EXT:
        return "archive"
    if ext == ".pdf":
        return "pdf"
    if ext in (".ifc", ".ifczip"):
        return "ifc"
    if ext == ".dxf":
        return "dxf"
    if ext == ".dwg":
        return "dwg"
    if ext in (".xlsx", ".xls", ".csv", ".tsv"):
        return "table"
    if ext in (".docx", ".doc", ".odt"):
        return "document"
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"):
        return "image"
    if ext in TEXT_EXT:
        return "text"
    return "other"


def head_text(path: str, limit: int = 400) -> str:
    try:
        with open(path, "rb") as fh:
            data = fh.read(limit)
        return data.decode("utf-8", "replace").replace("\x00", " ").strip()
    except OSError:
        return ""


def zip_entries(path: str) -> list[dict[str, object]]:
    try:
        with zipfile.ZipFile(path) as zf:
            out = []
            for info in zf.infolist()[:MAX_ZIP]:
                out.append({"name": info.filename, "size": info.file_size})
            return out
    except Exception:
        return []


def scan(root: str) -> tuple[list[dict[str, object]], int]:
    files: list[dict[str, object]] = []
    dirs = 0
    for base, names, filenames in os.walk(root, topdown=True):
        names[:] = [n for n in names if n not in SKIP_DIRS and not n.startswith(".")]
        dirs += len(names)
        rel_base = os.path.relpath(base, root)
        depth = 0 if rel_base == "." else rel_base.count(os.sep) + 1
        if depth > 5:
            names[:] = []
            continue
        for name in filenames:
            if name.startswith(".") and name not in (".env", ".gitignore"):
                continue
            path = os.path.join(base, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            rel = os.path.relpath(path, root)
            item: dict[str, object] = {
                "path": rel.replace(os.sep, "/"),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "kind": kind_of(name),
                "ext": os.path.splitext(name)[1].lower(),
            }
            if item["kind"] in ("text", "table") and st.st_size <= 200_000:
                item["head"] = head_text(path)
            elif item["kind"] in ("pdf", "ifc", "dxf", "dwg"):
                item["head"] = head_text(path, 120)
            if item["kind"] == "archive" and st.st_size <= 50_000_000:
                item["zip"] = zip_entries(path)
            files.append(item)
            if len(files) >= MAX_FILES:
                return files, dirs
    return files, dirs


def output_dirs(root: str) -> list[dict[str, object]]:
    out = []
    for base, names, filenames in os.walk(root):
        names[:] = [n for n in names if n not in SKIP_DIRS and not n.startswith(".")]
        rel = os.path.relpath(base, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > 4:
            names[:] = []
            continue
        if os.path.basename(base).lower() in OUTPUT_NAMES:
            files = []
            total = 0
            for name in filenames[:200]:
                try:
                    size = os.path.getsize(os.path.join(base, name))
                except OSError:
                    continue
                files.append({"name": name, "size": size})
                total += size
            out.append(
                {
                    "path": rel.replace(os.sep, "/"),
                    "files": files[:80],
                    "file_count": len(filenames),
                    "total_size": total,
                }
            )
    return out


def tools() -> dict[str, object]:
    commands = [
        "python3",
        "python",
        "pip",
        "pdftotext",
        "pdfinfo",
        "pdftoppm",
        "tesseract",
        "libreoffice",
        "soffice",
        "unzip",
        "zip",
        "7z",
        "git",
        "node",
        "npm",
        "jq",
        "convert",
        "magick",
        "gdalinfo",
        "ogrinfo",
        "sqlite3",
    ]
    found = {}
    for name in commands:
        path = shutil.which(name)
        if path:
            found[name] = path
    modules = {}
    for name in (
        "ifcopenshell",
        "ezdxf",
        "pandas",
        "openpyxl",
        "docx",
        "fitz",
        "pymupdf",
        "pdfplumber",
        "numpy",
        "scipy",
        "shapely",
        "trimesh",
        "PIL",
        "reportlab",
        "matplotlib",
        "xlsxwriter",
        "pypdf",
        "PyPDF2",
    ):
        try:
            __import__(name)
            modules[name] = True
        except Exception:
            modules[name] = False
    return {"commands": found, "modules": modules}


def env_info(root: str) -> dict[str, object]:
    info: dict[str, object] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    info["mem_total_kb"] = int(line.split()[1])
                    break
    except OSError:
        pass
    try:
        usage = shutil.disk_usage(root)
        info["disk_free"] = usage.free
        info["disk_total"] = usage.total
    except OSError:
        pass
    return info


def score(item: dict[str, object]) -> int:
    path = str(item["path"]).lower()
    kind = item["kind"]
    value = 0
    if any(word in path for word in KEY_WORDS):
        value += 100
    if kind in ("pdf", "ifc", "dxf", "dwg", "document", "table", "archive", "image"):
        value += 50
    if int(item["size"]) > 1_000_000:
        value += 20
    if any(part in OUTPUT_NAMES for part in path.split("/")[:-1]):
        value += 10
    if "input" in path.split("/")[:-1]:
        value += 10
    return value


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: preflight_task.py <workdir> [scratch]", file=sys.stderr)
        return 2
    root = os.path.abspath(sys.argv[1])
    scratch = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else "/tmp/ple-forge"
    os.makedirs(scratch, exist_ok=True)
    files, dir_count = scan(root)
    by_ext: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for item in files:
        by_ext[str(item["ext"])] = by_ext.get(str(item["ext"]), 0) + 1
        by_kind[str(item["kind"])] = by_kind.get(str(item["kind"]), 0) + 1
    key = sorted(files, key=score, reverse=True)[:MAX_KEY]
    top = sorted(files, key=lambda x: str(x["path"]))[:MAX_TOP]
    import time

    full = {
        "workdir": root,
        "created_at": time.time(),
        "file_count": len(files),
        "dir_count": dir_count,
        "by_ext": dict(sorted(by_ext.items(), key=lambda kv: -kv[1])[:40]),
        "by_kind": by_kind,
        "key_files": key,
        "output_dirs": output_dirs(root),
        "tools": tools(),
        "env": env_info(root),
        "files": files,
    }
    with open(os.path.join(scratch, "inventory.json"), "w", encoding="utf-8") as fh:
        json.dump(full, fh, indent=1)
    compact = {
        "workdir": root,
        "file_count": len(files),
        "dir_count": dir_count,
        "by_ext": full["by_ext"],
        "by_kind": by_kind,
        "key_files": key,
        "output_dirs": full["output_dirs"],
        "tools": full["tools"],
        "env": full["env"],
        "top_level": top,
    }
    print(json.dumps(compact, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
