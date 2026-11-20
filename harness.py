# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Triage-first Pi harness for Physical-Engineering's Last Exam.

The harness runs one headless Pi session per phase, all against the task
container through `taskbridge.Relay`:

1. A deterministic preflight inventories the workspace and extracts candidate
   deliverable paths from the instruction (no model call).
2. An executor plans, creates a skeleton at every required path early, and
   produces the deliverables.
3. An independent auditor re-opens the deliverables, recomputes key numbers,
   and returns a gap list.
4. A fixer addresses the gaps, and a deterministic checker runs again.
5. If any required path is still missing or empty, a short closer writes the
   best version it can before the deadline.

The deterministic layer is deliberately conservative: it never guesses at
engineering answers, but it does prevent the failure mode that scores zero on
an otherwise good run -- a required file that was never written.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
from typing import Any

import taskbridge
import triage

HERE = pathlib.Path(__file__).resolve().parent
# npm ci, from package-lock.json
PI = shutil.which("pi") or str(HERE / "node_modules" / ".bin" / "pi")
# Scratch directory inside the task container. It is deliberately under /tmp,
# not the workdir, so it can never leak into a directory deliverable.
SCRATCH = "/tmp/ple-forge"
# stop Pi this long before a hard session deadline (less on short tasks)
STOP_BEFORE_SEC = 90
CATALOG_TIMEOUT_SEC = 30
# Desired wall-clock budgets for the post-execution phases, in seconds.
AUDIT_SEC = 1200
FIX_SEC = 1200
CLOSE_SEC = 180
# Request features the Google Cloud route for Claude refuses. pi leaves them
# out, and the Anthropic API works without them too.
COMPAT = {
    "supportsStrictTools": False,
    "supportsMidConvoEffort": False,
    "supportsMidConvoSystemMessages": False,
    "supportsMidConvoToolChanges": False,
}

EXECUTOR = """You are an expert engineer working on a task in a Linux container with no internet access. Your tools act inside it, and bash starts in {workdir}. A deterministic brief is at {scratch}/BRIEF.md; read it before acting. The task instruction is authoritative: if the brief misreads a deliverable path or requirement, correct it in {scratch}/plan.md.

Work in this order:
1. Read the entire instruction and the files it points to.
2. Write {scratch}/plan.md with the exact deliverable paths, formats, required content, method, and verification steps. Create a skeleton at every required deliverable path early. Never leave a required path missing.
3. Execute the plan in small, verified steps. Keep {scratch}/notes.md and {scratch}/calc_log.csv current.
4. Compute with code, not by hand. Re-derive key quantitative results independently and check units, dimensions, sums, totals, and boundary conditions.
5. For geometry/CAD/BIM, check clashes, containment, clearances, connectivity, and the project coordinate system. For code, run it and check its output. For archives, list the contents. For documents, include every requested section.
6. Before finishing, open every deliverable and verify its exact path, format, and required content.
7. If a deliverable is an archive, create it with every required member at the stated root early, then replace member contents in place. If the task asks for a document in a document store or a case-tracking update, use the MCP tools.
When done, reply with a concise summary of each deliverable, its exact path, and the key results."""

AUDITOR = """You are an independent senior engineer auditing a colleague's work on a task in a Linux container. You may inspect files and run read-only commands; do not modify any file. The task instruction and the colleague's summary are below. The harness brief is at {scratch}/BRIEF.md.

Audit the deliverables against the instruction: exact paths and formats, every required part, and the key numbers. Recompute important values with Python in /tmp only, using the source data in the workspace. Check units, dimensions, sums, boundary conditions, and sign conventions. For archives, list and open every required file. For code, run it in a temporary directory and check its output. For geometry/CAD/BIM, open the file and check the required entities, properties, clashes, containment, and clearances.

Report only material gaps as a numbered list, each with severity (BLOCKER/MAJOR/MINOR), the exact file or number, and the correction needed. If there are no material gaps, reply with the single word PASS."""

FIXER = """You are an expert engineer fixing a colleague's task in a Linux container. The harness brief is at {scratch}/BRIEF.md; the task instruction, the current summary, and an independent reviewer's findings are below.

Fix only the material gaps. Preserve correct work; do not rewrite files that already pass. Re-open every deliverable after editing and re-run the relevant calculation. Create any missing deliverable path. When done, reply with an updated concise summary of each deliverable, its exact path, and the key results."""

CLOSER = """You are an expert engineer working against a hard deadline in a Linux container. The task instruction and a deterministic check are below. The check shows missing, empty, or invalid deliverables. Write the best possible version of each one now using the data already in the workspace. Do not analyze further or explore. Create every missing path first, then fill it with the best content you can. Reply with one short paragraph naming each file and its status."""


def model_limits() -> dict[str, Any]:
  """Returns Pi's fallback context and output limits for the declared model."""
  name = os.environ.get("MODEL_NAME", "").lower()
  if "claude" in name:
    return {"input": ["text"], "contextWindow": 1_000_000, "maxTokens": 32000}
  if "gemini" in name:
    return {"input": ["text"], "contextWindow": 1_048_576, "maxTokens": 32000}
  if "glm" in name:
    return {"input": ["text"], "contextWindow": 1_048_576, "maxTokens": 32000}
  if "gemma" in name:
    return {"input": ["text"], "contextWindow": 262_144, "maxTokens": 16000}
  if "llama" in name:
    return {"input": ["text"], "contextWindow": 524_288, "maxTokens": 16000}
  if "gpt-oss" in name:
    return {"input": ["text"], "contextWindow": 131_072, "maxTokens": 16000}
  return {"input": ["text"], "contextWindow": 128_000, "maxTokens": 16000}


def default_effort() -> str:
  """Returns the model's highest usable thinking level."""
  name = os.environ.get("MODEL_NAME", "").lower()
  return "max" if ("claude" in name or "glm" in name) else "high"


def provider() -> tuple[str, dict[str, Any]]:
  """Returns the Pi provider name and its `models.json` entry.

  Claude uses the native Anthropic Messages API so Pi's catalog supplies its
  limits and signed thinking. Every other model uses the OpenAI-compatible
  endpoint, which the competition gateway provides for all eight models.
  """
  model = os.environ.get("MODEL_NAME", "")
  if os.environ.get("ANTHROPIC_BASE_URL") and "claude" in model.lower():
    return "anthropic", {
        "baseUrl": os.environ["ANTHROPIC_BASE_URL"],
        "api": "anthropic-messages",
        "apiKey": "$ANTHROPIC_API_KEY",
        "compat": COMPAT,
    }
  return "model", {
      "baseUrl": os.environ["MODEL_BASE_URL"],
      "api": "openai-completions",
      "apiKey": "$MODEL_API_KEY",
  }


def in_catalog(name: str, model: str, env: dict[str, str]) -> bool:
  """Checks whether Pi's built-in model catalog recognizes `model`."""
  try:
    out = subprocess.run(
        [PI, "--offline", "--list-models", model],
        env=env,
        capture_output=True,
        text=True,
        timeout=CATALOG_TIMEOUT_SEC,
        check=False,
    ).stdout
  except (subprocess.TimeoutExpired, OSError):
    return False
  return any(line.split()[:2] == [name, model] for line in out.splitlines())


def configure(
    agent_dir: pathlib.Path,
    relay: taskbridge.Relay,
    session: taskbridge.Session,
    env: dict[str, str],
) -> tuple[str, str]:
  """Writes Pi's model, settings, and MCP configuration files for a task."""
  model = os.environ["MODEL_NAME"]
  name, config = provider()
  models = agent_dir / "models.json"
  models.write_text(json.dumps({"providers": {name: config}}))
  if not in_catalog(name, model, env):
    config["models"] = [{"id": model, "name": model, **model_limits()}]
    models.write_text(json.dumps({"providers": {name: config}}))
  settings = {
      "defaultProjectTrust": "never",
      "quietStartup": True,
      "cacheWarming": "off",
      "retry": {"maxRetries": 6, "maxAgentDelayMs": 60000},
  }
  (agent_dir / "settings.json").write_text(json.dumps(settings))
  servers = {
      s["name"]: {"url": relay.mcp_url(s["name"]), "timeout": 300}
      for s in session.mcp_servers
  }
  (agent_dir / "mcp.json").write_text(json.dumps({"mcpServers": servers}))
  return name, model


class Run:
  """Tracks JSON stream events from a single Pi subprocess run."""

  def __init__(
      self, session: taskbridge.Session, model: str, publish: bool = False
  ):
    self.session = session
    self.model = model
    self.publish = publish
    self.replies = 0
    self.final = ""

  async def on_event(self, event: dict[str, Any]) -> None:
    """Processes a parsed JSON event from Pi, updating final message and usage."""
    kind, message = event.get("type"), event.get("message") or {}
    if kind == "message_end" and message.get("role") == "assistant":
      self.replies += 1
      text = "\n".join(
          b.get("text", "")
          for b in message.get("content") or []
          if b.get("type") == "text"
      )
      if text.strip():
        self.final = text.strip()
        if self.publish:
          self.session.final_message = self.final
      if message.get("stopReason") == "error":
        await self.session.log(
            f"pi: model error: {message.get('errorMessage')}"
        )
      # input_tokens counts cached prompt tokens too
      u = message.get("usage") or {}
      await self.session.usage(
          self.model,
          input_tokens=u.get("input", 0)
          + u.get("cacheRead", 0)
          + u.get("cacheWrite", 0),
          output_tokens=u.get("output", 0),
          cache_read_tokens=u.get("cacheRead", 0),
      )
    elif kind == "tool_execution_start":
      await self.session.log(
          f"pi: {event.get('toolName')} {json.dumps(event.get('args'))[:300]}"
      )
    elif kind in ("auto_retry_start", "compaction_start"):
      await self.session.log(f"pi: {kind} {json.dumps(event)[:300]}")

  async def on_line(self, line: bytes) -> None:
    """Parses a raw stdout line from Pi as JSON and forwards it to `on_event`."""
    try:
      event = json.loads(line)
    except ValueError:
      return
    if isinstance(event, dict):
      await self.on_event(event)


def parse_json(text: str) -> dict[str, Any] | None:
  """Extracts the first complete JSON object from a command's output."""
  start = text.find("{")
  end = text.rfind("}")
  if start < 0 or end <= start:
    return None
  try:
    value = json.loads(text[start : end + 1])
  except ValueError:
    return None
  return value if isinstance(value, dict) else None


def phase_stop(
    left: float | None, desired: float, buffer: float = 60
) -> tuple[float, float]:
  """Returns `(stop_before_sec, run_for)` for a fixed-budget phase."""
  if left is None:
    return desired, desired
  run = min(desired, max(60.0, left - buffer))
  return max(0.0, left - run), run


async def put_script(session: taskbridge.Session, name: str) -> str:
  """Writes a bundled task-container script to the scratch directory."""
  path = f"{SCRATCH}/{name}"
  text = (HERE / name).read_text(encoding="utf-8")
  await session.write_file(path, text)
  return path


async def run_script(
    session: taskbridge.Session, name: str, args: list[str], timeout: int
) -> dict[str, Any]:
  """Runs a bundled script in the task container with python3 or python."""
  path = await put_script(session, name)
  quoted = " ".join(shlex.quote(str(a)) for a in [path] + args)
  command = (
      "if command -v python3 >/dev/null 2>&1; then "
      f"python3 {quoted}; else python {quoted}; fi"
  )
  result = await session.exec(command, timeout_sec=timeout)
  return {"exec": result, "json": parse_json(result.get("output", ""))}


async def mcp_catalog(session: taskbridge.Session) -> list[dict[str, Any]]:
  """Lists the task's MCP servers and a compact view of their tools."""
  catalog: list[dict[str, Any]] = []
  for server in session.mcp_servers:
    name = str(server.get("name", "mcp"))
    url = str(server.get("url", ""))
    try:
      client = taskbridge.MCPClient(session, url)
      await client.initialize()
      tools = await client.list_tools()
      catalog.append(
          {
              "name": name,
              "url": url,
              "tool_count": len(tools),
              "tools": [
                  {
                      "name": str(tool.get("name", "")),
                      "description": str(tool.get("description", ""))[:240],
                  }
                  for tool in tools[:240]
              ],
          }
      )
    except Exception as exc:  # noqa: BLE001 - an MCP fault must not stop triage
      catalog.append({"name": name, "url": url, "error": str(exc)})
  return catalog


async def preflight(
    session: taskbridge.Session,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool, list[dict[str, Any]]]:
  """Inventories the workspace, extracts candidate deliverables, and lists MCP."""
  await session.exec(f"mkdir -p {SCRATCH}", timeout_sec=30)
  result = await run_script(
      session, "preflight_task.py", [session.workdir, SCRATCH], 180
  )
  inventory = result["json"]
  if not inventory:
    await session.log("harness: preflight failed; continuing without inventory")
    inventory = {
        "workdir": session.workdir,
        "file_count": 0,
        "dir_count": 0,
        "by_ext": {},
        "by_kind": {},
        "key_files": [],
        "output_dirs": [],
        "tools": {"commands": {}, "modules": {}},
        "files": [],
    }
  deliverables, unscoped = triage.extract_deliverables(
      session.instruction, inventory, session.workdir
  )
  mcp = await mcp_catalog(session)
  if mcp:
    await session.write_file(
        f"{SCRATCH}/mcp_catalog.json", json.dumps(mcp, indent=1)
    )
  return inventory, deliverables, unscoped, mcp


async def check(
    session: taskbridge.Session, deliverables: list[dict[str, Any]]
) -> dict[str, Any]:
  """Runs the deterministic deliverable checker in the task container."""
  if not deliverables:
    return {
        "workdir": session.workdir,
        "deliverables": [],
        "ok": 0,
        "missing": 0,
        "empty": 0,
        "invalid": 0,
        "new_or_changed": 0,
    }
  payload = [
      {
          "path": item["path"],
          "kind": item.get("kind", "file"),
          "members": item.get("members", []),
      }
      for item in deliverables
  ]
  await session.write_file(f"{SCRATCH}/deliverables.json", json.dumps(payload))
  result = await run_script(
      session,
      "check_task.py",
      [session.workdir, f"{SCRATCH}/deliverables.json", SCRATCH],
      120,
  )
  report = result["json"]
  if not report:
    await session.log("harness: checker failed; treating deliverables as unchecked")
    return {
        "workdir": session.workdir,
        "deliverables": [],
        "ok": 0,
        "missing": 0,
        "empty": 0,
        "invalid": 0,
        "new_or_changed": 0,
    }
  return report


def plan_template(deliverables: list[dict[str, Any]], unscoped: bool) -> str:
  """Returns the initial plan file the executor fills in."""
  lines = ["# Plan", "", "## Deliverable contract", ""]
  if unscoped:
    lines.append(
        "The extractor found no explicit path. Write the exact deliverable paths, "
        "formats, and required content here before working."
    )
  else:
    lines += ["| Path | Kind | Format | Status |", "|---|---|---|---|"]
    for item in deliverables:
      lines.append(
          f"| `{item['path']}` | {item['kind']} | {item['format']} | "
          f"{'exists' if item['exists'] else 'missing'} |"
      )
    lines.append("")
    lines.append(
        "Correct any wrong path or missing deliverable in this table, then follow it."
    )
  lines += [
      "",
      "## Method",
      "",
      "## Verification",
      "",
      "For each deliverable: how it will be opened, what will be recomputed, and "
      "what exact path/format is required.",
      "",
  ]
  return "\n".join(lines)


async def make_dirs(
    session: taskbridge.Session, deliverables: list[dict[str, Any]]
) -> None:
  """Creates the parent directories for every candidate deliverable."""
  dirs: list[str] = []
  for item in deliverables:
    path = str(item["path"])
    if item.get("kind") == "dir":
      dirs.append(path)
    else:
      parent = os.path.dirname(path)
      if parent and parent != "/":
        dirs.append(parent)
  unique = sorted({d for d in dirs if d and not d.startswith(SCRATCH)})
  if not unique:
    return
  command = "mkdir -p " + " ".join(shlex.quote(d) for d in unique[:40])
  await session.exec(command, timeout_sec=60)


async def run_pi(
    session: taskbridge.Session,
    prompt: str,
    system_prompt: str,
    stop_before_sec: float,
    thinking: str,
    publish: bool,
    label: str,
    fraction: float = 1.0,
) -> tuple[Run, Any]:
  """Runs one Pi session against the task container."""
  with tempfile.TemporaryDirectory(
      prefix="pi-",
      dir=os.environ.get("HOME") or None,
      ignore_cleanup_errors=True,
  ) as scratch:
    agent_dir, work = (
        pathlib.Path(scratch) / "agent",
        pathlib.Path(scratch) / "work",
    )
    agent_dir.mkdir()
    work.mkdir()
    async with taskbridge.Relay(session) as relay:
      env = relay.env()
      env.update(
          PI_CODING_AGENT_DIR=str(agent_dir),
          PI_OFFLINE="1",
          PI_SKIP_VERSION_CHECK="1",
          PI_TELEMETRY="0",
          NODE_NO_WARNINGS="1",
          TASK_WORKDIR=session.workdir,
      )
      name, model = await asyncio.to_thread(
          configure, agent_dir, relay, session, env
      )
      argv = [
          PI,
          "--print",
          "--mode",
          "json",
          "--no-session",
          "-nc",
          "-ns",
          "-np",
          "-na",
          "-e",
          str(HERE / "task-tools.ts"),
          "--provider",
          name,
          "--model",
          model,
          "--thinking",
          thinking,
          "--append-system-prompt",
          system_prompt.replace("{workdir}", session.workdir).replace(
              "{scratch}", SCRATCH
          ),
      ]
      run = Run(session, model, publish=publish)
      done = await taskbridge.run_process(
          argv,
          session,
          env=env,
          cwd=str(work),
          on_line=run.on_line,
          stdin=prompt.encode(),
          stop_before_sec=stop_before_sec,
          fraction=fraction,
          log_prefix=f"{label}: ",
      )
  return run, done


def missing_count(report: dict[str, Any]) -> int:
  """Returns the number of deliverables that need another pass."""
  return int(report.get("missing", 0)) + int(report.get("empty", 0)) + int(
      report.get("invalid", 0)
  )


async def solve(session: taskbridge.Session) -> str:
  """Runs the triage, execute, audit, fix, close pipeline for one task."""
  final = ""
  deliverables: list[dict[str, Any]] = []
  report: dict[str, Any] = {}
  try:
    total = session.time_left()
    await session.log("harness: preflight")
    inventory, deliverables, unscoped, mcp = await preflight(session)
    brief = triage.build_brief(
        session.instruction,
        inventory,
        deliverables,
        unscoped,
        SCRATCH,
        total,
        mcp,
    )
    await session.write_file(f"{SCRATCH}/BRIEF.md", brief)
    await session.write_file(
        f"{SCRATCH}/plan.md", plan_template(deliverables, unscoped)
    )
    await session.write_file(f"{SCRATCH}/notes.md", "# Notes\n")
    await session.write_file(
        f"{SCRATCH}/calc_log.csv", "item,value,unit,source,check\n"
    )
    await make_dirs(session, deliverables)
    await session.log(
        f"harness: {len(deliverables)} deliverable candidate(s); "
        f"unscoped={unscoped}; brief at {SCRATCH}/BRIEF.md"
    )

    # Executor: 85% of the total budget, leaving room for verification.
    left = session.time_left()
    if total is None:
      stop, _ = STOP_BEFORE_SEC, STOP_BEFORE_SEC
    else:
      stop, _ = phase_stop(left, 0.85 * total, buffer=60)
    executor_prompt = (
        session.instruction
        + "\n\n## Harness brief\n\nRead `"
        + SCRATCH
        + "/BRIEF.md` first. Then write `"
        + SCRATCH
        + "/plan.md`, create a skeleton at every required deliverable path, "
        "and execute the plan."
    )
    run, done = await run_pi(
        session,
        executor_prompt,
        EXECUTOR,
        stop,
        default_effort(),
        True,
        "executor",
    )
    final = run.final or final
    report = await check(session, deliverables)
    await session.log(
        f"harness: executor exit={done.code}; check ok={report.get('ok')} "
        f"missing={report.get('missing')} empty={report.get('empty')} "
        f"invalid={report.get('invalid')}"
    )

    # Auditor: independent re-derivation. Skip only when the clock is short.
    left = session.time_left()
    if left is None or left > 900:
      stop, _ = phase_stop(left, AUDIT_SEC, buffer=300)
      audit_prompt = triage.build_audit_prompt(
          session.instruction, SCRATCH, final, report
      )
      audit, _ = await run_pi(
          session,
          audit_prompt,
          AUDITOR,
          stop,
          "high",
          False,
          "auditor",
      )
      verdict = audit.final
      await session.log(f"harness: auditor: {verdict[:600]}")
      if verdict and not triage.is_pass(verdict):
        left = session.time_left()
        if left is None or left > 600:
          stop, _ = phase_stop(left, FIX_SEC, buffer=180)
          fix_prompt = triage.build_fix_prompt(
              session.instruction, SCRATCH, final, verdict, report
          )
          fixed, _ = await run_pi(
              session,
              fix_prompt,
              FIXER,
              stop,
              default_effort(),
              True,
              "fixer",
          )
          final = fixed.final or final
          report = await check(session, deliverables)
          await session.log(
              f"harness: fixer check ok={report.get('ok')} "
              f"missing={report.get('missing')} empty={report.get('empty')} "
              f"invalid={report.get('invalid')}"
          )

    # Closer: the deterministic safety net for a missing/empty path.
    left = session.time_left()
    if missing_count(report) > 0 and (left is None or left > 120):
      stop, _ = phase_stop(left, CLOSE_SEC, buffer=30)
      close_prompt = triage.build_closer_prompt(
          session.instruction, SCRATCH, report, left
      )
      closed, _ = await run_pi(
          session,
          close_prompt,
          CLOSER,
          stop,
          "high",
          True,
          "closer",
      )
      final = closed.final or final
      report = await check(session, deliverables)
      await session.log(
          f"harness: closer check ok={report.get('ok')} "
          f"missing={report.get('missing')} empty={report.get('empty')} "
          f"invalid={report.get('invalid')}"
      )

    # Last-resort deterministic scaffold: a draft at every still-missing path.
    left = session.time_left()
    if missing_count(report) > 0 and (left is None or left > 30):
      await run_script(
          session,
          "scaffold.py",
          [session.workdir, f"{SCRATCH}/deliverables.json", SCRATCH],
          120,
      )
      report = await check(session, deliverables)
      await session.log(
          f"harness: scaffold check ok={report.get('ok')} "
          f"missing={report.get('missing')} empty={report.get('empty')} "
          f"invalid={report.get('invalid')}"
      )

    return triage.build_final_message(final, report, deliverables)
  except taskbridge.Cancelled:
    raise
  except Exception as exc:  # noqa: BLE001 - the task must still end with done
    with contextlib.suppress(Exception):
      await session.log(f"harness: error {type(exc).__name__}: {exc}")
    if session.final_message.strip():
      return session.final_message.strip()
    return f"Harness error: {type(exc).__name__}: {exc}"


if __name__ == "__main__":
  taskbridge.run(solve)
