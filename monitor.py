"""DINS Monitor | WhisperShell-compatible modular operator front panel.

This file is a NEW front end. The original WhisperShell.py and module APIs are
not rewritten. Place monitor.py alongside WhisperShell.py and modules/.
Python 3.10+ standard library; no external Python packages required by Monitor.

The historical connection code DINS.WHISPERSHELL.ORCHESTRATOR is preserved.
A robotics module opts into loading via monitor_load(context) and may expose
monitor_ready(), monitor_commands(), and monitor_command(action, payload).
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
MODULES = ROOT / "modules"
SCRIPTS = ROOT / "tools" / "scripts"
TEMPLATES = ROOT / "templates"
BLUEPRINT = ROOT / "architecture" / "blueprint.json"
MEMORY_CONFIG = ROOT / "data" / "memory" / "monitor_settings.json"
ROBOTICS_CONFIG = ROOT / "data" / "robotics" / "slots.json"
PROMPT_FOLDER = ROOT / "data" / "builder_prompts"
CODE = "DINS.WHISPERSHELL.ORCHESTRATOR"  # historical identity; never rename

DEFAULTS = {
    "input": {"mode": "Human Input", "source": "Text"},
    "resident": {"provider": "None", "model": ""},
    "builder": {"template": "default", "profile": "Full Original"},
}
PROVIDERS = ("None", "Ollama (local)", "OpenAI (API)", "Nebius (API)", "Custom API")
INPUT_SOURCES = {
    "Onscreen AI": ("ChatGPT window", "Claude window", "Grok window", "Other window"),
    "Local AI": ("Ollama", "Other local model"),
    "API AI": ("OpenAI", "Nebius", "Custom API"),
    "Scripts": ("Python", "PowerShell", "CMD", "Executable workflow"),
    "Human Input": ("Text", "Voice"),
}

# Slot name, relative file, preselected. Slot = UI definition, NOT a second robot.
ROBOTICS_DEFAULTS = (
    ("First Sight", "modules/first_sight.py", True),
    ("First Touch", "modules/first_touch.py", True),
    ("First Hearing", "modules/first_hearing.py", True),
    ("First Response", "modules/first_response.py", True),
    ("Delta Voice", "modules/delta_voice.py", True),
    ("Triangulation", "modules/robot_triangulation.py", False),
    ("First Sight API/Local", "modules/local.py", False),
)


def _safe_relative_file(relative: str, *, suffix: str = ".py") -> Path:
    """Resolve configured slot paths within this installation only."""
    item = Path(relative)
    path = (ROOT / item).resolve()
    if item.is_absolute() or not path.is_relative_to(ROOT) or path == ROOT or path.suffix.lower() != suffix:
        raise ValueError(f"Invalid module path: {relative}")
    return path


def _import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def field_module():
    if not (MODULES / "shared_field.py").is_file():
        raise FileNotFoundError("modules/shared_field.py is missing")
    if str(MODULES) not in sys.path:
        sys.path.insert(0, str(MODULES))
    import shared_field
    return shared_field


def bridge_module():
    if not (MODULES / "template_bridge.py").is_file():
        raise FileNotFoundError("modules/template_bridge.py is missing")
    if str(MODULES) not in sys.path:
        sys.path.insert(0, str(MODULES))
    import template_bridge
    return template_bridge


def preference_state() -> dict[str, Any]:
    field = field_module()
    field.register_block(CODE, DEFAULTS)
    result = field.get_block(CODE) or {}
    return result if isinstance(result, dict) else {}


def save_preferences(*, provider=None, model=None, input_mode=None, input_source=None):
    changes: dict[str, Any] = {}
    if provider is not None or model is not None:
        updates = {}
        if provider is not None:
            if provider not in PROVIDERS:
                raise ValueError("Unknown AI provider")
            updates["provider"] = provider
        if model is not None:
            updates["model"] = model.strip()
        changes["resident"] = updates
    if input_mode is not None or input_source is not None:
        old = preference_state().get("input", {})
        mode = input_mode if input_mode is not None else old.get("mode", "Human Input")
        source = input_source if input_source is not None else old.get("source", "Text")
        if mode not in INPUT_SOURCES or not str(source).strip():
            raise ValueError("Invalid input selection")
        changes["input"] = {"mode": mode, "source": str(source).strip()}
    return field_module().update_block(CODE, changes) if changes else preference_state()


def available_templates() -> list[str]:
    values = ["default", "robotics", "custom"]
    if TEMPLATES.is_dir():
        values += [p.name for p in TEMPLATES.iterdir() if p.is_dir()]
    return list(dict.fromkeys(values))


def capture_template(name: str) -> Path:
    return bridge_module().save_profile(name)


def apply_template(name: str) -> int:
    return bridge_module().apply_profile(name)


def blueprint_inventory() -> dict[str, Any]:
    with BLUEPRINT.open("r", encoding="utf-8") as f:
        plan = json.load(f)
    if plan.get("format") != "DINS.WhisperShell.Original.Blueprint":
        raise ValueError("Unrecognized blueprint format")
    components = plan.get("components")
    if not isinstance(components, list):
        raise ValueError("Blueprint must contain a component list")
    return {
        "schema_version": plan.get("schema_version"),
        "diagrams_archived": len(plan.get("diagram_index", [])),
        "components": [
            {"id": c["id"], "name": c["name"], "phase": c["phase"],
             "path": c["path"], "source_file_present": (ROOT / c["path"]).is_file()}
            for c in components
        ],
    }


def ollama_models() -> list[str]:
    try:
        req = Request("http://127.0.0.1:11434/api/tags", headers={"Accept": "application/json"})
        with urlopen(req, timeout=1.5) as response:
            data = json.load(response)
        return sorted({m["name"] for m in data.get("models", [])
                       if isinstance(m, dict) and isinstance(m.get("name"), str)})
    except (URLError, TimeoutError, OSError, ValueError, KeyError):
        return []


# Two independent Resident connections. No API key is ever written to disk or Shared Field.
# Model IDs and provider availability may change; all model fields are editable.
RESIDENT_LOCAL_CODE = "DINS.WHISPERSHELL.RESIDENT.LOCAL"
RESIDENT_API_CODE = "DINS.WHISPERSHELL.RESIDENT.API"
LOCAL_DEFAULT_URL = "http://127.0.0.1:11434"
API_PROVIDERS = {
    "Groq Cloud": {"protocol": "openai", "endpoint": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.3-70b-versatile"},
    "OpenRouter": {"protocol": "openai", "endpoint": "https://openrouter.ai/api/v1/chat/completions", "model": ""},
    "Gemini (Google)": {"protocol": "gemini", "endpoint": "https://generativelanguage.googleapis.com/v1beta/models", "model": "gemini-2.0-flash"},
    "Claude (Anthropic)": {"protocol": "anthropic", "endpoint": "https://api.anthropic.com/v1/messages", "model": "claude-3-5-haiku-latest"},
    "Grok (xAI)": {"protocol": "openai", "endpoint": "https://api.x.ai/v1/chat/completions", "model": "grok-3-mini"},
    "Qwen (Alibaba)": {"protocol": "openai", "endpoint": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions", "model": "qwen-plus"},
    "OpenAI": {"protocol": "openai", "endpoint": "https://api.openai.com/v1/chat/completions", "model": "gpt-4o-mini"},
    "Nebius": {"protocol": "openai", "endpoint": "https://api.studio.nebius.com/v1/chat/completions", "model": ""},
    "Custom (OpenAI-compatible)": {"protocol": "openai", "endpoint": "http://127.0.0.1:8000/v1/chat/completions", "model": ""},
}


def _validated_endpoint(value: str, *, local: bool = False) -> str:
    """Allow HTTPS for remote keys; HTTP only for loopback services."""
    from urllib.parse import urlsplit
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Enter a full http:// or https:// endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Endpoint must not contain credentials, query parameters or fragments")
    if parsed.scheme == "http" and parsed.hostname.lower() not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Use HTTPS for remote services; HTTP is only allowed for localhost")
    if local and parsed.path not in ("", "/"):
        raise ValueError("Enter the Ollama server address only, for example http://127.0.0.1:11434")
    return value


def _resident_json_request(url: str, payload=None, *, headers=None, timeout=30, secret=""):
    from urllib.error import HTTPError
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=hdrs, method="POST" if body is not None else "GET")
    try:
        with urlopen(req, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        try:
            details = exc.read(1000).decode("utf-8", "replace")
            parsed = json.loads(details)
            if isinstance(parsed, dict):
                error = parsed.get("error", details)
                details = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        except (ValueError, UnicodeError, OSError):
            details = exc.reason or "Request rejected"
        details = str(details).replace(secret, "[REDACTED]") if secret else str(details)
        raise RuntimeError(f"HTTP {exc.code}: {details[:450]}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Connection failed: {exc}") from None
    except ValueError as exc:
        raise RuntimeError(f"Invalid JSON response from server: {exc}") from None
    if not isinstance(result, dict):
        raise RuntimeError("Server did not return a JSON object")
    return result


def _resident_ollama_models(base: str) -> list[str]:
    data = _resident_json_request(_validated_endpoint(base, local=True) + "/api/tags", timeout=8)
    models = data.get("models", [])
    if not isinstance(models, list):
        raise RuntimeError("Unexpected Ollama /api/tags response")
    return sorted({item["name"] for item in models
                   if isinstance(item, dict) and isinstance(item.get("name"), str)})


def _resident_local_reply(base: str, model: str, messages: list[dict]) -> str:
    result = _resident_json_request(
        _validated_endpoint(base, local=True) + "/api/chat",
        {"model": model, "messages": messages, "stream": False}, timeout=120)
    response = result.get("message") or {}
    content = response.get("content") if isinstance(response, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Ollama returned no text in message.content")
    return content.strip()


def _resident_api_reply(provider: str, endpoint: str, model: str,
                        api_key: str, messages: list[dict]) -> str:
    from urllib.parse import quote
    if provider not in API_PROVIDERS:
        raise ValueError("Unknown API provider")
    endpoint = _validated_endpoint(endpoint)
    if not model.strip():
        raise ValueError("Enter a model ID")
    protocol = API_PROVIDERS[provider]["protocol"]
    if protocol == "anthropic":
        if not api_key:
            raise ValueError("Claude requires an API key")
        result = _resident_json_request(endpoint,
            {"model": model, "max_tokens": 1024, "messages": messages},
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            timeout=90, secret=api_key)
        parts = result.get("content", [])
        answer = "\n".join(p.get("text", "") for p in parts
                           if isinstance(p, dict) and isinstance(p.get("text"), str))
    elif protocol == "gemini":
        if not api_key:
            raise ValueError("Gemini requires an API key")
        url = endpoint + "/" + quote(model, safe="") + ":generateContent"
        contents = [{"role": "model" if m["role"] == "assistant" else "user",
                     "parts": [{"text": m["content"]}]} for m in messages]
        result = _resident_json_request(url, {"contents": contents},
            headers={"x-goog-api-key": api_key}, timeout=90, secret=api_key)
        candidates = result.get("candidates", [])
        parts = (candidates[0].get("content") or {}).get("parts", []) if candidates else []
        answer = "\n".join(p.get("text", "") for p in parts
                           if isinstance(p, dict) and isinstance(p.get("text"), str))
        if not answer:
            reason = (result.get("promptFeedback") or {}).get("blockReason", "")
            if reason:
                raise RuntimeError(f"Gemini blocked the request: {reason}")
    else:
        headers = {"Authorization": "Bearer " + api_key} if api_key else {}
        result = _resident_json_request(endpoint,
            {"model": model, "messages": messages, "stream": False},
            headers=headers, timeout=90, secret=api_key)
        choices = result.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        answer = message.get("content", "") if isinstance(message, dict) else ""
        if isinstance(answer, list):
            answer = "\n".join(str(x.get("text", "")) for x in answer if isinstance(x, dict))
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Provider returned no text response; check its model and response format")
    return answer.strip()


def _resident_publish(channel: str, *, connected: bool, state: str,
                      provider: str, model: str, endpoint: str):
    # Intentionally never accept or save an API key or conversation transcript here.
    code = RESIDENT_LOCAL_CODE if channel == "local" else RESIDENT_API_CODE
    return field_module().update_block(code, {
        "connected": bool(connected), "state": state,
        "provider": provider, "model": model, "endpoint": endpoint,
    })


def _resident_save_settings(channel: str, data: dict):
    """Save only non-secret fields, separately for each Resident."""
    clean = {k: str(data[k]) for k in ("provider", "model", "endpoint") if k in data}
    return field_module().update_block(CODE, {"resident_" + channel: clean})


def safe_script_path(name: str, language: str) -> Path:
    extensions = {"Python": ".py", "PowerShell": ".ps1", "CMD": ".cmd"}
    if language not in extensions:
        raise ValueError("Choose Python, PowerShell or CMD")
    ext = extensions[language]
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", name):
        raise ValueError("Use a plain filename")
    return SCRIPTS / (name if name.lower().endswith(ext) else name + ext)


def _load_json(path: Path, default: dict) -> dict:
    if not path.is_file():
        return json.loads(json.dumps(default))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected an object in {path.name}")
    return data


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


# Builder lives inside Monitor, using whichever Resident is already connected.
# It never installs packages or runs generated scripts without an explicit operator action.
BUILDER_PROJECTS = ROOT / "data" / "builder_projects"
BUILDER_DEFAULT_PROMPT = """Hello, welcome to Digital Intelligence Neuromorphic Systems (DINS).

This system was made by Ferenna (AI) and her partner Dennis (human).

What we want to ask of you is to create a small application following the guidelines presented to you.

You are DINS Builder, a coding assistant working with the selected local AI or API AI in DINS Monitor.

Your capabilities are:
1. FOLDER SETUP: Create the requested project folder and suitable subfolders.
2. SMALL SCRIPTS: Write small Python, CMD or PowerShell scripts when appropriate.
3. README: Explain what the application does and how to start it.
4. SMALL MODIFICATIONS: Read and change existing code without damaging unrelated sections.
5. VERIFICATION: Check files, inspect errors and report actual test results.

These are CAPABILITIES, not a fixed five-step limit. Choose as many steps as the task requires.
Do one small, understandable task per step and preserve existing project files.
Work inside the selected project workspace. Do not assume that describing a file creates it.
Only the Builder's confirmed file tools can actually make or modify files.
Never claim a file was created, modified, run or tested without confirmation.
Honor the chosen operating system, system RAM and application RAM budget.
Prefer lightweight libraries and avoid unnecessary background processes.

When asked for a PLAN, act ONLY as PROJECT PLANNER. Your first response must contain numbered instructions to yourself, NOT code. Do NOT include source code, file contents, headings, Markdown, code fences, explanations or unnecessary features. Every instruction will be returned to you individually by the DINS WhisperShell injector. When receiving an individual instruction, act as BUILDER and complete only that step. Do not generate another numbered plan.
EVERY instruction line must start with its consecutive number, a dot and one space.
Separate every instruction with ONE blank line. Start with 1. Do not add headers,
code fences, bullets, or explanations outside the numbered instructions.

When asked to COMPLETE A STEP, return only the requested JSON action object.
Builder will preview proposed file actions and ask the human before applying them.
"""


def builder_parse_steps(raw: str) -> list[str]:
    """Parse simple numbered, blank-line-separated injection instructions."""
    if not isinstance(raw, str):
        raise ValueError("AI plan must be text")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n|\n```\s*$", "", text).strip()
    lines = text.splitlines()
    numbered: list[str] = []
    for line in lines:
        if not line.strip():
            continue
        match = re.fullmatch(r"\s*(\d+)\.\s+(.+?)\s*", line)
        if not match:
            raise ValueError("Every instruction must occupy one numbered line, with a blank line between steps")
        expected = len(numbered) + 1
        if int(match.group(1)) != expected:
            raise ValueError(f"Step numbering must be consecutive from 1 (expected {expected})")
        numbered.append(match.group(2).strip())
    if not numbered:
        raise ValueError("The AI did not supply any numbered steps")
    # Enforce the requested blank lines between instructions; allow first or trailing newline.
    relevant = [i for i, line in enumerate(lines) if line.strip()]
    if any(b - a < 2 for a, b in zip(relevant, relevant[1:])):
        raise ValueError("Insert one blank line between consecutive numbered steps")
    return numbered


def builder_decode_actions(raw: str) -> tuple[list[dict], str]:
    """No executable source is evaluated. Only restricted JSON file operations."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n|\n```\s*$", "", text).strip()
    try:
        result = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"AI returned invalid JSON actions: {exc}") from None
    if not isinstance(result, dict) or not isinstance(result.get("actions"), list):
        raise ValueError('Step reply must be JSON with an "actions" list and "report" string')
    actions = result["actions"]
    if len(actions) > 12:
        raise ValueError("At most 12 file operations per step")
    for action in actions:
        if not isinstance(action, dict) or action.get("op") not in ("mkdir", "write"):
            raise ValueError("Only mkdir and write operations are supported")
        if not isinstance(action.get("path"), str):
            raise ValueError("Each file operation needs a relative path")
        if action["op"] == "write" and (not isinstance(action.get("content"), str)
                                            or len(action["content"]) > 100_000):
            raise ValueError("A write action needs text content of at most 100,000 characters")
    return actions, str(result.get("report", ""))[:1500]


def builder_project_path(project_root: Path, relative: str) -> Path:
    if not relative or relative.strip() != relative or "\\" in relative:
        raise ValueError("Use a plain forward-slash relative project path")
    rel = Path(relative)
    if rel.is_absolute() or any(part in (".", "..", "") for part in rel.parts):
        raise ValueError("Project file paths must stay inside the project folder")
    root = project_root.resolve()
    result = (root / rel).resolve()
    if not result.is_relative_to(root) or result == root:
        raise ValueError("A Builder file action tried to leave the project folder")
    return result


def builder_apply_actions(project_root: Path, actions: list[dict]) -> list[str]:
    """Validate all actions before touching disk. Caller must first obtain user approval."""
    validated = []
    for action in actions:
        destination = builder_project_path(project_root, action["path"])
        if action["op"] == "mkdir":
            if destination.exists() and not destination.is_dir():
                raise ValueError(f"Cannot create folder over existing file: {action['path']}")
        elif action["op"] == "write":
            if destination.exists() and not destination.is_file():
                raise ValueError(f"Cannot write over folder: {action['path']}")
        validated.append((action, destination))
    project_root.mkdir(parents=True, exist_ok=True)
    completed = []
    for action, destination in validated:
        if action["op"] == "mkdir":
            destination.mkdir(parents=True, exist_ok=True)
            completed.append(f"Created/confirmed directory: {action['path']}")
        else:
            existed = destination.is_file()
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = destination.with_name(destination.name + ".builder_tmp")
            temp.write_text(action["content"], encoding="utf-8")
            temp.replace(destination)
            completed.append(f"{'Updated' if existed else 'Created'} file: {action['path']}")
    return completed


def builder_workspace_context(project_root: Path) -> str:
    """A bounded context snapshot for small local coding models."""
    if not project_root.is_dir():
        return "Project folder is empty (not created yet)."
    items = []
    budget = 12_000
    allowed = {".py", ".cmd", ".bat", ".ps1", ".md", ".txt", ".json", ".html", ".css", ".js"}
    for entry in sorted(project_root.rglob("*")):
        if len(items) >= 18 or budget <= 0:
            break
        if not entry.is_file() or entry.is_symlink() or entry.suffix.lower() not in allowed:
            continue
        if entry.name.startswith(".") or entry.stat().st_size > 35_000:
            continue
        rel = str(entry.relative_to(project_root)).replace("\\", "/")
        if any(p.startswith(".") for p in Path(rel).parts):
            continue
        try:
            value = entry.read_text(encoding="utf-8")[:min(2800, budget)]
        except (OSError, UnicodeError):
            continue
        items.append(f"FILE {rel}:\n{value}")
        budget -= len(value)
    return "\n\n".join(items) if items else "Workspace contains no readable source files yet."


def builder_verify_files(project_root: Path) -> str:
    """Static verification only: does not execute scripts or claim to test RAM."""
    if not project_root.is_dir():
        return "No project folder has been created."
    files = [p for p in sorted(project_root.rglob("*")) if p.is_file()]
    failed = []
    for p in files:
        try:
            if p.suffix.lower() == ".py":
                ast.parse(p.read_text(encoding="utf-8-sig"), filename=str(p))
            elif p.suffix.lower() == ".json":
                json.loads(p.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError, OSError, UnicodeError) as exc:
            failed.append(f"{p.relative_to(project_root)}: {exc}")
    names = ", ".join(str(p.relative_to(project_root)) for p in files[:25]) or "none"
    return (f"Files on disk ({len(files)}): {names}\n"
            f"Static syntax checks: {'passed' if not failed else 'FAILED: ' + '; '.join(failed)}\n"
            "Scripts were not executed. Runtime RAM consumption has not been measured.")


def robotics_slots() -> list[dict]:
    config = _load_json(ROBOTICS_CONFIG, {"selected": {}, "custom": []})
    selected = config.get("selected", {})
    if not isinstance(selected, dict):
        selected = {}
    slots = [{"name": n, "path": p, "selected": bool(selected.get(n, initial))}
             for n, p, initial in ROBOTICS_DEFAULTS]
    for extra in config.get("custom", []):
        if isinstance(extra, dict) and isinstance(extra.get("name"), str) and isinstance(extra.get("path"), str):
            slots.append({"name": extra["name"], "path": extra["path"],
                          "selected": bool(selected.get(extra["name"], extra.get("selected", False)))})
    return slots


def save_robotics_slots(slots: list[dict]):
    standard = {n for n, _p, _active in ROBOTICS_DEFAULTS}
    _save_json(ROBOTICS_CONFIG, {
        "selected": {slot["name"]: bool(slot["selected"]) for slot in slots},
        "custom": [{"name": x["name"], "path": x["path"]} for x in slots if x["name"] not in standard],
    })


def _declares_monitor_load(path: Path) -> bool:
    """Avoid importing GUI scripts without an explicit Monitor integration hook."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name == "monitor_load" for node in tree.body)


def activate_module(slot: dict):
    """Connect one optional module using its own explicit Monitor contract.

    Hooks: monitor_load(context) -> True or {ready: True, ...}, optional
    monitor_ready() -> bool; monitor_commands() -> list[str];
    monitor_command(action, payload) -> result.
    """
    path = _safe_relative_file(slot["path"])
    if not path.is_file():
        raise FileNotFoundError(f"{slot['name']}: file not installed")
    if not _declares_monitor_load(path):
        raise RuntimeError(f"{slot['name']}: needs monitor_load integration")
    module_key = "dins_monitor_" + re.sub(r"\W+", "_", slot["name"]).strip("_").lower()
    plugin = _import_module(module_key, path)
    result = plugin.monitor_load({"root": str(ROOT), "role": "robotics", "connection_code": CODE})
    ready = result is True or (isinstance(result, dict) and result.get("ready") is True)
    if hasattr(plugin, "monitor_ready"):
        ready = ready and bool(plugin.monitor_ready())
    if not ready:
        raise RuntimeError(f"{slot['name']}: did not confirm readiness")
    return plugin


def status() -> dict[str, Any]:
    state = preference_state()
    field = field_module()
    connected = ["Shared Field"]
    try:
        bridge_module().list_profiles()
        connected.append("Template Bridge")
    except (ImportError, OSError, AttributeError, ValueError):
        pass
    return {"application": "DINS Monitor", "root": str(ROOT),
            "field_revision": field.revision(), "connected": connected,
            "orchestrator": state}


def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError as exc:
        raise RuntimeError("Tkinter unavailable on this Python installation") from exc

    state = preference_state()
    app = tk.Tk()
    app.title("DINS Monitor")
    app.geometry("1080x760")
    app.minsize(800, 575)
    notebook = ttk.Notebook(app)
    notebook.pack(fill="both", expand=True, padx=12, pady=10)

    pages = {name: ttk.Frame(notebook, padding=16) for name in (
        "Home / Monitor", "Resident", "Builder", "Robotics", "Memory Setup",
        "Script Automation", "Manual Operator")}
    for name, panel in pages.items():
        notebook.add(panel, text="  " + name + "  ")

    connected: dict[str, Any] = {"Shared Field": field_module()}
    try:
        b = bridge_module()
        b.list_profiles()  # successful API call, not just a file-presence check
        connected["Template Bridge"] = b
    except (ImportError, OSError, AttributeError, ValueError) as exc:
        bridge_problem = str(exc)
    else:
        bridge_problem = ""
    module_plugins: dict[str, Any] = {}
    events: list[str] = []

    def log(message: str):
        events.append(message)
        del events[:-60]
        refresh_home()

    def header(parent, title: str, subtitle: str = ""):
        ttk.Label(parent, text=title, font=("Segoe UI", 17, "bold")).pack(anchor="w")
        if subtitle:
            ttk.Label(parent, text=subtitle, wraplength=940).pack(anchor="w", pady=(4, 12))

    def message_error(title: str, exc: Exception):
        messagebox.showerror(title, str(exc))
        log(f"{title}: {exc}")

    # HOME/MONITOR: show connections actually verified or loaded, not absent plans.
    home = pages["Home / Monitor"]
    header(home, "Monitor", "Active connections and live system information")
    conn_frame = ttk.LabelFrame(home, text="Connected now", padding=9)
    conn_frame.pack(fill="x", pady=(0, 12))
    conn_text = tk.Text(conn_frame, height=5, wrap="word", state="disabled", font=("Consolas", 10))
    conn_text.pack(fill="x")
    resources = ttk.LabelFrame(home, text="System resources", padding=9)
    resources.pack(fill="x", pady=(0, 12))
    ram_label = tk.StringVar(value="Reading RAM...")
    ttk.Label(resources, textvariable=ram_label).pack(anchor="w")
    ram_progress = ttk.Progressbar(resources, maximum=100)
    ram_progress.pack(fill="x", pady=(5, 8))
    process_text = tk.Text(resources, height=6, state="disabled", font=("Consolas", 10))
    process_text.pack(fill="x")
    journal = ttk.LabelFrame(home, text="Recent module activity", padding=9)
    journal.pack(fill="both", expand=True)
    event_text = tk.Text(journal, state="disabled", font=("Consolas", 10))
    event_text.pack(fill="both", expand=True)

    def set_readonly(widget, value: str):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def refresh_home():
        names = sorted(connected.keys())
        def connection_line(name):
            entry = connected[name]
            if isinstance(entry, dict) and "status" in entry:
                return f"{name}: {entry['status']}"
            return "CONNECTED   " + name
        set_readonly(conn_text, "\n".join(connection_line(n) for n in names)
                     if names else "No verified connections")
        try:
            rev = field_module().revision()
            msg = f"Shared Field revision: {rev}"
        except Exception:
            msg = "Shared Field revision: unavailable"
        set_readonly(event_text, msg + "\n\n" + "\n".join(events[-25:]))

    try:
        import resource_monitor
    except ImportError:
        resource_monitor = None

    def refresh_resources():
        if resource_monitor is not None:
            try:
                info = resource_monitor.memory_snapshot()
                ram_label.set(f"RAM: {resource_monitor.gib(info['used_bytes']):.2f} / "
                              f"{resource_monitor.gib(info['total_bytes']):.2f} GiB   "
                              f"Available: {resource_monitor.gib(info['available_bytes']):.2f} GiB")
                ram_progress["value"] = info["used_percent"]
            except Exception as exc:
                ram_label.set(f"RAM measurement unavailable: {exc}")
        else:
            ram_label.set("Resource monitor module not connected")
        app.after(3000, refresh_resources)

    def refresh_processes():
        if resource_monitor is None:
            set_readonly(process_text, "Process list unavailable")
            return
        try:
            processes = resource_monitor.top_processes(8)
            set_readonly(process_text, "\n".join(
                f"{p['name'][:37]:<38}{p['memory_bytes'] / 1048576:>8.1f} MB  PID {p['pid']}"
                for p in processes))
        except Exception as exc:
            set_readonly(process_text, f"Process list unavailable: {exc}")

    ttk.Button(resources, text="Refresh processes", command=refresh_processes).pack(anchor="w", pady=(8, 0))
    refresh_resources()
    refresh_processes()

    # RESIDENT: two completely independent operators sharing the same Field.
    # Only this tab was redesigned; Manual Operator and Script Automation stay free.
    resident = pages["Resident"]
    header(resident, "Resident", "Local AI and API AI can connect and chat independently")
    ttk.Label(resident,
              text="Two separate connections. Each has its own settings, chat and Disconnect control.",
              wraplength=960).pack(anchor="w", pady=(0, 8))
    resident_panels = ttk.Panedwindow(resident, orient="horizontal")
    resident_panels.pack(fill="both", expand=True)
    local_panel = ttk.Frame(resident_panels, padding=8)
    api_panel = ttk.Frame(resident_panels, padding=8)
    resident_panels.add(local_panel, weight=1)
    resident_panels.add(api_panel, weight=1)

    resident_events: queue.Queue = queue.Queue()
    channels = {
        "local": {"connected": False, "verified": False, "generation": 0,
                  "busy": False, "history": [], "config": None},
        "api": {"connected": False, "verified": False, "generation": 0,
                "busy": False, "history": [], "config": None},
    }
    local_pref = state.get("resident_local", {})
    api_pref = state.get("resident_api", {})
    if not isinstance(local_pref, dict):
        local_pref = {}
    if not isinstance(api_pref, dict):
        api_pref = {}
    legacy = state.get("resident", {})
    legacy = legacy if isinstance(legacy, dict) else {}

    local_url = tk.StringVar(value=local_pref.get("endpoint", LOCAL_DEFAULT_URL))
    local_model = tk.StringVar(value=local_pref.get("model", legacy.get("model", "")
                                                if legacy.get("provider") == "Ollama (local)" else ""))
    local_status = tk.StringVar(value="Disconnected")
    ttk.Label(local_panel, text="LOCAL AI  /  Ollama", font=("Segoe UI", 14, "bold")).pack(anchor="w")
    ttk.Label(local_panel, text="Ollama address / port").pack(anchor="w", pady=(7, 0))
    local_endpoint_entry = ttk.Entry(local_panel, textvariable=local_url, width=46)
    local_endpoint_entry.pack(fill="x", pady=(2, 5))
    ttk.Label(local_panel, text="Local model").pack(anchor="w")
    local_models = ttk.Combobox(local_panel, textvariable=local_model, width=42)
    local_models.pack(fill="x", pady=(2, 5))
    local_buttons = ttk.Frame(local_panel)
    local_buttons.pack(fill="x", pady=(2, 5))
    local_connect_button = ttk.Button(local_buttons, text="Connect")
    local_connect_button.pack(side="left", padx=(0, 5))
    local_disconnect_button = ttk.Button(local_buttons, text="Disconnect")
    local_disconnect_button.pack(side="left", padx=(0, 5))
    local_discover_button = ttk.Button(local_buttons, text="Find models")
    local_discover_button.pack(side="left")
    ttk.Label(local_panel, textvariable=local_status, wraplength=400).pack(anchor="w", pady=(0, 6))
    ttk.Label(local_panel, text="Local conversation", font=("Segoe UI", 10, "bold")).pack(anchor="w")
    local_chat = tk.Text(local_panel, state="disabled", height=12, wrap="word", font=("Segoe UI", 10))
    local_chat.pack(fill="both", expand=True, pady=(3, 7))
    local_input_row = ttk.Frame(local_panel)
    local_input_row.pack(fill="x")
    local_input = ttk.Entry(local_input_row)
    local_input.pack(side="left", fill="x", expand=True, padx=(0, 5))
    local_send_button = ttk.Button(local_input_row, text="Send")
    local_send_button.pack(side="right")
    local_clear_button = ttk.Button(local_panel, text="Clear local chat")
    local_clear_button.pack(anchor="w", pady=(6, 0))

    api_provider_default = api_pref.get("provider", "Groq Cloud")
    if api_provider_default not in API_PROVIDERS:
        api_provider_default = "Groq Cloud"
    api_provider = tk.StringVar(value=api_provider_default)
    initial_api = API_PROVIDERS[api_provider_default]
    api_endpoint = tk.StringVar(value=api_pref.get("endpoint", initial_api["endpoint"]))
    api_model = tk.StringVar(value=api_pref.get("model", initial_api["model"]))
    api_key = tk.StringVar(value="")  # Memory only. Never saved to files or Shared Field.
    api_status = tk.StringVar(value="Disconnected")
    api_show_key = tk.BooleanVar(value=False)
    ttk.Label(api_panel, text="API AI  /  Cloud or custom", font=("Segoe UI", 14, "bold")).pack(anchor="w")
    # Compact rows leave enough vertical room for the API chat and Send bar.
    api_provider_row = ttk.Frame(api_panel)
    api_provider_row.pack(fill="x", pady=(7, 3))
    ttk.Label(api_provider_row, text="Provider", width=11).pack(side="left")
    api_provider_picker = ttk.Combobox(api_provider_row, values=list(API_PROVIDERS),
                                        textvariable=api_provider, state="readonly")
    api_provider_picker.pack(side="left", fill="x", expand=True)
    api_model_row = ttk.Frame(api_panel)
    api_model_row.pack(fill="x", pady=3)
    ttk.Label(api_model_row, text="Model ID", width=11).pack(side="left")
    ttk.Entry(api_model_row, textvariable=api_model).pack(side="left", fill="x", expand=True)
    api_endpoint_row = ttk.Frame(api_panel)
    api_endpoint_row.pack(fill="x", pady=3)
    ttk.Label(api_endpoint_row, text="Endpoint", width=11).pack(side="left")
    ttk.Entry(api_endpoint_row, textvariable=api_endpoint).pack(side="left", fill="x", expand=True)
    api_key_row = ttk.Frame(api_panel)
    api_key_row.pack(fill="x", pady=3)
    ttk.Label(api_key_row, text="API key", width=11).pack(side="left")
    api_key_entry = ttk.Entry(api_key_row, textvariable=api_key, show="*")
    api_key_entry.pack(side="left", fill="x", expand=True)
    ttk.Checkbutton(api_key_row, text="Show", variable=api_show_key,
                    command=lambda: api_key_entry.configure(show="" if api_show_key.get() else "*")).pack(side="left", padx=(4, 0))
    api_buttons = ttk.Frame(api_panel)
    api_buttons.pack(fill="x", pady=(3, 5))
    api_connect_button = ttk.Button(api_buttons, text="Connect")
    api_connect_button.pack(side="left", padx=(0, 5))
    api_disconnect_button = ttk.Button(api_buttons, text="Disconnect")
    api_disconnect_button.pack(side="left")
    ttk.Label(api_panel, textvariable=api_status, wraplength=400).pack(anchor="w", pady=(0, 6))
    ttk.Label(api_panel, text="API conversation", font=("Segoe UI", 10, "bold")).pack(anchor="w")
    api_chat = tk.Text(api_panel, state="disabled", height=12, wrap="word", font=("Segoe UI", 10))
    api_chat.pack(fill="both", expand=True, pady=(3, 7))
    api_input_row = ttk.Frame(api_panel)
    api_input_row.pack(fill="x")
    api_input = ttk.Entry(api_input_row)
    api_input.pack(side="left", fill="x", expand=True, padx=(0, 5))
    api_send_button = ttk.Button(api_input_row, text="Send")
    api_send_button.pack(side="right")
    api_clear_button = ttk.Button(api_panel, text="Clear API chat")
    api_clear_button.pack(anchor="w", pady=(6, 0))

    def chat_append(channel: str, speaker: str, content: str):
        text_widget = local_chat if channel == "local" else api_chat
        text_widget.configure(state="normal")
        text_widget.insert("end", f"{speaker}: {content}\n\n")
        text_widget.see("end")
        text_widget.configure(state="disabled")

    def chat_clear(channel: str):
        channels[channel]["history"] = []
        widget = local_chat if channel == "local" else api_chat
        set_readonly(widget, "")

    def update_resident_buttons():
        for channel, send_button, connect_button in (
            ("local", local_send_button, local_connect_button),
            ("api", api_send_button, api_connect_button),
        ):
            info = channels[channel]
            send_button.configure(state="normal" if info["connected"] and not info["busy"] else "disabled")
            connect_button.configure(state="disabled" if info["busy"] else "normal")

    def disconnect_resident(channel: str, *, silent: bool = False):
        info = channels[channel]
        info["generation"] += 1  # Ignore replies from any earlier connection/request.
        info["busy"] = False
        info["connected"] = False
        info["verified"] = False
        info["config"] = None
        label = "Local Resident" if channel == "local" else "API Resident"
        connected.pop(label, None)
        try:
            _resident_publish(channel, connected=False, state="disconnected",
                              provider="Ollama (local)" if channel == "local" else api_provider.get(),
                              model=local_model.get() if channel == "local" else api_model.get(),
                              endpoint=local_url.get() if channel == "local" else api_endpoint.get())
        except Exception as exc:
            if not silent:
                log(f"{label} state update failed: {exc}")
        (local_status if channel == "local" else api_status).set("Disconnected")
        if not silent:
            log(f"{label} disconnected")
        update_resident_buttons()
        refresh_home()

    def resident_worker(event_type: str, channel: str, generation: int, func, *args):
        """Network calls happen off the Tkinter thread; the main thread owns all widgets."""
        def work():
            try:
                result = func(*args)
                resident_events.put((event_type, channel, generation, True, result))
            except Exception as exc:
                resident_events.put((event_type, channel, generation, False, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def discover_local_models():
        base = local_url.get().strip()
        try:
            _validated_endpoint(base, local=True)
        except Exception as exc:
            local_status.set(str(exc))
            return
        local_status.set("Checking Ollama and installed models...")
        resident_worker("models", "local", channels["local"]["generation"],
                        _resident_ollama_models, base)

    def connect_local():
        disconnect_resident("local", silent=True)
        base = local_url.get().strip()
        wanted_model = local_model.get().strip()
        try:
            base = _validated_endpoint(base, local=True)
        except Exception as exc:
            local_status.set(str(exc))
            return
        info = channels["local"]
        info["busy"] = True
        info["pending_connect"] = {"endpoint": base, "model": wanted_model}
        local_status.set("Connecting to Ollama...")
        update_resident_buttons()
        resident_worker("connect", "local", info["generation"],
                        _resident_ollama_models, base)

    def connect_api():
        disconnect_resident("api", silent=True)
        provider_name = api_provider.get()
        model_name = api_model.get().strip()
        token = api_key.get().strip()
        try:
            endpoint = _validated_endpoint(api_endpoint.get())
            if not model_name:
                raise ValueError("Enter a model ID from your provider")
            if provider_name not in API_PROVIDERS:
                raise ValueError("Choose an API provider")
            if not token and provider_name != "Custom (OpenAI-compatible)":
                raise ValueError("Enter an API key (or use Custom for a local keyless server)")
            _resident_save_settings("api", {"provider": provider_name, "model": model_name,
                                           "endpoint": endpoint})
            # An HTTP chat API is stateless. Connect configures Monitor;
            # the first successful reply verifies remote credentials and model.
            _resident_publish("api", connected=False, state="configured-unverified",
                              provider=provider_name, model=model_name, endpoint=endpoint)
            info = channels["api"]
            info["connected"] = True
            info["verified"] = False
            info["config"] = {"provider": provider_name, "model": model_name,
                              "endpoint": endpoint, "key": token}
            info["history"] = []
            connected["API Resident"] = {"status": "Configured (not yet verified)"}
            api_status.set("Ready in Monitor • credentials verified on first Send")
            log("API Resident configured: " + provider_name)
        except Exception as exc:
            api_status.set(str(exc))
        update_resident_buttons()

    def resident_send(channel: str):
        info = channels[channel]
        entry = local_input if channel == "local" else api_input
        value = entry.get().strip()
        if not info["connected"] or info["busy"] or not value:
            return
        entry.delete(0, "end")
        chat_append(channel, "You", value)
        info["busy"] = True
        update_resident_buttons()
        history = info["history"][-18:] + [{"role": "user", "content": value}]
        config = info["config"].copy()
        gen = info["generation"]
        if channel == "local":
            local_status.set("Local AI responding...")
            resident_worker("reply", channel, gen, _resident_local_reply,
                            config["endpoint"], config["model"], history)
        else:
            api_status.set("API AI responding...")
            resident_worker("reply", channel, gen, _resident_api_reply,
                            config["provider"], config["endpoint"], config["model"],
                            config["key"], history)
        info["pending_history"] = history

    def on_api_provider_change(_event=None):
        if channels["api"]["connected"] or channels["api"]["busy"]:
            disconnect_resident("api", silent=True)
        defaults = API_PROVIDERS[api_provider.get()]
        api_endpoint.set(defaults["endpoint"])
        api_model.set(defaults["model"])
        api_key.set("")  # Do not carry a credential across providers.
        api_status.set("Disconnected • enter provider credentials and Connect")

    api_provider_picker.bind("<<ComboboxSelected>>", on_api_provider_change)
    local_connect_button.configure(command=connect_local)
    local_disconnect_button.configure(command=lambda: disconnect_resident("local"))
    local_discover_button.configure(command=discover_local_models)
    local_send_button.configure(command=lambda: resident_send("local"))
    local_input.bind("<Return>", lambda _e: (resident_send("local"), "break")[-1])
    local_clear_button.configure(command=lambda: chat_clear("local"))
    api_connect_button.configure(command=connect_api)
    api_disconnect_button.configure(command=lambda: disconnect_resident("api"))
    api_send_button.configure(command=lambda: resident_send("api"))
    api_input.bind("<Return>", lambda _e: (resident_send("api"), "break")[-1])
    api_clear_button.configure(command=lambda: chat_clear("api"))

    def resident_poll():
        try:
            while True:
                event_type, channel, gen, ok, response = resident_events.get_nowait()
                info = channels[channel]
                if gen != info["generation"]:
                    continue  # Disconnected or reconfigured while request was pending.
                if event_type == "models":
                    if ok:
                        local_models["values"] = response
                        if not local_model.get().strip() and response:
                            local_model.set(response[0])
                        local_status.set(f"Ollama reachable • {len(response)} model(s) installed")
                    else:
                        local_status.set("Ollama discovery failed: " + response)
                elif event_type == "connect" and channel == "local":
                    info["busy"] = False
                    if not ok:
                        local_status.set("Ollama connection failed: " + response)
                    else:
                        local_models["values"] = response
                        wanted = info.get("pending_connect", {}).get("model", "")
                        if not response:
                            local_status.set("Ollama found, but no models installed")
                        elif wanted and wanted not in response:
                            local_status.set(f"Model '{wanted}' not installed. Choose from Find models.")
                        else:
                            chosen = wanted or response[0]
                            base = info.get("pending_connect", {}).get("endpoint", LOCAL_DEFAULT_URL)
                            try:
                                _resident_save_settings("local", {"provider": "Ollama (local)",
                                      "model": chosen, "endpoint": base})
                                _resident_publish("local", connected=True, state="connected",
                                      provider="Ollama (local)", model=chosen, endpoint=base)
                                local_model.set(chosen)
                                info["connected"] = True
                                info["verified"] = True
                                info["config"] = {"endpoint": base, "model": chosen}
                                info["history"] = []
                                connected["Local Resident"] = {"status": "Ollama verified"}
                                local_status.set("Connected • " + chosen + " (Ollama reachable)")
                                log("Local Resident connected: " + chosen)
                            except Exception as exc:
                                local_status.set("Local Resident setup failed: " + str(exc))
                elif event_type == "reply":
                    info["busy"] = False
                    if ok:
                        info["history"] = info.get("pending_history", []) + [
                            {"role": "assistant", "content": response}]
                        info["history"] = info["history"][-20:]
                        chat_append(channel, "Local AI" if channel == "local" else "API AI", response)
                        if channel == "local":
                            local_status.set("Connected • " + info["config"]["model"])
                        else:
                            info["verified"] = True
                            c = info["config"]
                            connected["API Resident"] = {"status": "API verified"}
                            api_status.set("Connected • verified response from " + c["provider"])
                            _resident_publish("api", connected=True, state="connected",
                                  provider=c["provider"], model=c["model"], endpoint=c["endpoint"])
                        refresh_home()
                    else:
                        chat_append(channel, "Connection error", response)
                        (local_status if channel == "local" else api_status).set("Request failed: " + response)
                        if channel == "api":
                            info["verified"] = False
                            connected["API Resident"] = {"status": "Configured (request failed)"}
                            c = info["config"]
                            _resident_publish("api", connected=False, state="error",
                                  provider=c["provider"], model=c["model"], endpoint=c["endpoint"])
                # Always refresh controls after ANY result, including Connect.
                update_resident_buttons()
        except queue.Empty:
            pass
        except Exception as exc:
            log(f"Resident result handling: {exc}")
        app.after(100, resident_poll)

    update_resident_buttons()
    app.after(100, resident_poll)


    # BUILDER: five independent creation modes, each with its own editable preprompt.
    builder = pages["Builder"]
    header(builder, "DINS Builder", "Choose what to create. Each option opens its own planning and step-injection window.")
    ttk.Label(builder, text="The connected Local AI or API AI writes a numbered plan. "
              "Builder then injects its steps one by one with your selected interval.",
              wraplength=900).pack(anchor="w", pady=(0, 16))
    builder_choice_frame = ttk.Frame(builder)
    builder_choice_frame.pack(fill="both", expand=True)
    ttk.Label(builder_choice_frame, text="WHAT WOULD YOU LIKE TO CREATE?",
              font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(4, 10))
    builder_options = {
        "Coding": "Create or modify software projects, scripts and README files",
        "Story": "Storytelling application or interactive story",
        "Routine": "Small routine, utility or automation application",
        "Music": "Music-related application or player",
        "Video": "Video-related application or tool",
    }

    def builder_open(choice: str):
        window = tk.Toplevel(app)
        window.title("DINS Builder / " + choice)
        window.geometry("1000x830")
        window.minsize(790, 610)
        body = ttk.Frame(window, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="DINS Builder / " + choice,
                  font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(body, text=builder_options[choice]).pack(anchor="w", pady=(1, 7))

        # Keep the adjustable prescript and the response panel visible even on a small laptop.
        top = ttk.LabelFrame(body, text="Preloaded preprompt (editable)", padding=7)
        top.pack(fill="x", pady=(1, 7))
        prescript = tk.Text(top, height=10, wrap="word", undo=True)
        prescript.pack(fill="x", expand=False)
        prescript.insert("1.0", BUILDER_DEFAULT_PROMPT)
        ttk.Button(top, text="Restore default preprompt",
                   command=lambda: (prescript.delete("1.0", "end"),
                                    prescript.insert("1.0", BUILDER_DEFAULT_PROMPT))).pack(anchor="e", pady=(5, 0))

        config_row = ttk.Frame(body)
        config_row.pack(fill="x", pady=(2, 5))
        os_var = tk.StringVar(value="Windows")
        sysram_var = tk.StringVar(value="8 GB")
        appram_var = tk.StringVar(value="512 MB")
        route_var = tk.StringVar(value="Local AI")
        interval_var = tk.StringVar(value="3")
        project_var = tk.StringVar(value=choice.lower() + "_project")

        def labeled_combo(parent, title, variable, choices, width=16, readonly=False):
            part = ttk.Frame(parent)
            part.pack(side="left", padx=(0, 9))
            ttk.Label(part, text=title).pack(anchor="w")
            widget = ttk.Combobox(part, textvariable=variable, values=choices, width=width,
                                  state="readonly" if readonly else "normal")
            widget.pack(anchor="w", pady=(2, 0))
            return widget

        labeled_combo(config_row, "Operating system", os_var,
                      ["Windows", "Linux", "macOS"], width=15, readonly=True)
        labeled_combo(config_row, "System RAM", sysram_var,
                      ["1 GB", "2 GB", "4 GB", "8 GB", "16 GB", "32 GB"], width=12)
        labeled_combo(config_row, "App RAM limit", appram_var,
                      ["64 MB", "128 MB", "256 MB", "512 MB", "1024 MB", "2048 MB"], width=13)
        labeled_combo(config_row, "AI destination", route_var,
                      ["Local AI", "API AI"], width=14, readonly=True)

        second_row = ttk.Frame(body)
        second_row.pack(fill="x", pady=(0, 6))
        project_group = ttk.Frame(second_row)
        project_group.pack(side="left", fill="x", expand=True, padx=(0, 14))
        ttk.Label(project_group, text="Project folder name (under data/builder_projects)").pack(anchor="w")
        ttk.Entry(project_group, textvariable=project_var, width=45).pack(fill="x", pady=(2, 0))
        labeled_combo(second_row, "Interval between steps (seconds)", interval_var,
                      ["0", "1", "1.2", "3", "5", "13", "30"], width=14)

        ttk.Label(body, text="Your application request").pack(anchor="w")
        user_prompt = tk.Text(body, height=4, wrap="word", undo=True)
        user_prompt.pack(fill="x", pady=(2, 6))

        control_row = ttk.Frame(body)
        control_row.pack(fill="x", pady=(2, 5))
        plan_button = ttk.Button(control_row, text="1. Ask AI for numbered steps")
        plan_button.pack(side="left", padx=(0, 7))
        start_button = ttk.Button(control_row, text="2. Inject steps", state="disabled")
        start_button.pack(side="left", padx=(0, 7))
        stop_button = ttk.Button(control_row, text="Stop", state="disabled")
        stop_button.pack(side="left", padx=(0, 7))
        verify_button = ttk.Button(control_row, text="Verify files")
        verify_button.pack(side="left")
        stage = tk.StringVar(value="Connect a Resident, enter a request, then ask for steps.")
        ttk.Label(body, textvariable=stage, wraplength=920).pack(anchor="w", pady=(0, 7))

        output_panes = ttk.Panedwindow(body, orient="vertical")
        output_panes.pack(fill="both", expand=True)
        plan_frame = ttk.LabelFrame(output_panes, text="AI plan (editable; numbered line, blank line, next step)", padding=5)
        reply_frame = ttk.LabelFrame(output_panes, text="Builder activity / AI replies", padding=5)
        output_panes.add(plan_frame, weight=2)
        output_panes.add(reply_frame, weight=3)
        plan_view = tk.Text(plan_frame, wrap="word", undo=True, height=6)
        plan_view.pack(fill="both", expand=True)
        activity = tk.Text(reply_frame, wrap="word", height=8, state="disabled")
        activity.pack(fill="both", expand=True)

        job = {"generation": 0, "busy": False, "running": False, "steps": [],
               "step_index": 0, "route": None, "config": None, "connection_generation": None,
               "folder": None, "context": "", "preprompt": "", "settings": {},
               "interval": 3.0, "history": [], "pending_prompt": ""}
        builder_events: queue.Queue = queue.Queue()

        def activity_line(value: str):
            activity.configure(state="normal")
            activity.insert("end", value.rstrip() + "\n\n")
            activity.see("end")
            activity.configure(state="disabled")

        def control_state():
            planning = job["busy"]
            plan_button.configure(state="disabled" if planning or job["running"] else "normal")
            start_button.configure(state="disabled" if planning or job["running"]
                                   or not plan_view.get("1.0", "end-1c").strip() else "normal")
            stop_button.configure(state="normal" if planning or job["running"] else "disabled")

        def validate_inputs():
            prompt = user_prompt.get("1.0", "end-1c").strip()
            if not prompt:
                raise ValueError("Enter a request for the application")
            folder_name = project_var.get().strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,70}", folder_name):
                raise ValueError("Project folder name may contain letters, digits, hyphens and underscores")
            # A plain numeric field is more useful than fixing the user's machine to presets.
            def check_ram(value, unit):
                match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(GB|MB)\s*", value, flags=re.I)
                if not match or float(match.group(1)) <= 0:
                    raise ValueError(f"Enter a positive {unit} RAM amount such as 4 GB or 512 MB")
                return float(match.group(1)) * (1024 if match.group(2).upper() == "GB" else 1)
            system_mb = check_ram(sysram_var.get(), "system")
            application_mb = check_ram(appram_var.get(), "application")
            if application_mb > system_mb:
                raise ValueError("Application memory limit cannot exceed total system RAM")
            try:
                seconds = float(interval_var.get())
            except ValueError:
                raise ValueError("Interval must be a number of seconds") from None
            if not 0 <= seconds <= 300:
                raise ValueError("Interval must be between 0 and 300 seconds")
            channel = "local" if route_var.get() == "Local AI" else "api"
            resident_info = channels[channel]
            if not resident_info["connected"] or not resident_info["config"]:
                raise ValueError("Connect the selected AI in the Resident tab first")
            return {
                "request": prompt, "os": os_var.get(), "system_ram": sysram_var.get(),
                "app_ram": appram_var.get(), "route": channel, "interval": seconds,
                "folder": BUILDER_PROJECTS / folder_name,
                "preprompt": prescript.get("1.0", "end-1c").strip(),
                "resident_config": resident_info["config"].copy(),
                "connection_generation": resident_info["generation"],
                "category": choice,
            }

        def context_text(values):
            return (f"MODE: {values['category']}\nTARGET OS: {values['os']}\n"
                    f"SYSTEM RAM: {values['system_ram']}\nAPPLICATION RAM LIMIT: {values['app_ram']}\n"
                    f"PROJECT WORKSPACE: {values['folder'].name}\n"
                    f"USER REQUEST:\n{values['request']}")

        def send_builder_ai(phase: str, messages: list[dict]):
            run_id = job["generation"]
            channel = job["route"]
            settings = job["config"].copy()

            def work():
                try:
                    if channel == "local":
                        answer = _resident_local_reply(settings["endpoint"], settings["model"], messages)
                    else:
                        answer = _resident_api_reply(settings["provider"], settings["endpoint"],
                                                      settings["model"], settings["key"], messages)
                    builder_events.put((run_id, phase, True, answer))
                except Exception as exc:
                    builder_events.put((run_id, phase, False, str(exc)))
            threading.Thread(target=work, daemon=True).start()

        def request_plan():
            try:
                values = validate_inputs()
            except ValueError as exc:
                messagebox.showerror("DINS Builder", str(exc), parent=window)
                return
            job["generation"] += 1
            job["busy"] = True
            job["running"] = False
            job["route"] = values["route"]
            job["config"] = values["resident_config"]
            job["connection_generation"] = values["connection_generation"]
            job["folder"] = values["folder"]
            job["context"] = context_text(values)
            job["preprompt"] = values["preprompt"]
            job["interval"] = values["interval"]
            job["settings"] = values
            job["history"] = []
            plan_view.delete("1.0", "end")
            stage.set("Planning with " + ("Local AI" if job["route"] == "local" else "API AI") + "...")
            activity_line(f"REQUEST: {values['request']}\n{job['context']}")
            control_state()
            instruction = (job["preprompt"] + "\n\n" + job["context"] +
                           "\n\nPLAN MODE: Design the application in as many small sequential steps as needed. "
                           "Include folder setup, actual files and README, targeted changes if appropriate, "
                           "and verification. Do NOT say anything has already been created. "
                           "Return ONLY consecutive numbered single-line instructions starting with "
                           "'1. ' and separated by one blank line. No other text.")
            send_builder_ai("plan", [{"role": "user", "content": instruction}])

        def start_steps():
            try:
                steps = builder_parse_steps(plan_view.get("1.0", "end-1c"))
                # Preserve the same AI, model, folder and system constraints from planning.
                if job["folder"] is None:
                    raise ValueError("Ask the AI for a plan first")
                if not channels[job["route"]]["connected"] or (channels[job["route"]]["generation"]
                     != job["connection_generation"]):
                    raise ValueError("Resident connection changed. Generate a new plan first")
            except ValueError as exc:
                messagebox.showerror("Builder steps", str(exc), parent=window)
                return
            if not messagebox.askyesno("Start injection?",
                   f"Inject {len(steps)} steps to the selected AI?\n\n"
                   "Builder will ask before writing each set of files. Generated scripts will not run automatically.",
                   parent=window):
                return
            job["steps"] = steps
            job["step_index"] = 0
            job["running"] = True
            job["busy"] = False
            job["history"] = []
            activity_line(f"APPROVED PLAN: {len(steps)} step(s). Target folder: {job['folder']}")
            control_state()
            run_next_step()

        def run_next_step():
            if not job["running"] or not window.winfo_exists():
                return
            if not channels[job["route"]]["connected"] or (channels[job["route"]]["generation"]
                   != job["connection_generation"]):
                job["running"] = False
                stage.set("Resident disconnected or changed; injection stopped.")
                control_state()
                return
            index = job["step_index"]
            if index >= len(job["steps"]):
                job["running"] = False
                stage.set(f"All {len(job['steps'])} instructions processed. Check the verification results.")
                activity_line("FINAL STATIC CHECK\n" + builder_verify_files(job["folder"]))
                log(f"Builder {choice} completed {len(job['steps'])} injected steps")
                control_state()
                return
            text = job["steps"][index]
            job["busy"] = True
            stage.set(f"Injecting step {index + 1} / {len(job['steps'])} to selected AI...")
            activity_line(f"STEP {index + 1}/{len(job['steps'])}: {text}")
            control_state()
            # Conversation is kept in Builder, never mixed into the Resident chat.
            previous = "\n".join(job["history"][-10:])
            instruction = (job["preprompt"] + "\n\n" + job["context"] +
                           f"\n\nFULL APPROVED PLAN:\n" +
                           "\n\n".join(f"{n}. {x}" for n, x in enumerate(job["steps"], 1)) +
                           f"\n\nCOMPLETED PREVIOUS STEP RESULTS:\n{previous or '(none)'}" +
                           "\n\nEXISTING WORKSPACE FILE CONTENT:\n" +
                           builder_workspace_context(job["folder"]) +
                           f"\n\nCOMPLETE ONLY STEP {index + 1}: {text}\n\n"
                           "Reply ONLY as a JSON object: "
                           '{"actions":[{"op":"mkdir","path":"subfolder"},'
                           '{"op":"write","path":"subfolder/file.py","content":"complete file text"}],'
                           '"report":"short description"}. '
                           "You may return an empty actions list if the step requires no file changes. "
                           "All paths MUST be relative to the project workspace, use / separators. "
                           "Never use absolute paths, delete commands or shell commands. "
                           "For code edits, provide the full corrected file content, preserving unrelated code. "
                           "For verification, examine the supplied existing files and report only what "
                           "you actually checked. Do not claim code was run, runtime tested or RAM measured.")
            send_builder_ai("step", [{"role": "user", "content": instruction}])

        def stop_run():
            job["generation"] += 1  # Ignore responses that arrive after Stop.
            job["busy"] = False
            job["running"] = False
            stage.set("Injection stopped. Files from completed steps remain on disk.")
            activity_line("STOP requested by operator.")
            control_state()

        def verify_now():
            name = project_var.get().strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,70}", name):
                messagebox.showerror("DINS Builder", "Enter a valid project folder name", parent=window)
                return
            root = BUILDER_PROJECTS / name
            activity_line("MANUAL STATIC CHECK\n" + builder_verify_files(root))

        def poll_builder_events():
            if not window.winfo_exists():
                return
            try:
                while True:
                    run_id, phase, ok, reply = builder_events.get_nowait()
                    if run_id != job["generation"]:
                        continue
                    job["busy"] = False
                    if not ok:
                        job["running"] = False
                        stage.set(f"AI {phase} request failed: {reply}")
                        activity_line(f"ERROR ({phase}): {reply}")
                        control_state()
                        continue
                    if phase == "plan":
                        plan_view.delete("1.0", "end")
                        plan_view.insert("1.0", reply)
                        try:
                            count = len(builder_parse_steps(reply))
                            stage.set(f"AI proposed {count} steps. Review or edit them, then click Inject steps.")
                        except ValueError as exc:
                            stage.set(f"AI's step format needs correction: {exc}")
                        activity_line("AI PLAN RETURNED:\n" + reply)
                        control_state()
                    elif phase == "step":
                        activity_line("AI STEP REPLY:\n" + reply[:9000])
                        try:
                            actions, report = builder_decode_actions(reply)
                            # Validate all paths BEFORE asking permission, and reveal overwrites.
                            paths = []
                            for action in actions:
                                destination = builder_project_path(job["folder"], action["path"])
                                action_desc = action["op"].upper() + " " + action["path"]
                                if action["op"] == "write" and destination.exists():
                                    action_desc += " [OVERWRITE EXISTING FILE]"
                                paths.append(action_desc)
                            if actions:
                                summary = "\n".join(paths)
                                if len(summary) > 1800:
                                    summary = summary[:1800] + "..."
                                approved = messagebox.askyesno(
                                    "Approve Builder file actions?",
                                    f"Step {job['step_index'] + 1} proposes:\n\n{summary}\n\n"
                                    "Approve these file changes?", parent=window)
                                if not approved:
                                    job["running"] = False
                                    stage.set("Changes declined. Injection stopped; no actions applied for this step.")
                                    activity_line("OPERATOR DECLINED FILE ACTIONS")
                                    control_state()
                                    continue
                            actual = builder_apply_actions(job["folder"], actions) if actions else []
                        except (ValueError, OSError, TypeError) as exc:
                            job["running"] = False
                            stage.set(f"Step {job['step_index'] + 1} could not be applied: {exc}")
                            activity_line("ACTION ERROR: " + str(exc))
                            control_state()
                            continue
                        outcome = "; ".join(actual) if actual else "No file changes"
                        activity_line("CONFIRMED ACTIONS: " + outcome + "\nAI REPORT: " + report)
                        job["history"].append(f"Step {job['step_index'] + 1}: {outcome}; AI said: {report}")
                        job["step_index"] += 1
                        if job["running"]:
                            seconds = job["interval"] if job["step_index"] < len(job["steps"]) else 0
                            stage.set(f"Step {job['step_index']} complete. Next step in {seconds:g} seconds...")
                            window.after(int(seconds * 1000), run_next_step)
                        control_state()
            except queue.Empty:
                pass
            window.after(120, poll_builder_events)

        plan_button.configure(command=request_plan)
        start_button.configure(command=start_steps)
        stop_button.configure(command=stop_run)
        verify_button.configure(command=verify_now)
        control_state()
        window.after(120, poll_builder_events)

        def close_builder():
            job["generation"] += 1
            window.destroy()
        window.protocol("WM_DELETE_WINDOW", close_builder)

    for choice, description in builder_options.items():
        row = ttk.Frame(builder_choice_frame)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text=choice, width=22,
                   command=lambda selected=choice: builder_open(selected)).pack(side="left", padx=(0, 16))
        ttk.Label(row, text=description).pack(side="left")

    # ROBOTICS: tab auto-loads preselected slots, checks readiness, THEN applies profile.
    robotics = pages["Robotics"]
    header(robotics, "Robotics", "Selected modules first, readiness confirmation second, robotics profile third")
    slot_area = ttk.LabelFrame(robotics, text="Module slots", padding=10)
    slot_area.pack(fill="both", expand=True)
    robotics_status = tk.StringVar(value="Open Robotics to load the preselected modules")
    ttk.Label(robotics, textvariable=robotics_status, wraplength=950).pack(anchor="w", pady=(10, 7))
    slots = robotics_slots()
    slot_vars: dict[str, Any] = {}
    slot_status: dict[str, Any] = {}
    robotics_generation = 0
    applied_robotics = False

    def save_slot_choices():
        for s in slots:
            if s["name"] in slot_vars:
                s["selected"] = bool(slot_vars[s["name"]].get())
        save_robotics_slots(slots)

    def rebuild_slot_rows():
        for child in slot_area.winfo_children():
            child.destroy()
        slot_vars.clear()
        slot_status.clear()
        for s in slots:
            row = ttk.Frame(slot_area)
            row.pack(fill="x", pady=3)
            checked = tk.BooleanVar(value=s["selected"])
            slot_vars[s["name"]] = checked
            ttk.Checkbutton(row, text=s["name"], variable=checked,
                            command=save_slot_choices).pack(side="left")
            ttk.Label(row, text=s["path"], foreground="#666666").pack(side="left", padx=15)
            indicator = tk.StringVar(value="Ready to select" if s["selected"] else "Optional")
            slot_status[s["name"]] = indicator
            ttk.Label(row, textvariable=indicator, wraplength=320).pack(side="right")

    rebuild_slot_rows()
    custom_area = ttk.Frame(robotics)
    custom_area.pack(fill="x", pady=(5, 8))
    custom_name = tk.StringVar()
    custom_path = tk.StringVar(value="modules/")
    ttk.Label(custom_area, text="Extra slot name").pack(side="left")
    ttk.Entry(custom_area, width=16, textvariable=custom_name).pack(side="left", padx=4)
    ttk.Label(custom_area, text="Module file").pack(side="left")
    ttk.Entry(custom_area, width=34, textvariable=custom_path).pack(side="left", padx=4)

    def add_custom_slot():
        name = custom_name.get().strip()
        raw = custom_path.get().strip().replace("\\", "/")
        if not name or any(x["name"].casefold() == name.casefold() for x in slots):
            messagebox.showerror("Robotics", "Enter a unique slot name")
            return
        try:
            _safe_relative_file(raw)
            slots.append({"name": name, "path": raw, "selected": True})
            save_robotics_slots(slots)
            rebuild_slot_rows()
            log(f"Robotics slot added: {name}")
        except Exception as exc:
            message_error("Add Robotics slot", exc)

    ttk.Button(custom_area, text="Add slot", command=add_custom_slot).pack(side="left")

    def load_robotics():
        nonlocal robotics_generation, applied_robotics
        robotics_generation += 1
        gen = robotics_generation
        applied_robotics = False
        save_slot_choices()
        selected = [s for s in slots if s["selected"]]
        if not selected:
            robotics_status.set("No modules selected. Select one or more slots.")
            return
        robotics_status.set(f"Loading {len(selected)} selected module(s)...")
        failed = []
        for s in selected:
            slot_status[s["name"]].set("Queued")

        def load_next(index=0):
            nonlocal applied_robotics
            if gen != robotics_generation:
                return
            if index < len(selected):
                slot = selected[index]
                name = slot["name"]
                slot_status[name].set("Loading...")
                app.update_idletasks()
                try:
                    plugin = activate_module(slot)
                    module_plugins[name] = plugin
                    connected[name] = plugin
                    slot_status[name].set("Connected")
                    log(f"Robotics module connected: {name}")
                except Exception as exc:
                    failed.append(name)
                    connected.pop(name, None)
                    module_plugins.pop(name, None)
                    slot_status[name].set(str(exc))
                    log(f"Robotics: {exc}")
                app.after(30, lambda: load_next(index + 1))
                return
            refresh_operator_choices()
            if failed:
                robotics_status.set(f"{len(failed)} module(s) not ready: " + ", ".join(failed) +
                                    ". Robotics profile was not applied.")
                return
            try:
                if "Template Bridge" not in connected:
                    raise RuntimeError("Template Bridge is not connected")
                apply_template("robotics")
                applied_robotics = True
                robotics_status.set("All selected modules connected. Robotics profile applied.")
                log("Robotics profile applied after module readiness")
            except Exception as exc:
                robotics_status.set(f"Modules connected; robotics profile unavailable: {exc}")
                log(f"Robotics profile: {exc}")

        load_next()

    robotics_buttons = ttk.Frame(robotics)
    robotics_buttons.pack(fill="x", pady=(5, 0))
    ttk.Button(robotics_buttons, text="Load selected modules", command=load_robotics).pack(side="left", padx=(0, 8))

    def capture_robotics():
        try:
            if not messagebox.askyesno("Capture Robotics profile", "Save current Shared Field as the Robotics profile?"):
                return
            path = capture_template("robotics")
            log("Robotics profile captured")
            messagebox.showinfo("Robotics", f"Profile saved:\n{path}")
        except Exception as exc:
            message_error("Capture Robotics profile", exc)

    ttk.Button(robotics_buttons, text="Capture Robotics profile", command=capture_robotics).pack(side="left")

    # MEMORY SETUP: visible storage settings; original Block Workshop kept as Advanced.
    memory = pages["Memory Setup"]
    header(memory, "Memory Setup", "Memory locations, snapshots and persistent Shared Field blocks")
    config = _load_json(MEMORY_CONFIG, {
        "resident_memory_path": "data/memory/resident", "resident_memory_enabled": False})
    memory_enabled = tk.BooleanVar(value=bool(config.get("resident_memory_enabled", False)))
    memory_path = tk.StringVar(value=str(config.get("resident_memory_path", "data/memory/resident")))
    ttk.Checkbutton(memory, text="Enable Resident memory when connected", variable=memory_enabled).pack(anchor="w")
    ttk.Label(memory, text="Resident memory folder (relative to Monitor)").pack(anchor="w", pady=(8, 2))
    ttk.Entry(memory, textvariable=memory_path, width=70).pack(anchor="w")
    ttk.Label(memory, text="Shared Field remains separate from the Resident's experience memory.",
              wraplength=900).pack(anchor="w", pady=(10, 5))

    def save_memory_config():
        try:
            relative = memory_path.get().strip().replace("\\", "/")
            location = (ROOT / relative).resolve()
            if Path(relative).is_absolute() or not location.is_relative_to(ROOT) or location == ROOT:
                raise ValueError("Choose a folder inside this installation")
            location.mkdir(parents=True, exist_ok=True)
            _save_json(MEMORY_CONFIG, {"resident_memory_path": relative,
                                       "resident_memory_enabled": bool(memory_enabled.get())})
            log("Memory configuration saved")
        except Exception as exc:
            message_error("Save Memory Setup", exc)

    ttk.Button(memory, text="Save memory setup", command=save_memory_config).pack(anchor="w", pady=(7, 12))
    stored_profiles = tk.StringVar(value="")

    def list_profiles():
        try:
            found = bridge_module().list_profiles()
            stored_profiles.set(", ".join(r["name"] for r in found if r.get("saved")) or "No saved profiles")
        except Exception as exc:
            stored_profiles.set(str(exc))

    ttk.Button(memory, text="Refresh saved snapshots", command=list_profiles).pack(anchor="w")
    ttk.Label(memory, textvariable=stored_profiles, wraplength=920).pack(anchor="w", pady=(4, 6))
    list_profiles()
    show_advanced = tk.BooleanVar(value=False)
    advanced = ttk.LabelFrame(memory, text="Advanced: Shared Field block registry", padding=8)

    def toggle_advanced():
        if show_advanced.get():
            advanced.pack(fill="both", expand=True, pady=(6, 0))
        else:
            advanced.pack_forget()

    ttk.Checkbutton(memory, text="Show advanced block tools", variable=show_advanced,
                    command=toggle_advanced).pack(anchor="w", pady=(8, 3))
    advanced_row = ttk.Frame(advanced)
    advanced_row.pack(fill="x")
    code_var = tk.StringVar(value="DINS.EXAMPLE.MODULE")
    number_var = tk.StringVar(value="007")
    marker_var = tk.StringVar(value="identity_markers/007-a.json")
    for title, var, width in (("Connection code", code_var, 37), ("Module number", number_var, 9),
                              ("Birth marker", marker_var, 36)):
        ttk.Label(advanced_row, text=title).pack(side="left", padx=(0, 3))
        ttk.Entry(advanced_row, width=width, textvariable=var).pack(side="left", padx=(0, 9))
    block_payload = tk.Text(advanced, height=4, wrap="none")
    block_payload.insert("1.0", '{"settings": {}}')
    block_payload.pack(fill="x", pady=(6, 4))
    block_result = tk.Text(advanced, height=6, state="disabled", wrap="none")
    block_result.pack(fill="both", expand=True, pady=(5, 0))
    block_actions = ttk.Frame(advanced)
    block_actions.pack(fill="x", pady=(4, 0))

    def block_value():
        content = json.loads(block_payload.get("1.0", "end-1c"))
        if not isinstance(content, dict):
            raise ValueError("Module block must be a JSON object")
        return content

    def do_block(op: str):
        try:
            field = field_module()
            if op == "create":
                import block_registry
                marker = (ROOT / marker_var.get()).resolve()
                if not marker.is_relative_to(ROOT) or marker == ROOT or Path(marker_var.get()).is_absolute():
                    raise ValueError("Marker must stay inside Monitor folder")
                result = block_registry.claim(number_var.get().strip(),
                                              block_registry.birth_marker(marker), block_value())
                code_var.set(result["connection_code"])
            elif op == "expand":
                if field.get_block(code_var.get(), default=None) is None:
                    raise ValueError("Register the block first")
                result = field.update_block(code_var.get(), block_value())
            elif op == "inspect":
                result = field.get_block(code_var.get(), default=None)
            else:
                result = sorted(field.load_field()["blocks"])
            set_readonly(block_result, json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as exc:
            message_error("Block registry", exc)

    for title, action in (("Register", "create"), ("Expand", "expand"),
                          ("Inspect", "inspect"), ("List blocks", "list")):
        ttk.Button(block_actions, text=title, command=lambda a=action: do_block(a)).pack(side="left", padx=(0, 6))

    # SCRIPT AUTOMATION: create/save scripts; explicit human click executes drafts.
    scripts = pages["Script Automation"]
    header(scripts, "Script Automation", "Edit, save and manually run Python, CMD or PowerShell scripts")
    script_row = ttk.Frame(scripts)
    script_row.pack(fill="x", pady=(0, 8))
    script_language = tk.StringVar(value="Python")
    script_name = tk.StringVar(value="new_script")
    ttk.Label(script_row, text="Language").pack(side="left")
    ttk.Combobox(script_row, values=("Python", "CMD", "PowerShell"), width=13,
                 state="readonly", textvariable=script_language).pack(side="left", padx=(5, 12))
    ttk.Label(script_row, text="Name").pack(side="left")
    ttk.Entry(script_row, width=34, textvariable=script_name).pack(side="left", padx=(5, 12))
    script_editor = tk.Text(scripts, wrap="none", undo=True, height=13, font=("Consolas", 10))
    script_editor.pack(fill="both", expand=True)
    script_output = tk.Text(scripts, wrap="word", height=10, state="disabled", font=("Consolas", 10))
    script_output.pack(fill="both", expand=True, pady=(8, 0))
    script_controls = ttk.Frame(scripts)
    script_controls.pack(fill="x", pady=(8, 3))
    running_script: dict[str, Any] = {"process": None}
    results_queue: queue.Queue = queue.Queue()

    def save_script():
        path = safe_script_path(script_name.get(), script_language.get())
        if path.exists() and not messagebox.askyesno("Replace script?", f"Overwrite {path.name}?"):
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(script_editor.get("1.0", "end-1c"), encoding="utf-8")
        log(f"Script saved: {path.name}")
        return path

    def load_script():
        try:
            path = safe_script_path(script_name.get(), script_language.get())
            script_editor.delete("1.0", "end")
            script_editor.insert("1.0", path.read_text(encoding="utf-8"))
        except Exception as exc:
            message_error("Load script", exc)

    def script_cmd(path: Path, lang: str) -> list[str]:
        if lang == "Python":
            return [sys.executable, str(path)]
        if lang == "CMD":
            cmd = os.environ.get("ComSpec") or shutil.which("cmd.exe")
            if not cmd:
                raise RuntimeError("CMD is available only on Windows")
            return [cmd, "/d", "/c", str(path)]
        shell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if not shell:
            raise RuntimeError("PowerShell not found")
        return [shell, "-NoProfile", "-File", str(path)]

    def run_script():
        if running_script["process"] is not None:
            messagebox.showinfo("Script Automation", "A script is already running")
            return
        try:
            path = safe_script_path(script_name.get(), script_language.get())
            if not path.is_file():
                raise FileNotFoundError("Save the script first")
            if path.read_text(encoding="utf-8") != script_editor.get("1.0", "end-1c"):
                raise ValueError("Save your changes before running")
            if not messagebox.askyesno("Run script?", f"Execute {path.name} on this computer now?"):
                return
            cmd = script_cmd(path, script_language.get())
            process = subprocess.Popen(cmd, cwd=str(SCRIPTS), stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, errors="replace")
            running_script["process"] = process
            set_readonly(script_output, f"Running {path.name}...\n")
            log(f"Script started: {path.name}")

            def wait_job():
                output, _ = process.communicate()
                results_queue.put((process, path.name, process.returncode, output))

            threading.Thread(target=wait_job, daemon=True).start()
        except Exception as exc:
            message_error("Run script", exc)

    def stop_script():
        process = running_script["process"]
        if process is not None and process.poll() is None:
            process.terminate()
            log("Script stop requested")

    def poll_results():
        try:
            while True:
                process, name, rc, output = results_queue.get_nowait()
                if running_script["process"] is process:
                    running_script["process"] = None
                set_readonly(script_output, (output or "(no output)") + f"\nExit code: {rc}\n")
                log(f"Script finished: {name}, code {rc}")
        except queue.Empty:
            pass
        app.after(250, poll_results)

    poll_results()
    for label, callback in (("Save", save_script), ("Load", load_script),
                            ("Run now", run_script), ("Stop", stop_script)):
        ttk.Button(script_controls, text=label, command=callback).pack(side="left", padx=(0, 8))

    # MANUAL OPERATOR: use the same already connected modules, no duplicate driver.
    operator = pages["Manual Operator"]
    header(operator, "Manual Operator", "Send commands to connected modules with operator controls")
    operator_module = tk.StringVar()
    operator_action = tk.StringVar()
    ttk.Label(operator, text="Connected module").pack(anchor="w")
    operator_picker = ttk.Combobox(operator, state="readonly", textvariable=operator_module, width=52)
    operator_picker.pack(anchor="w", pady=(3, 10))
    ttk.Label(operator, text="Module action").pack(anchor="w")
    action_picker = ttk.Combobox(operator, state="readonly", textvariable=operator_action, width=52)
    action_picker.pack(anchor="w", pady=(3, 10))
    ttk.Label(operator, text="Action arguments (JSON object)").pack(anchor="w")
    action_args = tk.Text(operator, height=7, wrap="word")
    action_args.insert("1.0", "{}")
    action_args.pack(fill="x", pady=(4, 9))
    operator_output = tk.Text(operator, state="disabled", height=13, wrap="word")
    operator_output.pack(fill="both", expand=True)

    def operator_actions(_event=None):
        plugin = module_plugins.get(operator_module.get())
        actions = []
        if plugin is not None and hasattr(plugin, "monitor_command") and hasattr(plugin, "monitor_commands"):
            try:
                offered = plugin.monitor_commands()
                if isinstance(offered, dict):
                    actions = list(offered)
                elif isinstance(offered, (list, tuple)):
                    actions = list(offered)
            except Exception as exc:
                set_readonly(operator_output, str(exc))
        action_picker["values"] = [x for x in actions if isinstance(x, str)]
        operator_action.set(action_picker["values"][0] if action_picker["values"] else "")

    def refresh_operator_choices():
        options = [name for name, plugin in module_plugins.items()
                   if name in connected and hasattr(plugin, "monitor_command")]
        operator_picker["values"] = options
        if operator_module.get() not in options:
            operator_module.set(options[0] if options else "")
        operator_actions()

    operator_picker.bind("<<ComboboxSelected>>", operator_actions)

    def manual_send():
        plugin = module_plugins.get(operator_module.get())
        try:
            if plugin is None or not hasattr(plugin, "monitor_command"):
                raise ValueError("No controllable module selected")
            action = operator_action.get()
            if not action:
                raise ValueError("No actions advertised by this module")
            payload = json.loads(action_args.get("1.0", "end-1c"))
            if not isinstance(payload, dict):
                raise ValueError("Action arguments must be a JSON object")
            result = plugin.monitor_command(action, payload)
            set_readonly(operator_output, json.dumps(result, indent=2, ensure_ascii=False, default=str))
            log(f"Manual Operator: {operator_module.get()} / {action}")
        except Exception as exc:
            message_error("Manual Operator", exc)

    operator_buttons = ttk.Frame(operator)
    operator_buttons.pack(fill="x", pady=(8, 0))
    ttk.Button(operator_buttons, text="Refresh connections", command=refresh_operator_choices).pack(side="left", padx=(0, 8))
    ttk.Button(operator_buttons, text="Send command", command=manual_send).pack(side="left")
    refresh_operator_choices()

    visited_robotics = False

    def tab_changed(_event=None):
        nonlocal visited_robotics
        selected = notebook.tab(notebook.select(), "text").strip()
        if selected == "Robotics" and not visited_robotics:
            visited_robotics = True
            app.after(80, load_robotics)
        if selected == "Home / Monitor":
            refresh_home()
        if selected == "Manual Operator":
            refresh_operator_choices()

    notebook.bind("<<NotebookTabChanged>>", tab_changed)
    if bridge_problem:
        log(f"Template Bridge: {bridge_problem}")
    refresh_home()

    def close_monitor():
        # Avoid leaving a misleading persistent "connected" state after exit.
        disconnect_resident("local", silent=True)
        disconnect_resident("api", silent=True)
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", close_monitor)
    app.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="DINS Monitor")
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument("--status", action="store_true", help="Show connected foundation and stored configuration")
    flags.add_argument("--blueprint", action="store_true", help="Read blueprint inventory")
    flags.add_argument("--templates", action="store_true", help="List saved profiles")
    flags.add_argument("--capture", metavar="NAME", help="Save a Shared Field profile")
    flags.add_argument("--apply", metavar="NAME", help="Apply a Shared Field profile")
    args = parser.parse_args()
    try:
        if args.status:
            print(json.dumps(status(), ensure_ascii=False, indent=2))
        elif args.blueprint:
            print(json.dumps(blueprint_inventory(), ensure_ascii=False, indent=2))
        elif args.templates:
            for row in bridge_module().list_profiles():
                print(f"{row['name']}: {'SAVED' if row['saved'] else 'not captured'}")
        elif args.capture:
            print(f"Saved: {capture_template(args.capture)}")
        elif args.apply:
            print(f"Applied; revision {apply_template(args.apply)}")
        else:
            run_gui()
    except (OSError, ImportError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        print(f"Monitor: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
