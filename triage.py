"""Host-side triage: deliverable extraction, brief building, and prompts.

This module runs in the harness (serve) container. It never reads the dev-set
graders or the entry's own artifacts; it only uses the task instruction and the
inventory produced inside the task container.
"""

from __future__ import annotations

import os
import re
from typing import Any

ABS_RE = re.compile(
    r"(?<![\w/.-])(/(?:app|filesystem|tmp|home|root|workspace|mnt|opt|data)/[A-Za-z0-9._/\-]+)"
)
REL_RE = re.compile(
    r"(?<![\w/.-])((?:\./)?(?:output|outputs|submission|submissions|deliverables|out|result|results)/[A-Za-z0-9._/\-]+)"
)
QUOTED_FILE_RE = re.compile(
    r"[`'\"]([^`'\"\n]{1,220}\.(?:py|md|docx|xlsx|pptx|pdf|csv|json|zip|ifc|dxf|dwg|txt|yaml|yml|html|xml))[`'\"]",
    re.I,
)
BARE_FILE_RE = re.compile(
    r"(?<![\w/.-])([A-Za-z0-9][A-Za-z0-9._\-]{0,140}\.(?:py|md|docx|xlsx|pptx|pdf|csv|json|zip|ifc|dxf|dwg|txt|yaml|yml|html|xml))",
    re.I,
)
DELIVERABLE_WORDS = re.compile(
    r"\b(deliver|deliverable|output|save|write|submit|produce|create|place|file|upload|send|return|package)\b",
    re.I,
)
STRONG_VERBS = re.compile(
    r"\b(update|modify|revise|edit|fill|complete|append|replace|correct|incorporate|redline)\b",
    re.I,
)
NAMED_RE = re.compile(
    r"\b(named|as a single|file named|document named|return .{0,80} as|"
    r"submit .{0,80} as|deliver .{0,80} as|write .{0,80} to)\b",
    re.I,
)
ZIP_ROOT_RE = re.compile(
    r"(?is)(?:containing|contains|with exactly|at the archive root|"
    r"files? at the (?:archive |zip )?root)"
)
OUTPUT_WORDS = ("deliver", "output", "expected", "submit", "produce", "result")
INPUT_WORDS = (
    "input",
    "workspace",
    "provided",
    "source",
    "background",
    "situation",
    "constraint",
    "verification",
    "reference",
)
SKIP_PREFIXES = (
    "/usr/",
    "/bin/",
    "/sbin/",
    "/etc/",
    "/lib/",
    "/lib64/",
    "/proc/",
    "/sys/",
    "/dev/",
    "/var/lib/",
    "/var/cache/",
    "/opt/harness/",
    "/opt/python/",
    "/node_modules/",
)
SKIP_PARTS = ("site-packages", "node_modules", "/.git/", "/__pycache__/", "/.venv/")
FORMAT_EXT = {
    ".md",
    ".txt",
    ".docx",
    ".xlsx",
    ".pptx",
    ".pdf",
    ".csv",
    ".json",
    ".zip",
    ".ifc",
    ".dxf",
    ".dwg",
    ".py",
    ".yaml",
    ".yml",
    ".html",
    ".xml",
}


def _under_output(rel: str) -> bool:
    return any(
        part
        in (
            "output",
            "outputs",
            "submission",
            "submissions",
            "deliverables",
            "out",
            "result",
            "results",
        )
        for part in rel.replace("\\", "/").split("/")[:-1]
    )


def _zip_member_names(instruction: str) -> set[str]:
    """Returns filenames listed after a 'zip containing ... at the root' phrase."""
    match = ZIP_ROOT_RE.search(instruction)
    if not match:
        return set()
    tail = instruction[match.end() :]
    kept = []
    for line in tail.splitlines()[:80]:
        if line.lstrip().startswith("#"):
            break
        kept.append(line)
    text = "\n".join(kept)[:8000]
    names = set()
    for raw in QUOTED_FILE_RE.findall(text) + BARE_FILE_RE.findall(text):
        names.add(os.path.basename(_clean(raw)).lower())
    return names


def _clause_for(line: str, match: str) -> str:
    """Returns the sentence or clause around `match` on a long instruction line."""
    for clause in re.split(r"(?<=[.;,])\s+", line):
        if match in clause:
            return clause
    return line


def _clean(raw: str) -> str:
    value = raw.strip().strip("`'\"<>[]()")
    value = value.rstrip(".,;:!?")
    value = value.replace("\\", "/")
    if value.startswith("file://"):
        value = value[7:]
    return value


def _skip(value: str) -> bool:
    if not value:
        return True
    low = value.lower()
    if low.startswith(("http://", "https://", "mailto:")):
        return True
    if any(low.startswith(p) for p in SKIP_PREFIXES):
        return True
    if any(p in low for p in SKIP_PARTS):
        return True
    return False


def _norm(workdir: str, value: str) -> str:
    if os.path.isabs(value):
        return os.path.normpath(value)
    return os.path.normpath(os.path.join(workdir, value))


def _is_dir_candidate(raw: str, path: str, dirs: set[str]) -> bool:
    return raw.rstrip().endswith("/") or os.path.normpath(path) in dirs


def _inventory_index(
    inventory: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], set[str], set[str]]:
    by_rel: dict[str, dict[str, Any]] = {}
    by_lower: dict[str, dict[str, Any]] = {}
    basenames: set[str] = set()
    dirs: set[str] = set()
    for item in inventory.get("files", []) or []:
        rel = str(item.get("path", "")).replace("\\", "/").lstrip("./")
        if not rel:
            continue
        by_rel[rel] = item
        by_lower[rel.lower()] = item
        basenames.add(os.path.basename(rel).lower())
        parent = os.path.dirname(rel)
        while parent and parent != ".":
            dirs.add(parent)
            parent = os.path.dirname(parent)
    for item in inventory.get("output_dirs", []) or []:
        p = str(item.get("path", "")).replace("\\", "/").lstrip("./")
        if p:
            dirs.add(p)
    return by_rel, by_lower, basenames, dirs


def _lookup(
    workdir: str,
    path: str,
    by_rel: dict[str, dict[str, Any]],
    by_lower: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    rel = os.path.relpath(path, workdir).replace("\\", "/")
    if rel in by_rel:
        return by_rel[rel]
    if rel.lower() in by_lower:
        return by_lower[rel.lower()]
    base = os.path.basename(rel).lower()
    for key, item in by_rel.items():
        if os.path.basename(key).lower() == base:
            return item
    return None


def extract_deliverables(
    instruction: str, inventory: dict[str, Any], workdir: str
) -> tuple[list[dict[str, Any]], bool]:
    """Extracts candidate deliverable paths from the instruction and inventory.

    Returns a list of ``{path, kind, format, exists, head, evidence}`` dicts and
    a flag that is true when the instruction did not yield any candidate.
    """
    by_rel, by_lower, basenames, dirs = _inventory_index(inventory)
    known_inputs = {
        rel.lower() for rel in by_rel if not _under_output(rel)
    }
    candidates: dict[str, dict[str, Any]] = {}

    def section_weight(heading: str) -> int:
        low = heading.lower()
        if any(word in low for word in OUTPUT_WORDS):
            return 5
        if any(word in low for word in INPUT_WORDS):
            return -3
        return 0

    def add(
        raw: str,
        evidence: str,
        score: int,
        strong: bool = False,
        edit: bool = False,
    ) -> None:
        value = _clean(raw)
        if _skip(value):
            return
        path = _norm(workdir, value)
        if path.startswith("/tmp/ple-forge") or "/tmp/ple-forge/" in path:
            return
        key = os.path.normcase(path)
        rel = os.path.relpath(path, workdir).replace("\\", "/")
        item = by_rel.get(rel) or by_lower.get(rel.lower())
        exists = item is not None
        if not exists:
            base = os.path.basename(path).lower()
            exists = base in basenames
        kind = "dir" if _is_dir_candidate(value, path, dirs) else "file"
        fmt = "directory" if kind == "dir" else (os.path.splitext(path)[1].lower() or "unknown")
        record = candidates.get(key)
        if record is None:
            candidates[key] = {
                "path": path,
                "kind": kind,
                "format": fmt,
                "exists": exists,
                "head": str(item.get("head", ""))[:240] if item else "",
                "evidence": evidence,
                "score": score,
                "strong": strong,
                "edit": edit,
            }
        else:
            record["score"] += score
            record["strong"] = bool(record.get("strong")) or strong
            record["edit"] = bool(record.get("edit")) or edit
            if evidence not in record["evidence"]:
                record["evidence"] = (record["evidence"] + " | " + evidence)[:300]
            if exists:
                record["exists"] = True

    heading = ""
    for line in instruction.splitlines():
        if line.lstrip().startswith("#"):
            heading = line.lstrip("#").strip()
        weight = section_weight(heading)
        named = bool(NAMED_RE.search(line))
        edit = bool(STRONG_VERBS.search(line))
        strong = edit or named
        for match in ABS_RE.findall(line):
            add(
                match,
                f"absolute path under '{heading or 'top'}'",
                3 + weight,
                strong,
                edit,
            )
        for match in REL_RE.findall(line):
            add(
                match,
                f"output/submission path under '{heading or 'top'}'",
                3 + weight,
                strong,
                edit,
            )
        if DELIVERABLE_WORDS.search(line) or weight >= 5 or named:
            for match in QUOTED_FILE_RE.findall(line):
                clause = _clause_for(line, match)
                local_named = bool(NAMED_RE.search(clause))
                local_edit = bool(STRONG_VERBS.search(clause))
                local_deliver = bool(DELIVERABLE_WORDS.search(clause))
                add(
                    match,
                    f"quoted filename under '{heading or 'top'}'",
                    (3 if local_named else 2 if local_deliver else 1) + weight,
                    local_named or local_edit,
                    local_edit,
                )
            for match in BARE_FILE_RE.findall(line):
                clause = _clause_for(line, match)
                local_named = bool(NAMED_RE.search(clause))
                local_edit = bool(STRONG_VERBS.search(clause))
                local_deliver = bool(DELIVERABLE_WORDS.search(clause))
                add(
                    match,
                    f"filename under '{heading or 'top'}'",
                    (2 if local_named else 1) + weight,
                    local_named or local_edit,
                    local_edit,
                )

    if not candidates:
        for item in inventory.get("output_dirs", []) or []:
            raw = str(item.get("path", ""))
            if raw:
                add(raw, "existing output directory (no explicit path found)", 2)

    ranked = sorted(
        candidates.values(),
        key=lambda c: (-int(c["score"]), 0 if c["kind"] == "dir" else 1, c["path"]),
    )
    work_base = os.path.basename(os.path.normpath(workdir))
    result = []
    for item in ranked:
        rel = os.path.relpath(item["path"], workdir).replace("\\", "/")
        under_output = _under_output(rel)
        # A file that is present in the workspace outside an output directory is
        # an input, not a deliverable, unless the instruction edits it.
        if not under_output and rel.lower() in known_inputs and not item.get("edit"):
            continue
        # A bare alias of the project root (for example /filesystem/<project>)
        # is the workspace, not a deliverable.
        if (
            item["kind"] != "dir"
            and os.path.basename(os.path.normpath(item["path"])) == work_base
            and os.path.normpath(item["path"]) != os.path.normpath(workdir)
        ):
            continue
        # Existing files outside an output directory are inputs, not
        # deliverables, unless the instruction uses an edit verb.
        if item["exists"] and not under_output and not item.get("edit"):
            continue
        named_new = (
            not item["exists"]
            and item.get("strong")
            and item["format"] in FORMAT_EXT
        )
        if item["score"] >= 3 or under_output or item["kind"] == "dir" or named_new:
            result.append(item)
        if len(result) >= 24:
            break

    # Merge the same deliverable seen through /filesystem and a relative path:
    # keep the canonical /filesystem spelling when both are present.
    by_suffix: dict[str, dict[str, Any]] = {}
    merged: list[dict[str, Any]] = []
    for item in result:
        parts = item["path"].replace("\\", "/").rstrip("/").split("/")
        suffix = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
        old = by_suffix.get(suffix)
        if old is None:
            by_suffix[suffix] = item
            merged.append(item)
            continue
        old["score"] += item["score"]
        old["exists"] = bool(old.get("exists")) or bool(item.get("exists"))
        old["edit"] = bool(old.get("edit")) or bool(item.get("edit"))
        if item["path"].startswith("/filesystem"):
            old["path"] = item["path"]
        if item["evidence"] not in old["evidence"]:
            old["evidence"] = (old["evidence"] + " | " + item["evidence"])[:400]
    result = merged

    # If the instruction says a zip holds the listed files at its root, treat
    # those files as archive members, not as separate top-level deliverables.
    zip_items = [x for x in result if x.get("format") == ".zip"]
    if len(zip_items) == 1 and ZIP_ROOT_RE.search(instruction):
        archive = zip_items[0]
        member_names = _zip_member_names(instruction)
        members = []
        kept = []
        for item in result:
            if item is archive:
                kept.append(item)
                continue
            rel = os.path.relpath(item["path"], workdir).replace("\\", "/")
            under_output = _under_output(rel)
            member_name = os.path.basename(item["path"]).lower()
            if (
                not under_output
                and item.get("format") in FORMAT_EXT
                and item.get("format") != ".zip"
                and (not item.get("exists") or item.get("edit"))
                and (not member_names or member_name in member_names)
            ):
                members.append(item)
            else:
                kept.append(item)
        if members:
            archive["members"] = [
                {"name": os.path.basename(m["path"]), "format": m["format"]}
                for m in members
            ]
            result = kept

    unscoped = not bool(result)
    if not result:
        # The grader may read a whole directory rather than a named file. Use an
        # existing output directory when the workspace has one; otherwise watch
        # the workspace for any new or changed file.
        for output_dir in inventory.get("output_dirs", []) or []:
            raw = str(output_dir.get("path", ""))
            if raw:
                path = _norm(workdir, raw)
                result.append(
                    {
                        "path": path,
                        "kind": "dir",
                        "format": "directory",
                        "exists": True,
                        "head": "",
                        "evidence": "fallback: existing output directory (grader reads the directory)",
                        "score": 1,
                        "strong": False,
                        "edit": False,
                    }
                )
        if not result:
            result.append(
                {
                    "path": workdir,
                    "kind": "dir",
                    "format": "directory",
                    "exists": True,
                    "head": "",
                    "evidence": "fallback: task workspace (grader reads new/changed files)",
                    "score": 1,
                    "strong": False,
                    "edit": False,
                    "changed_only": True,
                }
            )
    return result, unscoped


def _fmt_size(size: int) -> str:
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.1f} kB"
    return f"{size} B"


def build_brief(
    instruction: str,
    inventory: dict[str, Any],
    deliverables: list[dict[str, Any]],
    unscoped: bool,
    scratch: str,
    time_left: float | None,
    mcp: list[dict[str, Any]] | None = None,
) -> str:
    by_kind = inventory.get("by_kind", {}) or {}
    by_ext = inventory.get("by_ext", {}) or {}
    tools = inventory.get("tools", {}) or {}
    commands = tools.get("commands", {}) or {}
    modules = tools.get("modules", {}) or {}
    dirs = inventory.get("output_dirs", []) or []
    key_files = inventory.get("key_files", []) or []
    lines: list[str] = [
        "# PLE task brief (auto-generated)",
        "",
        f"Scratch directory: `{scratch}`. Write `plan.md`, `notes.md`, and",
        "`calc_log.csv` there. Do not put scratch files in the deliverables.",
        "",
        "## 1. Instruction (verbatim)",
        "",
        instruction.strip(),
        "",
        "## 2. Deliverable contract (candidates — confirm against the instruction)",
        "",
    ]
    if unscoped:
        lines += [
            "The extractor found no explicit deliverable path. Re-read the instruction and",
            "write the exact paths, filenames, and formats into `plan.md` before working.",
            "",
        ]
    else:
        lines += [
            "These paths were extracted from the instruction. They are candidates, not",
            "authority: confirm or correct them in `plan.md`. If a required deliverable is",
            "missing from this table, add it and create it.",
            "",
            "| # | Path | Kind | Format | Exists now | Evidence |",
            "|---|---|---|---|---|---|",
        ]
        for i, item in enumerate(deliverables, 1):
            members = item.get("members") or []
            member_note = ""
            if members:
                member_note = " <br>members: " + ", ".join(
                    f"`{m.get('name')}`" for m in members[:12]
                )
            lines.append(
                f"| {i} | `{item['path']}` | {item['kind']} | {item['format']} | "
                f"{'yes' if item['exists'] else 'no'} | {item['evidence'][:160]}"
                f"{member_note} |"
            )
        lines.append("")
    lines += [
        "## 3. Workspace inventory",
        "",
        f"- Workdir: `{inventory.get('workdir', '')}`",
        f"- Files: {inventory.get('file_count', 0)}; directories: {inventory.get('dir_count', 0)}",
        f"- By kind: {', '.join(f'{k}={v}' for k, v in sorted(by_kind.items()))}",
        f"- By extension: {', '.join(f'{k}={v}' for k, v in list(by_ext.items())[:16])}",
        "",
    ]
    if dirs:
        lines.append("Existing output directories:")
        for d in dirs[:12]:
            sample = ", ".join(f["name"] for f in (d.get("files", []) or [])[:8])
            lines.append(
                f"- `{d.get('path')}` — {d.get('file_count', 0)} file(s), "
                f"{_fmt_size(int(d.get('total_size', 0)))}"
                + (f"; e.g. {sample}" if sample else "")
            )
        lines.append("")
    lines.append("Key source files (largest / most task-relevant):")
    lines.append("")
    lines.append("| Path | Size | Kind | First line |")
    lines.append("|---|---|---|---|")
    for item in key_files[:40]:
        head_lines = str(item.get("head", "")).splitlines()
        head = (head_lines[0] if head_lines else "")[:140].replace("|", "\\|")
        lines.append(
            f"| `{item.get('path')}` | {_fmt_size(int(item.get('size', 0)))} | "
            f"{item.get('kind')} | {head} |"
        )
    lines.append("")
    lines.append("Tools available in the task container:")
    lines.append("- Commands: " + (", ".join(sorted(commands)) or "none detected"))
    lines.append(
        "- Python modules: "
        + (", ".join(sorted(k for k, v in modules.items() if v)) or "none detected")
    )
    lines.append("")
    if mcp:
        lines += ["## 4. MCP servers (task applications)", ""]
        for server in mcp:
            name = server.get("name", "mcp")
            if server.get("error"):
                lines.append(f"- **{name}**: unavailable — {server['error']}")
                continue
            tools = server.get("tools", []) or []
            key = [
                t
                for t in tools
                if re.search(
                    r"document|file|upload|create|write|read|search|case|ticket|task|"
                    r"email|message|calendar|spreadsheet|sheet|slide|folder|project|"
                    r"comment|status|close|update|attach",
                    str(t.get("name", "")) + " " + str(t.get("description", "")),
                    re.I,
                )
            ][:14]
            lines.append(
                f"- **{name}** — {server.get('tool_count', len(tools))} tools. "
                f"Full catalog: `{scratch}/mcp_catalog.json`."
            )
            for tool in key:
                desc = str(tool.get("description", "")).splitlines()[0][:140]
                lines.append(f"  - `{tool.get('name')}` — {desc}")
        lines.append("")
        lines.append(
            "If the task asks you to file a document, update a case, send a message, "
            "or close a record, use these MCP tools. A local file alone may not satisfy "
            "the deliverable."
        )
        lines.append("")
    lines += [
        "## 5. Engineering guardrails",
        "",
        "- Read the whole instruction before acting. Identify every deliverable path,",
        "  filename, format, and required section.",
        "- Drawings and scanned pages are inputs, not decoration. Open PNG/JPEG/PDF",
        "  pages with the read tool and transcribe dimensions, callouts, schedules, and",
        "  elevations. Do not guess what a drawing shows.",
        "- Work in the project's units. State assumptions; convert consistently; keep",
        "  dimensions and units explicit in `calc_log.csv`. If the task states a",
        "  mixed convention (for example millimetre project units but metre placement",
        "  translations), apply it exactly and check every placement and property.",
        "- Compute with code, not by hand. Independently re-derive key numbers and check",
        "  sums, totals, boundary conditions, and sign conventions.",
        "- Geometry/CAD/BIM: use the project coordinate system; check clashes,",
        "  containment, clearances, connectivity, and that the file opens.",
        "- Code: run it, check the entry point and output schema, and make it deterministic.",
        "- Archives: include every required member at the archive root; create the",
        "  archive early and replace member contents in place; list the zip contents",
        "  before finishing.",
        "- Documents: include every requested section, table, and signature block; use",
        "  the requested format.",
        "- Create a skeleton at every required deliverable path early. Never leave a",
        "  required path missing.",
        "",
        "## 6. Time budget",
        "",
    ]
    if time_left is None:
        lines.append("- No task time limit reported.")
    else:
        lines.append(f"- About {int(time_left // 60)} minutes remain for the whole task.")
    lines.append("- Leave enough time to open every deliverable and verify it.")
    lines.append("")
    return "\n".join(lines)


def summarize_check(check: dict[str, Any]) -> str:
    rows = []
    for item in check.get("deliverables", []) or []:
        status = str(item.get("status", "unknown"))
        size = item.get("size")
        detail = str(item.get("detail", ""))[:160]
        extra = ""
        if item.get("kind") == "archive" and item.get("entry_count") is not None:
            extra = f"{item['entry_count']} entries"
            missing = item.get("missing_members") or []
            if missing:
                extra += "; missing " + ", ".join(map(str, missing[:8]))
        elif item.get("kind") == "ifc":
            extra = f"{item.get('entity_count', 0)} entities"
        elif item.get("kind") == "dir":
            extra = (
                f"{item.get('file_count', 0)} files"
                + (
                    f", {item.get('new_or_changed', 0)} new/changed"
                    if item.get("changed_only")
                    else ""
                )
            )
        elif item.get("chars") is not None:
            extra = f"{item.get('chars')} chars"
        rows.append(
            f"- `{item.get('path')}`: **{status}**"
            + (f" ({_fmt_size(int(size))})" if isinstance(size, int) else "")
            + (f" — {extra}" if extra else "")
            + (f" — {detail}" if detail else "")
        )
    if not rows:
        rows = ["- No deliverable paths were extracted; inspect the instruction and workspace."]
    return "\n".join(rows)


def build_audit_prompt(
    instruction: str,
    scratch: str,
    final_message: str,
    check: dict[str, Any],
) -> str:
    return (
        "## Task instruction\n\n"
        + instruction.strip()
        + "\n\n## Harness brief\n\nRead `"
        + scratch
        + "/BRIEF.md`, `"
        + scratch
        + "/plan.md`, and `"
        + scratch
        + "/notes.md`.\n\n"
        + "## The engineer's final summary\n\n"
        + (final_message.strip() or "(none)")
        + "\n\n## Deterministic deliverable check\n\n"
        + summarize_check(check)
        + "\n\nAudit the work as an independent senior engineer. Do not modify any file. "
        "Open every deliverable and the source data. Re-read the governing criteria, "
        "specification clauses, and schedules yourself; do not rely on the engineer's "
        "summary for the method, the governing document, or a superseded/cancelled "
        "document. Recompute the key numbers with Python in /tmp only. Check units, "
        "dimensions, sums, boundary conditions, sign conventions, and the exact "
        "paths/formats the task asks for. For archives, list and open every required "
        "file. For code, run it in a temporary directory. Report only material "
        "gaps, as a numbered list with severity (BLOCKER/MAJOR/MINOR), the exact file or "
        "number, and the correction needed. If the summary is a progress note, stops "
        "mid-sentence, or does not name the deliverables, report that as a BLOCKER too. "
        "If there are no material gaps, reply with the single word PASS."
    )


def build_fix_prompt(
    instruction: str,
    scratch: str,
    final_message: str,
    verdict: str,
    check: dict[str, Any],
) -> str:
    return (
        "## Task instruction\n\n"
        + instruction.strip()
        + "\n\n## Harness brief\n\nRead `"
        + scratch
        + "/BRIEF.md` and `"
        + scratch
        + "/plan.md`.\n\n"
        + "## The engineer's current summary\n\n"
        + (final_message.strip() or "(none)")
        + "\n\n## Independent reviewer's findings\n\n"
        + (verdict.strip() or "(none)")
        + "\n\n## Deterministic deliverable check\n\n"
        + summarize_check(check)
        + "\n\nFix only the material gaps above. Preserve correct work; do not rewrite "
        "files that already pass. Re-open every deliverable after editing, re-run the "
        "relevant calculation, and verify the exact path/format. When done, reply with "
        "an updated concise summary of each deliverable, its exact path, and the key "
        "results."
    )


def build_closer_prompt(
    instruction: str,
    scratch: str,
    check: dict[str, Any],
    time_left: float | None,
) -> str:
    minutes = "" if time_left is None else f" About {int(time_left // 60)} minutes remain."
    return (
        "## Task instruction\n\n"
        + instruction.strip()
        + "\n\n"
        + "Time is nearly up."
        + minutes
        + " The deterministic check below shows missing, empty, or invalid deliverables. "
        "Write the best possible version of each one now, using the data already in the "
        "workspace. Do not spend time on further analysis or exploration. Create every "
        "missing path before editing content. Reply with one short paragraph naming each "
        "file and its status.\n\n"
        + "## Deterministic deliverable check\n\n"
        + summarize_check(check)
    )


def is_pass(verdict: str) -> bool:
    text = re.sub(r"[*_`.#\s]+", " ", verdict or "").strip().lower()
    if not text:
        return True
    if text in ("pass", "passed", "no gaps", "no issues", "no material gaps"):
        return True
    return text.startswith("pass") and len(text) < 40


def build_final_message(
    final_message: str,
    check: dict[str, Any],
    deliverables: list[dict[str, Any]],
) -> str:
    body = (final_message or "").strip()
    if not body:
        body = "Work completed. The deterministic deliverable check is below."
    lines = [body, "", "## Delivered files (deterministic check)", ""]
    for item in check.get("deliverables", []) or []:
        status = str(item.get("status", "unknown"))
        size = item.get("size")
        note = []
        if item.get("kind") == "archive" and item.get("entry_count") is not None:
            note.append(f"{item['entry_count']} entries")
            missing = item.get("missing_members") or []
            if missing:
                note.append("missing " + ", ".join(map(str, missing[:8])))
        if item.get("kind") == "ifc":
            note.append(f"{item.get('entity_count', 0)} entities")
        if item.get("kind") == "dir":
            note.append(f"{item.get('file_count', 0)} files")
            if item.get("changed_only"):
                note.append(f"{item.get('new_or_changed', 0)} new/changed")
        if item.get("chars") is not None:
            note.append(f"{item.get('chars')} chars")
        if item.get("detail"):
            note.append(str(item["detail"])[:120])
        lines.append(
            f"- `{item.get('path')}` — **{status}**"
            + (f", {_fmt_size(int(size))}" if isinstance(size, int) else "")
            + ((" — " + "; ".join(note)) if note else "")
        )
    if not check.get("deliverables"):
        lines.append("- No deliverable paths were extracted; see the task instruction.")
    return "\n".join(lines)
