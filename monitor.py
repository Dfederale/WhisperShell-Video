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
import time
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
    "NVIDIA NIM": {'protocol': 'openai', 'endpoint': 'https://integrate.api.nvidia.com/v1/chat/completions', 'model': ''},
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

# Each connected Resident route keeps its own project files. The onscreen
# injector remains an independent external-chat workflow and is not captured.
BUILDER_ROUTE_FOLDERS = {"local": "LOCAL_AI", "api": "API_AI"}


def builder_route_directory(route: str) -> Path:
    """Return the fixed workspace belonging to a Resident route."""
    if route not in BUILDER_ROUTE_FOLDERS:
        raise ValueError("Unknown Builder project route")
    return BUILDER_PROJECTS / BUILDER_ROUTE_FOLDERS[route]


def builder_project_directory(route: str, name: str) -> Path:
    """Keep names plain and prevent paths escaping their assigned route."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,70}", name):
        raise ValueError("Project folder name may contain letters, digits, hyphens and underscores")
    return builder_route_directory(route) / name


def builder_prepare_route_project(route: str, name: str) -> Path:
    """Create only the directories appropriate to this output route."""
    folder = builder_project_directory(route, name)
    subfolders = ("source", "responses") if route == "local" else (
        "source", "documentation", "images", "instructions", "responses")
    for subfolder in subfolders:
        (folder / subfolder).mkdir(parents=True, exist_ok=True)
    return folder


def builder_record_response(project_root: Path, relative: str, content: str) -> Path:
    """Store the returned AI text verbatim, without interpreting or executing it."""
    destination = builder_project_path(project_root, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".builder_tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(destination)
    return destination


def builder_pack_api_project(project_root: Path) -> Path:
    """Package existing files after API steps complete; never fabricate an image."""
    from zipfile import ZIP_DEFLATED, ZipFile
    root = project_root.resolve()
    if not root.is_dir() or root.parent.name != BUILDER_ROUTE_FOLDERS["api"]:
        raise ValueError("Not an API Builder project folder")
    archive = root / (root.name + ".zip")
    temporary = root / (root.name + ".zip.builder_tmp")
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as zipped:
            for directory in sorted(root.rglob("*")):
                if directory.is_symlink():
                    continue
                relative = directory.relative_to(root)
                named = (Path(root.name) / relative).as_posix()
                if directory.is_dir():
                    if not any(directory.iterdir()):
                        zipped.writestr(named + "/", "")
                elif directory.is_file() and directory not in (temporary, archive):
                    zipped.write(directory, arcname=named)
        with ZipFile(temporary) as zipped:
            if zipped.testzip() is not None:
                raise RuntimeError("Generated project ZIP failed integrity verification")
        temporary.replace(archive)
    finally:
        if temporary.exists():
            temporary.unlink()
    return archive
BUILDER_DEFAULT_PROMPT = """Hello, welcome to Digital Intelligence Neuromorphic Systems (DINS).

This system was made by Ferenna (AI) and her partner Dennis (human).

You are DINS Builder, a project-building assistant working with DINS WhisperShell Monitor.

Your task is to create real, downloadable project files following the user's request. Do not merely describe how files could be created.

YOUR CAPABILITIES:

ONE - PROJECT ZIP: Create an actual downloadable ZIP archive containing the complete project folder structure and necessary subfolders. The archive must extract into one clearly named project folder. Include placeholder files where necessary to preserve empty folders. Provide a clickable download link to the ZIP. A JSON mkdir instruction is NOT a substitute for the ZIP.

TWO - SOURCE FILES: Decide how many Python (.py) files the project requires. Create each file with its complete working source code and provide it as a downloadable file when file-creation tools are available. Use CMD, PowerShell, or other necessary files when appropriate. State the total number of Python files.

THREE - CONNECTIONS: If the project requires communication between modules, create a Shared Field or Template Bridge and its necessary files. Do not introduce unnecessary modules or dependencies.

FOUR - SETUP SCHEMATIC: Use the onscreen AI's built-in IMAGE GENERATOR to create a rendered image showing the project's actual folder structure, modules, connections, and assembly order. Display the generated image and provide it as a downloadable image if supported. Do NOT generate SVG, HTML, Python drawing code, ASCII art, or any other substitute for the image generator. If image generation is unavailable, report that clearly rather than substituting another format.

FIVE - README: Create a downloadable README.md explaining the application, requirements, dependencies, file locations, and launch commands.

SIX - FINAL ASSEMBLY: The LAST numbered plan instruction must produce a complete on-screen assembly guide. Explain how to download and extract the ZIP, which files to place in which folders, how to connect modules, and how to start the application. The user must be able to assemble the entire project using the previous outputs.

IMPORTANT FILE CREATION RULES:

When working through an onscreen AI interface with file-creation tools, actually create the requested files and downloadable attachments.

When instructed to create the project ZIP, generate the real ZIP archive and provide its download link in that step.

Do not replace requested downloadable files with JSON describing mkdir or write operations.

Do not claim a file exists unless it was successfully created.

If file-creation tools are unavailable, state that limitation clearly rather than pretending an archive or downloadable file exists.

When working through a separate Builder route that explicitly requires JSON file actions, follow that route's required JSON protocol. Do not claim those actions produced downloadable attachments.

PROJECT RULES:

Honor the selected operating system, system RAM, and application RAM budget.

Prefer portable, lightweight solutions with minimal dependencies.

Preserve relative paths so projects can be extracted to any drive or folder.

Use as many building steps as necessary. The capability categories are not a fixed step limit.

VERIFY AUTOMATICALLY:

Check generated source files, filenames, imports, folder references, and archive contents whenever the available tools permit.

Report only confirmed verification results.

Verification is NOT a separate numbered plan instruction.

CRITICAL PLAN FORMAT FOR WHISPERSHELL:

When asked for a PLAN, act ONLY as PROJECT PLANNER.

Return ONLY consecutive numbered instructions to yourself.

Every instruction MUST begin with its consecutive number, a dot, and ONE space.

Start at 1 and continue without skipping any numbers.

Each numbered instruction must occupy exactly ONE physical line.

Leave EXACTLY ONE completely blank line between numbered instructions.

Do not include headings, introductions, explanations, code, JSON, Markdown fences, or additional text in PLAN MODE.

The FIRST numbered instruction must request creation of the actual downloadable project ZIP with its folder structure.

Subsequent instructions must request the necessary source files, module connections, schematic, and README.

The LAST numbered instruction must ALWAYS request the final on-screen assembly guide.

Each instruction will be returned to you individually by the DINS WhisperShell injector.

STEP EXECUTION MODE:

When receiving an individual numbered instruction, act as BUILDER.

Complete ONLY that instruction.

Do not generate another numbered plan.

Use available tools to create and deliver real downloadable files when working through the onscreen AI.

Provide the resulting file or download link for that step.

Do not claim success unless the requested operation was actually completed.

After completing the step, await the next instruction from WhisperShell."""


# Default prompt texts are seeds for editable .txt presets, not fixed UI resets.
# The original on-screen Builder contract above is preserved verbatim for both
# Onscreen and API routes; only the Local route uses a code-only contract.
BUILDER_LOCAL_CODE_PROMPT = """Hello, welcome to Digital Intelligence Neuromorphic Systems (DINS).

This system was made by Ferenna (AI) and her partner Dennis (human).

You are DINS Builder, working through a connected LOCAL AI Resident in DINS WhisperShell Monitor.

YOUR ROLE:
Plan and write project SOURCE CODE, scripts, configuration, and documentation as text.
Choose the number of Python files needed for the user's request and give each file complete working content. Keep the project portable and lightweight for the specified OS and RAM budget.

LOCAL ROUTE OUTPUT CONTRACT:
- Return only ordinary text, numbered plans, and source-file content in the format requested by Monitor.
- This route cannot directly produce downloadable ZIP attachments or generated images. Do not promise them or fabricate links.
- You may describe folder structure, create textual setup instructions, and document how a user can assemble or package the project.
- Monitor's separate, permission-controlled file writer can create folders and text files from valid JSON mkdir/write operations when explicitly requested. Do not claim any file exists until Monitor reports that its write operation succeeded.
- Do not use SVG, HTML, ASCII art, or source code as a substitute for an image-generator request.
- No unrequested package installations, automatic script execution, or external connections.

PLAN MODE:
Return ONLY consecutive numbered, actionable steps starting at 1.
Put one instruction per physical line with exactly one blank line between instructions.
No headings, code fences, JSON, explanations, or claims that work has already completed.
Include source code, necessary file connections, README, and a final assembly/launch guide.
Do not add steps requiring image generation or the AI to attach a ZIP.

STEP EXECUTION MODE:
Complete ONLY the individual numbered step returned by Monitor.
For the connected Resident Builder route, reply with ONLY a JSON object:
{"actions":[{"op":"mkdir","path":"subfolder"},{"op":"write","path":"source/main.py","content":"complete file text"}],"report":"short accurate description"}
Use only mkdir or write, with project-relative forward-slash paths. No shell commands, delete operations, or absolute paths. Return an empty actions list for steps that make no file changes.
Never claim source files were run, RAM was measured, or a ZIP or image was produced without verification.
Wait for the next numbered instruction from Monitor."""

BUILDER_PRESET_NAMES = {
    "onscreen": "DINS Full Builder",
    "api": "DINS Full Builder",
    "local": "DINS Local Code",
}


def builder_seed_prompt_presets(choice: str) -> dict[str, Path]:
    """Seed editable route-specific TXT presets. Never overwrite user changes."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,49}", choice):
        raise ValueError("Invalid Builder mode")
    templates = {
        "onscreen": BUILDER_DEFAULT_PROMPT,
        "api": BUILDER_DEFAULT_PROMPT,
        "local": BUILDER_LOCAL_CODE_PROMPT,
    }
    PROMPT_FOLDER.mkdir(parents=True, exist_ok=True)
    seeded = {}
    for route, content in templates.items():
        filename = f"{choice.lower()}__{route}__{BUILDER_PRESET_NAMES[route]}.txt"
        target = PROMPT_FOLDER / filename
        # Exclusive create preserves custom modifications from previous runs.
        try:
            with target.open("x", encoding="utf-8") as handle:
                handle.write(content)
        except FileExistsError:
            pass
        seeded[route] = target
    return seeded


def builder_list_prompt_presets(choice: str, route: str) -> dict[str, Path]:
    """Read this route's presets, including legacy presets for online routes."""
    if route not in BUILDER_PRESET_NAMES:
        raise ValueError("Unknown Builder prompt route")
    root = choice.lower() + "__"
    prefix = root + route + "__"
    found: dict[str, Path] = {}
    if not PROMPT_FOLDER.is_dir():
        return found
    for path in PROMPT_FOLDER.glob(prefix + "*.txt"):
        if path.is_file() and not path.is_symlink():
            found[path.stem[len(prefix):]] = path
    if route in ("onscreen", "api"):
        # Preserve presets from the earlier Save Custom release. They weren't
        # route-specific, so make them available to both online routes.
        for path in PROMPT_FOLDER.glob(root + "*.txt"):
            suffix = path.stem[len(root):]
            if "__" not in suffix and path.is_file() and not path.is_symlink():
                found.setdefault(suffix, path)
    return found


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


def builder_ocr_numbered(raw: str) -> list[tuple[int, str]]:
    """Extract visually wrapped numbered lines, including merged 2./3./4. OCR.

    This stage does NOT decide whether the observed text is a real response.
    builder_ocr_filter_preprompt makes that decision before any step is queued.
    """
    result: list[tuple[int, str]] = []
    number = None
    parts: list[str] = []

    def flush():
        if number is not None and parts:
            content = " ".join(parts).strip()
            if len(content) >= 5:
                result.append((number, content))

    # OCR can glue instructions together on one line, including immediately
    # after closing quotes. Split only at a numbered prefix followed by text.
    raw = re.sub(r'(?<![\w\d])([1-9]\d{0,2})[.,)]\s+(?=[A-Za-z])',
                 r'\n\1. ', raw)
    # Trim recognizable interface footer text, which is not part of the plan.
    footer = re.compile(r'(?:chatgpt can make mistakes|check important info|'
                        r'show more|regenerate response)', re.IGNORECASE)
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        match_footer = footer.search(line)
        if match_footer:
            line = line[:match_footer.start()].strip(' \t,.;')
            if not line:
                flush()
                number = None
                parts = []
                continue
        hit = re.match(r"^(\d{1,3})[.)]\s+(.+)$", line)
        if hit:
            flush()
            number = int(hit.group(1))
            parts = [hit.group(2).strip()]
        elif not line:
            flush()
            number = None
            parts = []
        elif number is not None and not line.startswith(("```", ">", "#")):
            parts.append(line)
    flush()
    latest: dict[int, str] = {}
    for index, content in result:
        if 1 <= index <= 150:
            latest[index] = content
    return sorted(latest.items())


def builder_ocr_filter_preprompt(observed: list[tuple[int, str]],
                                 preprompt: str) -> tuple[list[tuple[int, str]], int]:
    """Exclude echoed preprompt examples before the OCR plan can reach injector.

    Derive known instructions from the *editable* preprompt rather than assume
    that the five stock examples are unchanged. Fail closed when an OCR item
    contains a preprompt numbered item (including merged/inaccurate OCR lines).
    """
    from difflib import SequenceMatcher
    import unicodedata

    def normalize(value: str) -> str:
        value = unicodedata.normalize('NFKD', value).casefold()
        return ' '.join(re.findall(r'[a-z0-9]+', value))

    prompt_examples = []
    prompt_prefixes = []
    for line in preprompt.splitlines():
        match = re.match(r'^\s*\d{1,3}[.)]\s+(.+?)\s*$', line)
        if not match:
            continue
        content = normalize(match.group(1))
        if content:
            prompt_examples.append(content)
            # Prefixes such as FOLDER SETUP, SMALL SCRIPTS, README, etc.
            # survive OCR punctuation corruption and merged lines.
            label = normalize(match.group(1).split(':', 1)[0])
            if ':' in match.group(1) and label and len(label) >= 5:
                prompt_prefixes.append(label)
    other_prompt_markers = [
        'you are dins builder', 'these are capabilities',
        'when asked for a plan', 'when asked to complete a step',
        'every instruction line', 'plan mode return only',
    ]

    filtered = []
    rejected = 0
    for index, text in observed:
        candidate = normalize(text)
        # A real plan may say "Create README.md" or "Verify files".
        # Only a LABEL AT THE START identifies the preprompt's numbered
        # capability examples; do not reject ordinary mentions of README.
        is_echo = any(candidate == label or candidate.startswith(label + ' ')
                      for label in prompt_prefixes)
        is_echo = is_echo or any(marker in candidate for marker in other_prompt_markers)
        if not is_echo:
            for example in prompt_examples:
                if (candidate == example or (len(candidate) >= 24 and
                        SequenceMatcher(None, candidate, example).ratio() >= 0.76)):
                    is_echo = True
                    break
        if is_echo:
            rejected += 1
        else:
            filtered.append((index, text))
    return filtered, rejected


def builder_ocr_instructions(raw: str) -> list[str]:
    """Compatibility helper for any older caller."""
    return [step for _, step in builder_ocr_numbered(raw)]


def builder_merge_ocr_lines(collected: dict[int, str], observed: list[tuple[int, str]]) -> bool:
    """Accumulate streaming steps without losing text scrolled out of the OCR region.

    More complete versions of an already-seen step extend the quiet-period timer;
    shorter OCR glitches don't erase earlier text.
    """
    changed = False
    for number, content in observed:
        if number < 1 or number > 150:
            continue
        previous = collected.get(number, "")
        if not previous:
            collected[number] = content
            changed = True
        elif content != previous and len(content) > len(previous) + 2:
            # OCR sometimes changes a letter while streaming. The longer plan wins.
            collected[number] = content
            changed = True
    return changed


def builder_ocr_plan_ready(collected: dict[int, str], last_change: float,
                           now: float, quiet_seconds: float = 20.0) -> bool:
    """A plan is ready only if it starts at 1, has no gaps and stayed quiet."""
    if not collected or not last_change or now - last_change < quiet_seconds:
        return False
    return sorted(collected) == list(range(1, max(collected) + 1))


# Tesseract is a separate Windows executable. Pillow/pytesseract alone are not enough.
# Keep its path local to Monitor, without changing the system PATH or other modules.
TESSERACT_PATH_FILE = ROOT / "data" / "memory" / "tesseract_path.txt"
TESSDATA_PATH_FILE = ROOT / "data" / "memory" / "tessdata_path.txt"
_TESSERACT_RESOLVED: str | None = None


def builder_tesseract_check(candidate: str | Path) -> str | None:
    """Accept only an executable that identifies itself as Tesseract OCR."""
    candidate = Path(str(candidate).strip().strip('"')).expanduser()
    if not candidate.is_file() or candidate.name.lower() != 'tesseract.exe':
        return None
    try:
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        result = subprocess.run([str(candidate), '--version'], capture_output=True,
                                text=True, timeout=6, creationflags=flags)
        details = ((result.stdout or '') + (result.stderr or '')).lower()
        if result.returncode == 0 and 'tesseract' in details:
            return str(candidate.resolve())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def builder_local_tesseract_candidates() -> list[Path]:
    """Find portable Tesseract next to Monitor, without relying on drive letters.

    Search only named tool folders and their limited-depth subfolders. Do not
    recursively scan the full WhisperShell installation or its user projects.
    """
    candidates: list[Path] = [ROOT / "tesseract.exe"]
    named_dirs = {"ocr", "tesseract", "tesseract-ocr", "tesseract_ocr"}
    try:
        folders = [p for p in ROOT.iterdir() if p.is_dir() and not p.is_symlink()
                   and p.name.casefold() in named_dirs]
    except OSError:
        folders = []
    for folder in folders:
        # Common layout: WhisperShell/ocr/tesseract.exe or
        # WhisperShell/ocr/Tesseract-OCR/tesseract.exe
        candidates.append(folder / "tesseract.exe")
        todo = [(folder, 0)]
        visited = 0
        while todo and visited < 500:
            parent, depth = todo.pop(0)
            visited += 1
            if depth >= 4:
                continue
            try:
                children = list(parent.iterdir())
            except (OSError, PermissionError):
                continue
            for child in children:
                if child.is_symlink():
                    continue
                if child.is_file() and child.name.casefold() == "tesseract.exe":
                    candidates.append(child)
                elif child.is_dir() and child.name.casefold() not in {
                    "tessdata", "__pycache__", ".git", "models", "logs", "data"
                }:
                    todo.append((child, depth + 1))
    return list(dict.fromkeys(candidates))


def builder_find_tesseract() -> str | None:
    """Prefer a portable OCR executable; fall back to saved/system installations."""
    global _TESSERACT_RESOLVED
    # A cached absolute path can become stale when WhisperShell moves to USB or
    # another drive. Always try its own neighboring OCR tools first.
    for item in builder_local_tesseract_candidates():
        resolved = builder_tesseract_check(item)
        if resolved:
            _TESSERACT_RESOLVED = resolved
            return resolved
    if _TESSERACT_RESOLVED:
        resolved = builder_tesseract_check(_TESSERACT_RESOLVED)
        if resolved:
            return resolved
    candidates = []
    if TESSERACT_PATH_FILE.is_file():
        try:
            candidates.append(TESSERACT_PATH_FILE.read_text(encoding='utf-8').strip())
        except OSError:
            pass
    if os.getenv('TESSERACT_CMD'):
        candidates.append(os.environ['TESSERACT_CMD'])
    which = shutil.which('tesseract.exe') or shutil.which('tesseract')
    if which:
        candidates.append(which)
    for env in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA', 'APPDATA'):
        base = os.getenv(env)
        if base:
            candidates += [Path(base) / 'Tesseract-OCR' / 'tesseract.exe',
                           Path(base) / 'Programs' / 'Tesseract-OCR' / 'tesseract.exe']
    candidates += [Path('C:/Program Files/Tesseract-OCR/tesseract.exe'),
                   Path('C:/Program Files (x86)/Tesseract-OCR/tesseract.exe')]
    for item in candidates:
        resolved = builder_tesseract_check(item)
        if resolved:
            _TESSERACT_RESOLVED = resolved
            return resolved
    return None


def builder_set_tesseract_path(path: str, *, remember: bool = False) -> str:
    """Remember the verified portable OCR executable, without changing global PATH."""
    global _TESSERACT_RESOLVED
    resolved = builder_tesseract_check(path)
    if not resolved:
        raise RuntimeError('That file is not a working Tesseract OCR executable.')
    _TESSERACT_RESOLVED = resolved
    if remember:
        TESSERACT_PATH_FILE.parent.mkdir(parents=True, exist_ok=True)
        TESSERACT_PATH_FILE.write_text(resolved + '\n', encoding='utf-8')
    return resolved


def builder_find_tessdata(tesseract_exe: str | Path) -> Path | None:
    """Find portable English OCR language data without relying on the working directory.

    First look around the discovered executable, then inside named OCR folders
    beside Monitor. A saved absolute path is only a fallback for movable USBs.
    """
    exe = Path(tesseract_exe).resolve()
    candidates: list[Path] = [
        exe.parent / "tessdata", exe.parent,
        exe.parent.parent / "tessdata", ROOT / "ocr" / "tessdata",
        ROOT / "tessdata",
    ]
    for name in ("ocr", "tesseract", "tesseract-ocr", "tesseract_ocr"):
        base = ROOT / name
        if not base.is_dir() or base.is_symlink():
            continue
        todo = [(base, 0)]
        scanned = 0
        while todo and scanned < 500:
            folder, depth = todo.pop(0)
            scanned += 1
            candidates.append(folder)
            if depth >= 5:
                continue
            try:
                children = list(folder.iterdir())
            except OSError:
                continue
            for child in children:
                if child.is_dir() and not child.is_symlink() and child.name.casefold() not in {
                    "__pycache__", ".git", "models", "logs", "data"
                }:
                    todo.append((child, depth + 1))
    # Support an existing TESSDATA_PREFIX, but never require a system-wide change.
    prefix = os.getenv("TESSDATA_PREFIX", "").strip().strip('"')
    if prefix:
        candidates.extend((Path(prefix), Path(prefix) / "tessdata"))
    if TESSDATA_PATH_FILE.is_file():
        try:
            candidates.append(Path(TESSDATA_PATH_FILE.read_text(encoding="utf-8").strip()))
        except OSError:
            pass
    for folder in dict.fromkeys(candidates):
        try:
            language_file = folder / "eng.traineddata"
            if language_file.is_file() and language_file.stat().st_size > 0:
                return folder.resolve()
        except OSError:
            pass
    return None


def builder_set_tessdata_path(file: str | Path, *, remember: bool = False) -> Path:
    """Configure an existing eng.traineddata chosen through the file picker."""
    selected = Path(file).expanduser()
    if selected.name.casefold() != "eng.traineddata" or not selected.is_file() or selected.stat().st_size == 0:
        raise RuntimeError("Select an existing, non-empty eng.traineddata file.")
    directory = selected.resolve().parent
    if remember:
        TESSDATA_PATH_FILE.parent.mkdir(parents=True, exist_ok=True)
        TESSDATA_PATH_FILE.write_text(str(directory) + "\n", encoding="utf-8")
    return directory


class BuilderPIDCleaner:
    """Track only OCR processes launched by THIS Builder window.

    Windows owns numerical PIDs: a restart gets a fresh one. Keeping Popen
    handles makes cleanup safe even when Windows reuses unrelated PID numbers.
    Never enumerate or terminate ChatGPT, Ollama, Monitor, or Windows tasks.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._epoch = 0
        self._children: dict[int, subprocess.Popen] = {}

    def current_epoch(self) -> int:
        with self._lock:
            return self._epoch

    def clean(self) -> list[int]:
        """Cancel old OCR work and terminate any still-running owned child."""
        with self._lock:
            self._epoch += 1
            children = list(self._children.values())
            self._children.clear()
        stopped = []
        for process in children:
            if process.poll() is None:
                try:
                    process.kill()  # Only the exact process WE started.
                    stopped.append(process.pid)
                except (OSError, ProcessLookupError):
                    pass
            try:
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        return stopped

    def run(self, arguments: list[str], *, epoch: int, timeout: float = 25.0):
        """Run one tracked child, rejecting work from a cancelled OCR session."""
        with self._lock:
            if epoch != self._epoch:
                raise RuntimeError("Old OCR session cancelled")
            # Lock covers creation and registration, so Start cannot race
            # with a previous OCR thread spawning an untracked process.
            process = subprocess.Popen(
                arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self._children[process.pid] = process
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                if process.poll() is None:
                    process.kill()
                process.communicate()
                raise
            with self._lock:
                if epoch != self._epoch:
                    raise RuntimeError("Old OCR session cancelled")
            return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)
        finally:
            with self._lock:
                if self._children.get(process.pid) is process:
                    self._children.pop(process.pid, None)


def builder_tesseract_ocr(image, executable: str | Path, language_dir: Path,
                          *, pid_cleaner: BuilderPIDCleaner | None = None,
                          pid_epoch: int | None = None) -> str:
    """Run OCR with an argument list, never quote a Windows folder inside an argument.

    pytesseract uses shlex.split(..., posix=False) on Windows. If a folder is
    quoted inside its config string, those quote characters can become part
    of the actual --tessdata-dir argument. A subprocess argument list avoids
    this entirely, including for portable installations with spaces in paths.
    The temporary capture file is removed even when OCR fails.
    """
    import tempfile

    exe = str(executable)
    language_dir = Path(language_dir)
    if not (language_dir / "eng.traineddata").is_file():
        raise RuntimeError("Tesseract English data is missing: " + str(language_dir / "eng.traineddata"))
    with tempfile.TemporaryDirectory(prefix="dins_ocr_") as temporary:
        screenshot = Path(temporary) / "screenshot.png"
        image.save(screenshot, format="PNG")
        arguments = [exe, str(screenshot), "stdout", "-l", "eng",
                     "--psm", "6", "--tessdata-dir", str(language_dir)]
        try:
            if pid_cleaner is not None:
                if pid_epoch is None:
                    raise ValueError("PID-cleaner OCR requires a session epoch")
                result = pid_cleaner.run(arguments, epoch=pid_epoch, timeout=25)
            else:
                result = subprocess.run(
                    arguments, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=25,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Tesseract OCR could not run: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            raise RuntimeError("Tesseract OCR error: " + detail[:900])
        return result.stdout


def builder_ocr_capture(region: tuple[int, int, int, int],
                        *, pid_cleaner: BuilderPIDCleaner | None = None,
                        pid_epoch: int | None = None) -> str:
    """Capture the selected region and invoke portable Tesseract directly."""
    try:
        from PIL import ImageGrab, ImageOps, ImageEnhance
    except ImportError as exc:
        raise RuntimeError("Onscreen OCR requires Pillow. Install it with python -m pip install Pillow") from exc
    path = builder_find_tesseract()
    if not path:
        raise RuntimeError('Tesseract OCR executable not found. Press Start to locate tesseract.exe.')
    tessdata = builder_find_tessdata(path)
    if tessdata is None:
        raise RuntimeError("English OCR data (eng.traineddata) not found inside the portable OCR folders.")
    x, y, w, h = region
    if w < 10 or h < 10:
        raise ValueError("Select an OCR rectangle at least 10 x 10 pixels")
    shot = ImageGrab.grab(bbox=(x, y, x+w, y+h), all_screens=True)
    image = ImageEnhance.Contrast(ImageOps.grayscale(shot)).enhance(1.8)
    return builder_tesseract_ocr(image, path, tessdata,
                                 pid_cleaner=pid_cleaner, pid_epoch=pid_epoch)


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
        # Builder transcripts and prompts are stored for the operator, not
        # re-fed as source code: keep the model's context budget for real files.
        if entry.relative_to(project_root).parts[0] in ("responses", "instructions"):
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

    # Mixed-DPI dual-monitor setups need consistent physical screen coordinates.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (OSError, AttributeError, ValueError):
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except (OSError, AttributeError, ValueError):
                pass
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
    builder_pid_cleaners: list[BuilderPIDCleaner] = []

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


    # BUILDER: five creation modes, with route-specific editable TXT presets.
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

        # Separate prompt libraries for Onscreen, API, and Local AI. Changing
        # routes stores the editor's current text so even UNSAVED work survives
        # when switching back; Save Custom is the explicit write-to-disk action.
        try:
            seeded_presets = builder_seed_prompt_presets(choice)
        except (ValueError, OSError) as exc:
            messagebox.showerror("DINS Builder presets", str(exc), parent=window)
            window.destroy()
            return
        route_labels = {"Onscreen AI": "onscreen", "API AI": "api", "Local AI": "local"}
        prompt_route_var = tk.StringVar(value="Onscreen AI")
        active_prompt_route = ["onscreen"]
        prompt_drafts = {}
        for route, path in seeded_presets.items():
            try:
                prompt_drafts[route] = path.read_text(encoding="utf-8")
            except OSError:
                prompt_drafts[route] = (BUILDER_LOCAL_CODE_PROMPT if route == "local"
                                        else BUILDER_DEFAULT_PROMPT)
        prescript.insert("1.0", prompt_drafts["onscreen"])

        prompt_controls = ttk.Frame(top)
        prompt_controls.pack(fill="x", pady=(5, 0))
        ttk.Label(prompt_controls, text="Preprompt for:").pack(side="left", padx=(0, 5))
        prompt_route_picker = ttk.Combobox(
            prompt_controls, textvariable=prompt_route_var,
            values=list(route_labels), state="readonly", width=13)
        prompt_route_picker.pack(side="left", padx=(0, 8))
        ttk.Label(prompt_controls, text="Preset:").pack(side="left", padx=(0, 5))
        custom_name = tk.StringVar(value=BUILDER_PRESET_NAMES["onscreen"])
        custom_picker = ttk.Combobox(prompt_controls, textvariable=custom_name, width=22)
        custom_picker.pack(side="left", padx=(0, 6))
        custom_status = tk.StringVar(value="Onscreen AI preset ready")
        route_preset_names = {r: BUILDER_PRESET_NAMES[r] for r in BUILDER_PRESET_NAMES}
        local_notice_shown = [False]

        def local_ai_notice():
            if local_notice_shown[0]:
                return
            local_notice_shown[0] = True
            messagebox.showinfo(
                "Local AI Builder",
                "This route produces code and text. Downloadable ZIP files and "
                "generated images are not available here.\n\n"
                "The quality and complexity of the output depend on the selected AI model.",
                parent=window)

        def current_prompt_text(route: str) -> str:
            if active_prompt_route[0] == route:
                return prescript.get("1.0", "end-1c")
            return prompt_drafts[route]

        def custom_prompt_path(name: str, route: str) -> Path:
            name = name.strip()
            if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,59}", name)
                    or name.endswith((".", " "))):
                raise ValueError("Use a preset name of 1-60 letters, digits, spaces, dots, - or _.")
            # Keep legacy files untouched; new saves are route-specific.
            return PROMPT_FOLDER / f"{choice.lower()}__{route}__{name}.txt"

        def refresh_custom_presets():
            route = active_prompt_route[0]
            available = builder_list_prompt_presets(choice, route)
            custom_picker.configure(values=sorted(available, key=str.casefold))

        def switch_prompt_route(route: str, *, notify_local: bool = True):
            if route not in BUILDER_PRESET_NAMES:
                raise ValueError("Unknown Builder prompt route")
            previous = active_prompt_route[0]
            prompt_drafts[previous] = prescript.get("1.0", "end-1c")
            route_preset_names[previous] = custom_name.get()
            active_prompt_route[0] = route
            prompt_route_var.set(next(label for label, value in route_labels.items() if value == route))
            prescript.delete("1.0", "end")
            prescript.insert("1.0", prompt_drafts[route])
            custom_name.set(route_preset_names[route])
            refresh_custom_presets()
            custom_status.set(prompt_route_var.get() + " preprompt ready")
            if route == "local" and notify_local:
                local_ai_notice()

        def on_prompt_route_selected(_event=None):
            switch_prompt_route(route_labels[prompt_route_var.get()])

        prompt_route_picker.bind("<<ComboboxSelected>>", on_prompt_route_selected)

        def save_custom_preprompt():
            try:
                route = active_prompt_route[0]
                path = custom_prompt_path(custom_name.get(), route)
                content = prescript.get("1.0", "end-1c")
                if not content.strip():
                    raise ValueError("The preprompt editor is empty.")
                if len(content) > 100_000:
                    raise ValueError("Custom preprompts are limited to 100,000 characters.")
                if path.exists() and not messagebox.askyesno(
                        "Overwrite custom preset?", f"Replace existing preset '{custom_name.get().strip()}'?",
                        parent=window):
                    return
                PROMPT_FOLDER.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(".txt.tmp")
                temporary.write_text(content, encoding="utf-8")
                temporary.replace(path)
                prompt_drafts[route] = content
                refresh_custom_presets()
                custom_status.set("Saved: " + path.name)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Save Custom", str(exc), parent=window)

        def load_custom_preprompt():
            try:
                route = active_prompt_route[0]
                selected = builder_list_prompt_presets(choice, route)
                path = selected.get(custom_name.get().strip())
                if path is None or not path.is_file() or path.is_symlink():
                    raise FileNotFoundError("Choose an existing preset from the dropdown.")
                content = path.read_text(encoding="utf-8")
                if not content.strip():
                    raise ValueError("That saved preprompt is empty.")
                prescript.delete("1.0", "end")
                prescript.insert("1.0", content)
                prompt_drafts[route] = content
                custom_status.set("Loaded: " + path.name)
            except (ValueError, OSError) as exc:
                messagebox.showerror("Load Selected", str(exc), parent=window)

        ttk.Button(prompt_controls, text="Save Custom", command=save_custom_preprompt).pack(side="left", padx=(0, 5))
        ttk.Button(prompt_controls, text="Load Selected", command=load_custom_preprompt).pack(side="left", padx=(0, 5))
        ttk.Label(top, textvariable=custom_status, foreground="#555555").pack(anchor="w")
        refresh_custom_presets()

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
        destination_picker = labeled_combo(config_row, "AI destination", route_var,
                                           ["Local AI", "API AI"], width=14, readonly=True)

        def on_ai_destination_selected(_event=None):
            route = "local" if route_var.get() == "Local AI" else "api"
            switch_prompt_route(route)

        destination_picker.bind("<<ComboboxSelected>>", on_ai_destination_selected)

        second_row = ttk.Frame(body)
        second_row.pack(fill="x", pady=(0, 6))
        project_group = ttk.Frame(second_row)
        project_group.pack(side="left", fill="x", expand=True, padx=(0, 14))
        ttk.Label(project_group, text="Project folder name (under data/builder_projects)").pack(anchor="w")
        ttk.Entry(project_group, textvariable=project_var, width=45).pack(fill="x", pady=(2, 0))

        def open_route_folder(route: str):
            """Open the route workspace, independent of the currently selected AI."""
            try:
                directory = builder_route_directory(route)
                directory.mkdir(parents=True, exist_ok=True)
                if sys.platform == "win32":
                    os.startfile(str(directory))
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(directory)])
                else:
                    subprocess.Popen(["xdg-open", str(directory)])
            except (OSError, ValueError) as exc:
                messagebox.showerror("Open Builder folder", str(exc), parent=window)

        ttk.Button(second_row, text="Open API Folder",
                   command=lambda: open_route_folder("api")).pack(side="right", padx=(5, 0), pady=(15, 0))
        ttk.Button(second_row, text="Open Local Folder",
                   command=lambda: open_route_folder("local")).pack(side="right", padx=(5, 0), pady=(15, 0))

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
        stage = tk.StringVar(value="Connect a Resident, enter a request, then ask for steps.")
        ttk.Label(body, textvariable=stage, wraplength=920).pack(anchor="w", pady=(0, 7))

        # Onscreen is a single-route, fully automatic OCR -> plan -> injector path.
        # Region is selected by dragging a screen rectangle, input by clicking the AI.
        screen_frame = ttk.LabelFrame(body, text="Onscreen Builder / Select, Start, Inject", padding=6)
        screen_frame.pack(fill="x", pady=(2, 6))
        screen_status = tk.StringVar(value="1. Select the AI response region.  2. Write a request.  3. Start, then click the AI input box.")
        screen_controls = ttk.Frame(screen_frame)
        screen_controls.pack(fill="x", pady=(1, 5))
        screen_select_button = ttk.Button(screen_controls, text="Select region (draw rectangle)")
        screen_select_button.pack(side="left", padx=(0, 6))
        screen_start_button = ttk.Button(screen_controls, text="Start")
        screen_start_button.pack(side="left", padx=(0, 6))
        screen_pause_button = ttk.Button(screen_controls, text="Pause / Resume")
        screen_pause_button.pack(side="left", padx=(0, 6))
        screen_stop_button = ttk.Button(screen_controls, text="Stop")
        screen_stop_button.pack(side="left", padx=(0, 6))
        screen_reset_button = ttk.Button(screen_controls, text="Reset")
        screen_reset_button.pack(side="left")
        screen_interval_row = ttk.Frame(screen_frame)
        screen_interval_row.pack(fill="x", pady=(2, 5))
        ttk.Label(screen_interval_row, text="Injection interval (seconds):").pack(side="left", padx=(0, 8))
        screen_interval_picker = ttk.Combobox(
            screen_interval_row, textvariable=interval_var,
            values=["0", "1", "1.2", "3", "5", "10", "13", "20", "30", "60", "120", "180", "240", "300", "420", "480", "600", "720", "900"], width=9)
        screen_interval_picker.pack(side="left")
        ttk.Label(screen_interval_row, text="Editable. Affects both onscreen and connected Resident step injection.").pack(side="left", padx=10)
        ttk.Label(screen_frame, textvariable=screen_status, wraplength=940).pack(anchor="w")
        ttk.Label(screen_frame,
                  text="After sending the request, Monitor jumps to the newest response and keeps "
                       "scrolling the selected chat area until OCR completes. "
                       "Echoed preprompt steps are filtered. "
                       "OCR begins 5 seconds later. After 20 seconds without new numbered lines, "
                       "the collected plan is injected at the interval selected above.",
                  wraplength=940).pack(anchor="w", pady=(3, 0))

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
            if not 0 <= seconds <= 900:
                raise ValueError("Interval must be between 0 and 900 seconds")
            channel = "local" if route_var.get() == "Local AI" else "api"
            resident_info = channels[channel]
            if not resident_info["connected"] or not resident_info["config"]:
                raise ValueError("Connect the selected AI in the Resident tab first")
            return {
                "request": prompt, "os": os_var.get(), "system_ram": sysram_var.get(),
                "app_ram": appram_var.get(), "route": channel, "interval": seconds,
                "folder": builder_project_directory(channel, folder_name),
                "preprompt": current_prompt_text(channel).strip(),
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
            selected_route = "local" if route_var.get() == "Local AI" else "api"
            if active_prompt_route[0] != selected_route:
                switch_prompt_route(selected_route)
            elif selected_route == "local":
                local_ai_notice()
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
            try:
                builder_prepare_route_project(values["route"], values["folder"].name)
                # Preserve the exact request and selected preprompt for this run.
                builder_record_response(job["folder"], "responses/request.txt", values["request"])
                builder_record_response(job["folder"], "responses/preprompt.txt", values["preprompt"])
            except (OSError, ValueError) as exc:
                job["busy"] = False
                stage.set("Project folder could not be created: " + str(exc))
                messagebox.showerror("Builder workspace", str(exc), parent=window)
                control_state()
                return
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
                stage.set(f"All {len(job['steps'])} instructions processed. Files are in the {job['route'].upper()} folder.")
                activity_line("FINAL STATIC CHECK\n" + builder_verify_files(job["folder"]))
                if job["route"] == "api":
                    try:
                        package = builder_pack_api_project(job["folder"])
                        activity_line("API PROJECT ZIP CREATED: " + str(package))
                    except (OSError, ValueError, RuntimeError) as exc:
                        activity_line("API ZIP PACKAGING ERROR: " + str(exc))
                        stage.set("Steps completed, but the API project ZIP failed: " + str(exc))
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
                        try:
                            builder_record_response(job["folder"], "instructions/plan.txt" if job["route"] == "api"
                                                    else "responses/plan.txt", reply)
                        except (OSError, ValueError) as exc:
                            activity_line("PLAN SAVE ERROR: " + str(exc))
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
                            builder_record_response(job["folder"],
                                f"responses/step_{job['step_index'] + 1:03d}.txt", reply)
                            if job["route"] == "api":
                                builder_record_response(job["folder"],
                                    f"instructions/step_{job['step_index'] + 1:03d}.txt",
                                    job["steps"][job["step_index"]])
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

        # ONSCREEN PIPELINE: draw response rectangle -> submit request -> scroll the
        # selected chat response area -> start OCR after 5s -> 20s quiet -> inject plan.
        # No coordinate, poll-rate, or countdown boxes are required.
        screen_state = {
            "generation": 0, "phase": "idle", "paused": False, "pause_at": None,
            "region": None, "target": None, "target_hwnd": None,
            "collected": {}, "pending": [], "last_change": 0.0,
            "busy": False, "sending": False, "last_send": 0.0,
            "interval": 3.0, "prompt": "", "preprompt": "", "selected_at": 0.0,
            "mouse_was_down": False, "last_read": 0.0,
            "request_sent_at": 0.0, "last_scroll": 0.0,
            "echo_warning_shown": False,
        }
        screen_events: queue.Queue = queue.Queue()
        # The only child PIDs owned by onscreen Builder are OCR subprocesses.
        # Tkinter/injector threads belong to Monitor's own process and cannot
        # be safely PID-killed without closing Monitor itself.
        screen_pid_cleaner = BuilderPIDCleaner()
        builder_pid_cleaners.append(screen_pid_cleaner)
        OCR_POLL_SECONDS = 1.5
        QUIET_SECONDS = 20.0
        INPUT_CLICK_SECONDS = 10.0  # fixed safety window, not another UI setting
        OCR_START_DELAY_SECONDS = 5.0  # wait for the answer after initial injection
        # Native Windows mouse-wheel pulses scroll the chosen chat viewport quickly.
        # PyAutoGUI turns a 50-tick request into 50 slow individual mouse events.
        RESPONSE_SCROLL_INTERVAL_SECONDS = 0.35
        RESPONSE_SCROLL_TICKS = 40    # per pulse when following live output
        RESPONSE_INITIAL_TICKS = 96  # per pulse when jumping past the prompt


        def windows_window_at(point):
            """Return top-level Windows HWND and process ID at screen position."""
            import ctypes
            from ctypes import wintypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
            u = ctypes.windll.user32
            u.WindowFromPoint.argtypes = [POINT]
            u.WindowFromPoint.restype = wintypes.HWND
            u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            u.GetAncestor.restype = wintypes.HWND
            u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            u.GetWindowThreadProcessId.restype = wintypes.DWORD
            hwnd = u.WindowFromPoint(POINT(int(point[0]), int(point[1])))
            if not hwnd:
                return None, None
            root_hwnd = u.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
            process_id = wintypes.DWORD()
            u.GetWindowThreadProcessId(root_hwnd, ctypes.byref(process_id))
            return int(root_hwnd), int(process_id.value)

        def windows_mouse_snapshot():
            """Read global mouse-button state without requiring pynput."""
            import ctypes
            from ctypes import wintypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
            u = ctypes.windll.user32
            pointer = POINT()
            u.GetCursorPos(ctypes.byref(pointer))
            left_down = bool(u.GetAsyncKeyState(0x01) & 0x8000)
            return left_down, (int(pointer.x), int(pointer.y))

        def select_ocr_region():
            if screen_state["phase"] in ("await_click", "sending_prompt", "watching", "injecting"):
                messagebox.showinfo("Onscreen Builder", "Stop the current run before changing the region.", parent=window)
                return
            try:
                from PIL import ImageGrab, ImageTk
                if sys.platform != "win32":
                    raise RuntimeError("The multi-monitor drag selector currently requires Windows.")
                import ctypes
                u = ctypes.windll.user32
                # Virtual desktop can start at negative X when monitor two is left.
                origin_x = u.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
                origin_y = u.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
                screenshot = ImageGrab.grab(all_screens=True)
                width, height = screenshot.size
            except Exception as exc:
                messagebox.showerror("Select region", f"Cannot capture screens: {exc}", parent=window)
                return
            selector = tk.Toplevel(app)
            selector.overrideredirect(True)
            selector.attributes("-topmost", True)
            selector.configure(cursor="crosshair")
            # Initially place the overlay, then enforce negative monitor coordinates.
            selector.geometry(f"{width}x{height}+0+0")
            selector.update_idletasks()
            try:
                from ctypes import wintypes
                u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
                u.SetWindowPos.restype = wintypes.BOOL
                raw_hwnd = selector.wm_frame()
                hwnd = int(raw_hwnd, 0) if isinstance(raw_hwnd, str) else int(raw_hwnd)
                if not u.SetWindowPos(hwnd, -1, origin_x, origin_y, width, height, 0x0040):
                    raise OSError("Could not position selection overlay")
            except (OSError, ValueError, TypeError):
                selector.geometry(f"{width}x{height}{origin_x:+d}{origin_y:+d}")
            canvas = tk.Canvas(selector, width=width, height=height, highlightthickness=0,
                               cursor="crosshair")
            canvas.pack(fill="both", expand=True)
            photo = ImageTk.PhotoImage(screenshot)
            canvas.image_ref = photo
            canvas.create_image(0, 0, anchor="nw", image=photo)
            canvas.create_text(28, 26, anchor="nw", text="Drag around the AI response area. Esc cancels.",
                               font=("Segoe UI", 18, "bold"), fill="#00F4D0")
            drag = {"x": None, "y": None, "box": None}

            def begin(event):
                drag["x"], drag["y"] = event.x, event.y
                if drag["box"] is not None:
                    canvas.delete(drag["box"])
                drag["box"] = canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                                       outline="#00F4D0", width=3)

            def move(event):
                if drag["box"] is not None:
                    canvas.coords(drag["box"], drag["x"], drag["y"], event.x, event.y)

            def finish(event):
                if drag["x"] is None:
                    return
                x1 = max(0, min(width, min(drag["x"], event.x)))
                x2 = max(0, min(width, max(drag["x"], event.x)))
                y1 = max(0, min(height, min(drag["y"], event.y)))
                y2 = max(0, min(height, max(drag["y"], event.y)))
                selector.destroy()
                if x2 - x1 < 50 or y2 - y1 < 35:
                    screen_status.set("Selection too small. Drag a rectangle around the numbered response.")
                    return
                screen_state["region"] = (origin_x + x1, origin_y + y1, x2-x1, y2-y1)
                screen_status.set(f"Region selected: {x2-x1} x {y2-y1} pixels. Enter the request and click Start.")
                activity_line(f"ONSCREEN: OCR rectangle selected ({x2-x1} x {y2-y1} pixels).")

            canvas.bind("<ButtonPress-1>", begin)
            canvas.bind("<B1-Motion>", move)
            canvas.bind("<ButtonRelease-1>", finish)
            selector.bind("<Escape>", lambda _e: selector.destroy())
            selector.focus_force()

        def screen_paste(text):
            """Send complete multiline text via Ctrl+V. The user chooses the target by click."""
            import pyautogui
            target = screen_state["target"]
            if target is None:
                raise RuntimeError("No AI input click recorded")
            if sys.platform == "win32":
                hwnd, owner_pid = windows_window_at(target)
                if not hwnd or hwnd != screen_state["target_hwnd"] or owner_pid == os.getpid():
                    raise RuntimeError("Target window moved or changed. Stopped to avoid typing into another app.")
            pyautogui.FAILSAFE = True
            app.clipboard_clear()
            app.clipboard_append(text)
            app.update_idletasks()
            pyautogui.click(*target)
            time.sleep(0.10)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.25)  # let the receiving app process the paste before Enter
            pyautogui.press("enter")

        def screen_scroll_response(*, initial=False):
            """Snap chat to the newest output and follow it until OCR finishes.

            The wheel targets the previously selected response rectangle, never
            the input field. A native Windows mouse-wheel event moves multiple
            detents in a single system event, avoiding PyAutoGUI's per-tick loop.
            Keep the original window-owner check to prevent scrolling other apps.
            """
            s = screen_state
            region = s["region"]
            if not region or s["phase"] != "watching" or s["paused"]:
                return
            x, y, width, height = region
            response_point = (x + width // 2, y + height // 2)
            if sys.platform == "win32":
                hwnd, owner_pid = windows_window_at(response_point)
                if (not hwnd or hwnd != s["target_hwnd"] or owner_pid == os.getpid()):
                    raise RuntimeError(
                        "Selected OCR response area is no longer in the chosen AI window. "
                        "Stop or restore the chat window before continuing.")
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.moveTo(*response_point, duration=0)
            if sys.platform == "win32":
                import ctypes
                user32 = ctypes.windll.user32
                # MOUSEEVENTF_WHEEL = 0x0800, WHEEL_DELTA = 120.
                # Tesseract and GUI processing should not wait for hundreds of
                # individually simulated wheel ticks.
                # IMPORTANT: Do not set argtypes on this shared Windows function.
                # PyAutoGUI also calls ctypes.windll.user32.mouse_event for
                # clicks, passing ctypes.c_long mouse coordinates. Overriding
                # argtypes here makes the NEXT click fail with:
                # "argument 2: TypeError: wrong type".
                # Native wheel messages work without altering the signature.
                per_pulse = RESPONSE_INITIAL_TICKS if initial else RESPONSE_SCROLL_TICKS
                # A few native wheel messages handle long chat histories; future
                # pulses keep the newest AI response inside the OCR rectangle.
                pulses = 3 if initial else 2
                wheel_delta = (-120 * per_pulse) & 0xFFFFFFFF
                for _ in range(pulses):
                    user32.mouse_event(0x0800, 0, 0, wheel_delta, 0)
            else:
                # Non-Windows fallback; onscreen selection currently needs Windows.
                pyautogui.scroll(-(RESPONSE_INITIAL_TICKS if initial else RESPONSE_SCROLL_TICKS))
            s["last_scroll"] = time.monotonic()

        def screen_read():
            if screen_state["busy"] or screen_state["phase"] != "watching" or screen_state["paused"]:
                return
            screen_state["busy"] = True
            generation = screen_state["generation"]
            region = screen_state["region"]
            pid_epoch = screen_pid_cleaner.current_epoch()
            def work():
                try:
                    screen_events.put((generation, True, builder_ocr_capture(
                        region, pid_cleaner=screen_pid_cleaner, pid_epoch=pid_epoch)))
                except Exception as exc:
                    screen_events.put((generation, False, str(exc)))
            threading.Thread(target=work, daemon=True).start()

        def screen_send_next():
            s = screen_state
            if s["phase"] != "injecting" or s["paused"] or s["sending"] or not s["pending"]:
                return
            if time.monotonic() - s["last_send"] < s["interval"]:
                return
            index, instruction = s["pending"][0]
            s["sending"] = True
            try:
                screen_paste(f"{index}. {instruction}")
            except Exception as exc:
                s["paused"] = True
                s["pause_at"] = time.monotonic()
                screen_status.set(f"Injection paused: {exc}")
                activity_line(f"ONSCREEN INJECTION ERROR: {exc}")
            else:
                s["pending"].pop(0)
                s["last_send"] = time.monotonic()
                activity_line(f"INJECTED {index}: {instruction}")
                if not s["pending"]:
                    s["phase"] = "finished"
                    screen_status.set(f"Finished injecting {len(s['collected'])} numbered steps.")
                    log(f"Onscreen Builder {choice}: {len(s['collected'])} steps injected")
                else:
                    screen_status.set(f"Injected {index}. {len(s['pending'])} remaining. Next in {s['interval']:g}s.")
            finally:
                s["sending"] = False

        def screen_start():
            s = screen_state
            if s["phase"] in ("await_click", "sending_prompt", "watching", "injecting"):
                return
            if not s["region"]:
                messagebox.showerror("Onscreen Builder", "Click Select region and draw a rectangle first.", parent=window)
                return
            request = user_prompt.get("1.0", "end-1c").strip()
            if not request:
                messagebox.showerror("Onscreen Builder", "Enter your application request first.", parent=window)
                return
            # Minus Alex-style PID cleanup BEFORE starting a new Builder run.
            # Only owned Tesseract PIDs are eligible; never kill the target AI.
            cleaned_pids = screen_pid_cleaner.clean()
            activity_line("ONSCREEN PID CLEANER: " +
                          ("stopped owned OCR PIDs " + ", ".join(map(str, cleaned_pids))
                           if cleaned_pids else "no leftover OCR process"))
            try:
                interval = float(interval_var.get())
                if not 0 <= interval <= 900:
                    raise ValueError("Injection interval must be 0 to 900 seconds")
                if sys.platform != "win32":
                    raise RuntimeError("Automatic external-click capture is currently Windows-only")
                import pyautogui
                from PIL import ImageGrab
                # First search the portable OCR folder beside Monitor; then PATH.
                found_tesseract = builder_find_tesseract()
                if not found_tesseract:
                    from tkinter import filedialog
                    chosen_exe = filedialog.askopenfilename(
                        parent=window, title="Locate your existing Tesseract OCR installation",
                        filetypes=[("Tesseract OCR", "tesseract.exe"), ("Executables", "*.exe")],
                        initialdir=str(ROOT / "ocr" if (ROOT / "ocr").is_dir() else ROOT))
                    if not chosen_exe:
                        screen_status.set("Tesseract executable not selected; Start cancelled.")
                        return
                    found_tesseract = builder_set_tesseract_path(chosen_exe, remember=True)
                else:
                    builder_set_tesseract_path(found_tesseract)
                # Check the language file BEFORE sending anything to the AI.
                # Tesseract --version succeeds even if the English OCR data is missing.
                language_dir = builder_find_tessdata(found_tesseract)
                if language_dir is None:
                    from tkinter import filedialog
                    chosen_data = filedialog.askopenfilename(
                        parent=window,
                        title="Locate eng.traineddata (English OCR language data)",
                        initialdir=str(ROOT / "ocr" if (ROOT / "ocr").is_dir() else ROOT),
                        filetypes=[("English OCR data", "eng.traineddata"),
                                   ("Traineddata files", "*.traineddata")])
                    if not chosen_data:
                        screen_status.set("English OCR language file missing; Start cancelled before sending request.")
                        return
                    language_dir = builder_set_tessdata_path(chosen_data, remember=True)
                # Exercise the exact OCR launch before sending anything to the AI.
                # Existence checks alone cannot detect broken Tesseract CLI arguments.
                from PIL import Image, ImageDraw
                probe = Image.new("RGB", (210, 60), "white")
                ImageDraw.Draw(probe).text((10, 12), "DINS OCR TEST", fill="black")
                builder_tesseract_ocr(
                    probe, found_tesseract, language_dir,
                    pid_cleaner=screen_pid_cleaner,
                    pid_epoch=screen_pid_cleaner.current_epoch())
                activity_line("ONSCREEN: Tesseract OCR preflight passed: " + found_tesseract)
                activity_line("ONSCREEN: English language data ready: " + str(language_dir))
            except (ValueError, ImportError, RuntimeError) as exc:
                messagebox.showerror("Onscreen Builder", str(exc), parent=window)
                return
            # An Onscreen run does NOT need Local/API Resident connectivity.
            # Existing Resident Builder buttons above remain independent.
            preprompt = current_prompt_text("onscreen").strip()
            constraints = (f"TARGET OS: {os_var.get()}\nSYSTEM RAM: {sysram_var.get()}\n"
                           f"APP RAM BUDGET: {appram_var.get()}\nBUILD MODE: {choice}")
            ask = (preprompt + "\n\n" + constraints + "\n\nUSER REQUEST:\n" + request +
                   "\n\nPLAN MODE: Return ONLY consecutively numbered, actionable instruction "
                   "lines starting at 1. Use one blank line between steps. "
                   "Do not return code, headings, Markdown fences or explanations. "
                   "Wait for each numbered instruction to be returned to you separately.")
            s.update(generation=s["generation"] + 1, phase="await_click", paused=False,
                     pause_at=None, target=None, target_hwnd=None, collected={}, pending=[],
                     last_change=0.0, busy=False, sending=False, last_send=0.0,
                     interval=interval, prompt=ask, preprompt=preprompt,
                     selected_at=time.monotonic(),
                     request_sent_at=0.0, last_scroll=0.0, last_read=0.0,
                     echo_warning_shown=False)
            s["mouse_was_down"], _pos = windows_mouse_snapshot()
            screen_status.set("Click the AI input box now (within 10 seconds). The request will send automatically.")
            activity_line("ONSCREEN: waiting for click on the AI input field; region already selected.")

        def screen_pause_resume():
            s = screen_state
            if s["phase"] not in ("watching", "injecting"):
                return
            if s["paused"]:
                duration = time.monotonic() - (s["pause_at"] or time.monotonic())
                if s["last_change"]:
                    s["last_change"] += duration
                if s["last_send"]:
                    s["last_send"] += duration
                if s["request_sent_at"]:
                    s["request_sent_at"] += duration
                if s["last_scroll"]:
                    s["last_scroll"] += duration
                s["paused"] = False
                s["pause_at"] = None
                screen_status.set("Resumed " + s["phase"] + ".")
            else:
                s["paused"] = True
                s["pause_at"] = time.monotonic()
                screen_status.set("Paused. OCR plan and injection queue retained.")

        def screen_stop():
            s = screen_state
            s["generation"] += 1
            cleaned_pids = screen_pid_cleaner.clean()
            if cleaned_pids:
                activity_line("ONSCREEN PID CLEANER: stopped owned OCR PIDs " +
                              ", ".join(map(str, cleaned_pids)))
            s.update(phase="stopped", paused=False, busy=False, sending=False)
            screen_status.set(f"Stopped. {len(s['collected'])} detected plan lines remain until Reset.")

        def screen_reset():
            screen_stop()
            screen_state.update(phase="idle", collected={}, pending=[], last_change=0.0,
                                target=None, target_hwnd=None,
                                request_sent_at=0.0, last_scroll=0.0)
            screen_status.set("Reset. Region retained. Enter a request, then Start and click the AI input.")
            plan_view.delete("1.0", "end")

        def screen_tick():
            if not window.winfo_exists():
                return
            s = screen_state
            now = time.monotonic()
            try:
                if s["phase"] == "await_click":
                    if now - s["selected_at"] >= INPUT_CLICK_SECONDS:
                        s["phase"] = "stopped"
                        screen_status.set("No AI input click captured within 10s. Press Start and try again.")
                    else:
                        down, position = windows_mouse_snapshot()
                        if s["mouse_was_down"] and not down:
                            hwnd, owner_pid = windows_window_at(position)
                            if hwnd and owner_pid != os.getpid():
                                s["target"] = position
                                s["target_hwnd"] = hwnd
                                s["phase"] = "sending_prompt"
                                screen_status.set("AI input selected. Sending preprompt and request...")
                                # Delay gives the target app time to take keyboard focus.
                                window.after(250, screen_dispatch_prompt)
                        s["mouse_was_down"] = down
                        if s["phase"] == "await_click":
                            remaining = max(0, int(INPUT_CLICK_SECONDS - (now - s["selected_at"])) + 1)
                            screen_status.set(f"Click the AI input field now. {remaining}s remaining.")
                elif s["phase"] == "watching" and not s["paused"]:
                    # Keep the latest AI output visible. Never scroll while a
                    # screenshot/OCR capture is in progress.
                    if (not s["busy"] and
                            now - s["last_scroll"] >= RESPONSE_SCROLL_INTERVAL_SECONDS):
                        screen_scroll_response()
                    # OCR starts exactly 5s after the preprompt + request are sent.
                    if now - s["request_sent_at"] < OCR_START_DELAY_SECONDS:
                        remaining = OCR_START_DELAY_SECONDS - (now - s["request_sent_at"])
                        screen_status.set(f"Request sent; scrolling response. OCR starts in {remaining:.1f}s.")
                    else:
                        if not s["busy"] and now - s["last_read"] >= OCR_POLL_SECONDS:
                            s["last_read"] = now
                            screen_read()
                    if (now - s["request_sent_at"] >= OCR_START_DELAY_SECONDS and
                            not s["busy"] and builder_ocr_plan_ready(s["collected"], s["last_change"], now, QUIET_SECONDS)):
                        s["pending"] = sorted(s["collected"].items())
                        s["phase"] = "injecting"
                        s["last_send"] = 0.0
                        activity_line(f"OCR PLAN QUIET FOR 20s: {len(s['pending'])} lines loaded into injector.")
                        screen_status.set(f"Plan collected ({len(s['pending'])} steps). Injection begins now.")
                    elif s["collected"]:
                        elapsed = min(QUIET_SECONDS, now - s["last_change"])
                        missing = sorted(set(range(1, max(s["collected"]) + 1)) - set(s["collected"]))
                        if missing:
                            screen_status.set(f"Found {len(s['collected'])} lines; waiting for missing numbers: {missing[:8]}")
                        else:
                            screen_status.set(f"Found {len(s['collected'])} numbered lines. Quiet timer: {elapsed:.0f}/20s.")
                elif s["phase"] == "injecting" and not s["paused"]:
                    screen_send_next()
            except Exception as exc:
                s["paused"] = True
                screen_status.set("Onscreen paused: " + str(exc))
                activity_line("ONSCREEN ERROR: " + str(exc))
            window.after(25 if s["phase"] == "await_click" else 100, screen_tick)

        def screen_dispatch_prompt():
            s = screen_state
            if s["phase"] != "sending_prompt":
                return
            try:
                screen_paste(s["prompt"])
            except Exception as exc:
                s["phase"] = "stopped"
                screen_status.set("Request not injected: " + str(exc))
                activity_line("ONSCREEN REQUEST ERROR: " + str(exc))
            else:
                s["phase"] = "watching"
                s["request_sent_at"] = time.monotonic()
                s["last_scroll"] = 0.0
                s["last_read"] = 0.0
                activity_line("ONSCREEN: preprompt + request submitted to chosen AI input.")
                screen_status.set("Request sent. Scrolling response area; OCR starts in 5 seconds...")
                # Start scrolling immediately after the first (request) injection.
                try:
                    screen_scroll_response(initial=True)
                    activity_line("ONSCREEN: automatic chat scrolling started; OCR begins after 5s.")
                except Exception as exc:
                    s["paused"] = True
                    s["pause_at"] = time.monotonic()
                    activity_line("ONSCREEN SCROLL ERROR: " + str(exc))
                    screen_status.set("Paused: response scrolling failed. " + str(exc))

        def screen_poll_events():
            if not window.winfo_exists():
                return
            try:
                while True:
                    generation, ok, payload = screen_events.get_nowait()
                    if generation != screen_state["generation"]:
                        continue
                    screen_state["busy"] = False
                    if ok:
                        if screen_state["phase"] != "watching":
                            continue
                        seen_lines = builder_ocr_numbered(payload)
                        seen_lines, ignored = builder_ocr_filter_preprompt(
                            seen_lines, screen_state.get("preprompt", ""))
                        # A plan without step 1 is not an actionable response.
                        # Ignore prior-chat steps until OCR actually sees a valid
                        # first step; do not enqueue contaminated partial lists.
                        if 1 not in screen_state["collected"]:
                            first = next((text for n, text in seen_lines if n == 1), None)
                            if first is None:
                                seen_lines = []
                            else:
                                seen_lines = [(n, t) for n, t in seen_lines if n >= 1]
                        if ignored and not screen_state.get("echo_warning_shown"):
                            activity_line("ONSCREEN: ignored echoed preprompt instructions in OCR.")
                            screen_state["echo_warning_shown"] = True
                        if builder_merge_ocr_lines(screen_state["collected"], seen_lines):
                            screen_state["last_change"] = time.monotonic()
                            ordered = sorted(screen_state["collected"].items())
                            plan_view.delete("1.0", "end")
                            plan_view.insert("1.0", "\n\n".join(f"{n}. {text}" for n, text in ordered))
                            activity_line(f"OCR plan updated: {len(ordered)} numbered steps detected.")
                    else:
                        screen_state["paused"] = True
                        screen_state["pause_at"] = time.monotonic()
                        screen_status.set("OCR failed; paused: " + str(payload))
                        activity_line("OCR ERROR: " + str(payload))
            except queue.Empty:
                pass
            window.after(150, screen_poll_events)

        screen_select_button.configure(command=select_ocr_region)
        screen_start_button.configure(command=screen_start)
        screen_pause_button.configure(command=screen_pause_resume)
        screen_stop_button.configure(command=screen_stop)
        screen_reset_button.configure(command=screen_reset)
        window.after(80, screen_tick)
        window.after(150, screen_poll_events)

        plan_button.configure(command=request_plan)
        start_button.configure(command=start_steps)
        stop_button.configure(command=stop_run)
        control_state()
        window.after(120, poll_builder_events)

        def close_builder():
            job["generation"] += 1
            screen_state["generation"] += 1
            screen_pid_cleaner.clean()
            if screen_pid_cleaner in builder_pid_cleaners:
                builder_pid_cleaners.remove(screen_pid_cleaner)
            screen_state["running"] = False
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
        # Release only processes actually started by Builder before GUI exits.
        for cleaner in list(builder_pid_cleaners):
            cleaner.clean()
        builder_pid_cleaners.clear()
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
