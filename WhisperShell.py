"""DINS WhisperShell ORIGINAL | private portable orchestrator front panel.

Launch with: python WhisperShell.py
Headless status: python WhisperShell.py --status

One-file GUI (standard-library tkinter). All paths resolve from this file's
location. This is the PRIVATE original's orchestrator; customer versions must
not expose this full builder/tooling UI.

Shared Field plus Template Bridge are wired: complete profiles can be saved and
applied, preserving stable connection codes. Resident execution and First Touch
execution are explicitly waiting until their modules are installed.
The Script panel saves drafts; it NEVER executes code independently of First
Touch. API credentials are never stored in Shared Field.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
MODULES = ROOT / "modules"
TEMPLATES = ROOT / "templates"
SCRIPTS = ROOT / "tools" / "scripts"
BLUEPRINT = ROOT / "architecture" / "blueprint.json"
CODE = "DINS.WHISPERSHELL.ORCHESTRATOR"
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
INPUT_MODES = tuple(INPUT_SOURCES)
MODULES_TO_SHOW = (
    ("Shared Field", "modules/shared_field.py"),
    ("Template Bridge", "modules/template_bridge.py"),
    ("First Sight", "modules/first_sight.py"),
    ("First Touch", "modules/first_touch.py"),
    ("First Hearing", "modules/first_hearing.py"),
    ("First Response", "modules/first_response.py"),
    ("Delta Voice", "modules/delta_voice.py"),
    ("Resident", "mind/resident.py"),
    ("Jumpcore", "mind/jumpcore.py"),
)


def field_module():
    if not (MODULES / "shared_field.py").is_file():
        raise FileNotFoundError("STEP 01 is missing: modules/shared_field.py")
    if str(MODULES) not in sys.path:
        sys.path.insert(0, str(MODULES))
    import shared_field
    return shared_field


def preference_state() -> dict[str, Any]:
    field = field_module()
    field.register_block(CODE, DEFAULTS)
    result = field.get_block(CODE) or {}
    return result if isinstance(result, dict) else {}


def save_preferences(*, provider: str | None = None, model: str | None = None,
                     template: str | None = None,
                     input_mode: str | None = None,
                     input_source: str | None = None) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if input_mode is not None or input_source is not None:
        previous = preference_state().get("input", {})
        chosen_mode = input_mode if input_mode is not None else previous.get("mode", "Human Input")
        chosen_source = input_source if input_source is not None else previous.get("source", "Text")
        if chosen_mode not in INPUT_MODES:
            raise ValueError("Unknown input mode")
        if not isinstance(chosen_source, str) or not chosen_source.strip():
            raise ValueError("Input source cannot be empty")
        changes["input"] = {
            "mode": chosen_mode,
            "source": chosen_source.strip(),
        }

    if provider is not None or model is not None:
        changes["resident"] = {}
        if provider is not None:
            if provider not in PROVIDERS:
                raise ValueError("Unrecognized provider")
            changes["resident"]["provider"] = provider
        if model is not None:
            changes["resident"]["model"] = model.strip()
    if template is not None:
        template = template.lower().strip()
        if template not in available_templates():
            raise ValueError("Unknown template profile: " + template)
        changes["builder"] = {"template": template}
    if changes:
        return field_module().update_block(CODE, changes)
    return preference_state()


def available_templates() -> list[str]:
    # Show original builder options immediately, including an empty profile.
    options = ["default", "robotics", "custom"]
    if TEMPLATES.is_dir():
        options += [p.name for p in TEMPLATES.iterdir() if p.is_dir()]
    return list(dict.fromkeys(options))


def bridge_ready() -> bool:
    return (MODULES / "template_bridge.py").is_file()


def bridge_module():
    if not bridge_ready():
        raise FileNotFoundError("Template Bridge missing: modules/template_bridge.py")
    if str(MODULES) not in sys.path:
        sys.path.insert(0, str(MODULES))
    import template_bridge
    return template_bridge


def capture_template(name: str) -> Path:
    """Remember active profile, then capture the complete Shared Field."""
    save_preferences(template=name)
    return bridge_module().save_profile(name)


def apply_template(name: str) -> int:
    """Restore the complete captured state; then label selected profile."""
    new_revision = bridge_module().apply_profile(name)
    save_preferences(template=name)
    return new_revision


def touch_ready() -> bool:
    return (MODULES / "first_touch.py").is_file()


def read_blueprint() -> dict[str, Any]:
    """Load our source-backed MASTER PLAN as DATA, not executable modules.

    This is private engineering metadata only. The blueprint does not silently
    start any component or create missing capabilities.
    """
    with BLUEPRINT.open("r", encoding="utf-8") as handle:
        plan = json.load(handle)
    if plan.get("format") != "DINS.WhisperShell.Original.Blueprint" or plan.get("schema_version") != 1:
        raise ValueError("Unknown master blueprint format/version")
    if not isinstance(plan.get("components"), list):
        raise ValueError("Master blueprint components must be a list")
    return plan


def blueprint_inventory() -> dict[str, Any]:
    """Actual files vs designs; never mistake a schematic for running software."""
    plan = read_blueprint()
    entries = []
    for item in plan["components"]:
        path = ROOT / item["path"]
        entries.append({
            "id": item["id"], "name": item["name"],
            "region": item["region"], "phase": item["phase"],
            "source_file_present": path.is_file(), "path": item["path"],
            "schematics": item.get("sources", []),
        })
    return {"schema_version": plan["schema_version"],
            "diagrams_archived": len(plan.get("diagram_index", [])),
            "components": entries,
            "note": "Source-file presence does not guarantee the component runs or is connected."}


def status() -> dict[str, Any]:
    state = preference_state()
    return {
        "root": str(ROOT),
        "field_revision": field_module().revision(),
        "orchestrator": state,
        "modules": {name: (ROOT / path).is_file() for name, path in MODULES_TO_SHOW},
        "templates": (bridge_module().list_profiles() if bridge_ready() else []),
        "master_blueprint": {
            "present": BLUEPRINT.is_file(),
            "component_count": len(read_blueprint()["components"]) if BLUEPRINT.is_file() else 0,
        },
        "note": "File-present means installed, not necessarily connected or running.",
    }


def ollama_models() -> list[str]:
    """Optional LOCAL discovery only; no network/cloud call."""
    try:
        req = Request("http://127.0.0.1:11434/api/tags", headers={"Accept": "application/json"})
        with urlopen(req, timeout=1.5) as response:
            data = json.load(response)
        return sorted({m["name"] for m in data.get("models", [])
                       if isinstance(m, dict) and isinstance(m.get("name"), str)})
    except (URLError, TimeoutError, OSError, ValueError, KeyError):
        return []


def safe_script_path(name: str, language: str) -> Path:
    ext = {"Python": ".py", "PowerShell": ".ps1", "CMD": ".cmd"}[language]
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", name):
        raise ValueError("Use a simple filename (letters, digits, dots, _ or -).")
    return SCRIPTS / (name if name.lower().endswith(ext) else name + ext)


def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError as exc:
        raise RuntimeError("Tkinter is not installed. Use --status for headless mode.") from exc

    state = preference_state()
    app = tk.Tk()
    app.title("DINS WhisperShell | ORIGINAL · Private Orchestrator")
    app.geometry("890x680")
    app.minsize(700, 530)
    app.option_add("*Font", "TkDefaultFont")
    notebook = ttk.Notebook(app)
    notebook.pack(fill="both", expand=True, padx=14, pady=12)

    main = ttk.Frame(notebook, padding=18)
    resident = ttk.Frame(notebook, padding=18)
    builder = ttk.Frame(notebook, padding=18)
    scripts = ttk.Frame(notebook, padding=18)
    blocks = ttk.Frame(notebook, padding=18)
    blueprint = ttk.Frame(notebook, padding=18)
    monitor = ttk.Frame(notebook, padding=18)
    notebook.add(main, text="  Home / Body  ")
    notebook.add(monitor, text="  Monitor  ")
    notebook.add(resident, text="  Input / Resident  ")
    notebook.add(builder, text="  Original Builder  ")
    notebook.add(scripts, text="  Script / First Touch  ")
    notebook.add(blocks, text="  Block Workshop  ")
    notebook.add(blueprint, text="  Master Blueprint  ")

    # Resource Monitor: reads the operating system, not Shared Field estimates.
    field_module()
    import resource_monitor
    from capability_hints import HoverHint

    ttk.Label(
        monitor, text="Resource Monitor",
        font=("Segoe UI", 17, "bold")
    ).pack(anchor="w")

    ttk.Label(
        monitor,
        text="Live system RAM and running processes. "
             "Module hardware requirements will connect here later.",
        wraplength=750
    ).pack(anchor="w", pady=(5, 15))

    ram_text = tk.StringVar(value="Reading memory...")
    ttk.Label(
        monitor, textvariable=ram_text,
        font=("Consolas", 11)
    ).pack(anchor="w", pady=(0, 8))

    ram_bar = ttk.Progressbar(
        monitor, orient="horizontal",
        mode="determinate", maximum=100
    )
    ram_bar.pack(fill="x", pady=(0, 15))

    def monitor_ram_hint():
        snapshot = resource_monitor.memory_snapshot()
        available = resource_monitor.gib(snapshot["available_bytes"])

        return (
            f"Available now: {available:.2f} GiB\\n"
            "Live operating-system measurement.\\n"
            "Future module toggles will show their own RAM ranges."
        )

    HoverHint(ram_bar, monitor_ram_hint)

    ttk.Label(
        monitor, text="Largest running processes",
        font=("Segoe UI", 12, "bold")
    ).pack(anchor="w")

    process_box = tk.Text(
        monitor, height=14, width=85,
        font=("Consolas", 10), state="disabled"
    )
    process_box.pack(fill="both", expand=True, pady=(8, 12))

    def refresh_ram():
        try:
            info = resource_monitor.memory_snapshot()
            total = resource_monitor.gib(info["total_bytes"])
            used = resource_monitor.gib(info["used_bytes"])
            available = resource_monitor.gib(info["available_bytes"])

            ram_text.set(
                f"Total: {total:.2f} GiB   "
                f"Used: {used:.2f} GiB   "
                f"Available: {available:.2f} GiB   "
                f"Load: {info['used_percent']}%"
            )
            ram_bar["value"] = info["used_percent"]
        except Exception as exc:
            ram_text.set("Memory reading failed: " + str(exc))

        app.after(3000, refresh_ram)

    def refresh_processes():
        try:
            processes = resource_monitor.top_processes(12)
            lines = [
                f"{p['name'][:27]:<28} "
                f"{p['memory_bytes'] / 1048576:>8.1f} MB  "
                f"PID {p['pid']}"
                for p in processes
            ]
        except Exception as exc:
            lines = ["Process reading failed: " + str(exc)]

        process_box.configure(state="normal")
        process_box.delete("1.0", "end")
        process_box.insert("1.0", "\n".join(lines))
        process_box.configure(state="disabled")

    ttk.Button(
        monitor, text="Refresh process list",
        command=refresh_processes
    ).pack(anchor="w")

    refresh_ram()
    refresh_processes()

    ttk.Label(main, text="WhisperShell ORIGINAL", font=("Segoe UI", 20, "bold")).pack(anchor="w")
    ttk.Label(main, text="Private orchestrator  |  Portable folder  |  Expandable Shared Field").pack(anchor="w", pady=(4, 14))
    ttk.Label(main, text="Current module inventory (installed file ≠ running component):").pack(anchor="w")
    inventory = tk.Text(main, height=15, width=72, state="disabled", wrap="none")
    inventory.pack(fill="both", expand=True, pady=(8, 10))

    def refresh_inventory():
        info = status()
        lines = [f"ROOT  {info['root']}", f"SHARED FIELD REVISION  {info['field_revision']}", ""]
        for label, exists in info["modules"].items():
            lines.append(f"{'FILE PRESENT' if exists else 'NOT INSTALLED':<15}  {label}")
        lines += ["", "An installed module still needs its runtime connection.",
                  "The mind and body's additional modules are built step by step."]
        inventory.configure(state="normal")
        inventory.delete("1.0", "end")
        inventory.insert("1.0", "\n".join(lines))
        inventory.configure(state="disabled")

    ttk.Button(main, text="Refresh module inventory", command=refresh_inventory).pack(anchor="w")
    refresh_inventory()

    ttk.Label(resident, text="Input / Resident Picker", font=("Segoe UI", 17, "bold")).pack(anchor="w")

    ttk.Label(
        resident,
        text="Five entry paths into one orchestrator. Selecting a path does not start it.",
        wraplength=750,
    ).pack(anchor="w", pady=(6, 12))

    saved_input = state.get("input", {})
    saved_mode = saved_input.get("mode", "Human Input")
    if saved_mode not in INPUT_MODES:
        saved_mode = "Human Input"

    input_mode = tk.StringVar(value=saved_mode)
    input_source = tk.StringVar(
        value=saved_input.get("source") or INPUT_SOURCES[saved_mode][0]
    )

    ttk.Label(resident, text="Input mode").pack(anchor="w")
    mode_picker = ttk.Combobox(
        resident, textvariable=input_mode,
        values=INPUT_MODES, state="readonly", width=34
    )
    mode_picker.pack(anchor="w", pady=(3, 12))

    ttk.Label(resident, text="Input source").pack(anchor="w")
    source_picker = ttk.Combobox(
        resident, textvariable=input_source,
        values=INPUT_SOURCES[saved_mode], width=56
    )
    source_picker.pack(anchor="w", pady=(3, 12))

    def on_mode_change(event=None):
        options = INPUT_SOURCES[input_mode.get()]
        source_picker["values"] = options
        input_source.set(options[0])

    mode_picker.bind("<<ComboboxSelected>>", on_mode_change)

    def save_input_choice():
        try:
            save_preferences(
                input_mode=input_mode.get(),
                input_source=input_source.get()
            )
            messagebox.showinfo(
                "Input configuration",
                "Input mode and source saved in Shared Field. "
                "Execution is not connected yet."
            )
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    ttk.Button(
        resident, text="Save Input Choice",
        command=save_input_choice
    ).pack(anchor="w", pady=(0, 16))

    ttk.Separator(resident, orient="horizontal").pack(fill="x", pady=(5, 16))
    ttk.Label(resident, text="Resident Model Configuration",
              font=("Segoe UI", 13, "bold")).pack(anchor="w")
    ttk.Label(resident, text="Choose the model now. Actual inference connects when mind/resident.py is built.",
              wraplength=750).pack(anchor="w", pady=(6, 18))
    provider = tk.StringVar(value=state.get("resident", {}).get("provider", "None"))
    model = tk.StringVar(value=state.get("resident", {}).get("model", ""))
    ttk.Label(resident, text="AI provider (Local / API)").pack(anchor="w")
    ttk.Combobox(resident, textvariable=provider, values=PROVIDERS, state="readonly", width=34).pack(anchor="w", pady=(3, 12))
    ttk.Label(resident, text="Model name / ID").pack(anchor="w")
    model_picker = ttk.Combobox(resident, textvariable=model, values=(), width=56)
    model_picker.pack(anchor="w", pady=(3, 12))

    def scan_models():
        models = ollama_models()
        model_picker["values"] = models
        messagebox.showinfo("Local models", f"Found {len(models)} Ollama model(s)." if models else
                            "No Ollama models found on 127.0.0.1:11434.\nYou can still type a model name.")

    ttk.Button(resident, text="Discover local Ollama models", command=scan_models).pack(anchor="w", pady=(0, 16))

    def save_model():
        try:
            save_preferences(provider=provider.get(), model=model.get())
            messagebox.showinfo("Resident configuration", "Selection stored in Shared Field.\nNo model started yet.")
            refresh_inventory()
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    ttk.Button(resident, text="Save Resident choice", command=save_model).pack(anchor="w")
    ttk.Label(resident, text="API secrets never belong in Shared Field. They will be handled privately when the Resident is wired.",
              wraplength=750).pack(anchor="w", pady=(25, 0))

    ttk.Label(builder, text="Original builder", font=("Segoe UI", 17, "bold")).pack(anchor="w")
    ttk.Label(builder, text="The private original offers every build direction from day one.\n"
              "Profiles are complete Shared Field snapshots managed by Template Bridge, not separate architectures.",
              wraplength=750).pack(anchor="w", pady=(6, 16))
    ttk.Label(builder, text="Template profile").pack(anchor="w")
    template = tk.StringVar(value=state.get("builder", {}).get("template", "default"))
    ttk.Combobox(builder, textvariable=template, values=available_templates(),
                 state="readonly", width=34).pack(anchor="w", pady=(3, 13))

    def choose_template():
        try:
            save_preferences(template=template.get())
            messagebox.showinfo("Builder selection", "Profile choice stored in Shared Field.\n"
                                "Use Capture to save it or Apply to restore it.")
        except Exception as exc:
            messagebox.showerror("Builder error", str(exc))

    ttk.Button(builder, text="Remember selected profile", command=choose_template).pack(anchor="w")
    ttk.Separator(builder, orient="horizontal").pack(fill="x", pady=20)
    bridge_status = ("Template Bridge connected: full Shared Field snapshots available." if bridge_ready() else
                     "Template Bridge pending: modules/template_bridge.py is not built yet.")
    ttk.Label(builder, text=bridge_status).pack(anchor="w", pady=(0, 12))
    def capture_selected():
        target = template.get()
        if not messagebox.askyesno("Capture entire Shared Field?",
                                  f"Overwrite snapshot for '{target}' with ALL current module blocks?"):
            return
        try:
            path = capture_template(target)
            messagebox.showinfo("Profile captured", f"Saved complete snapshot:\n{path}")
            refresh_inventory()
        except Exception as exc:
            messagebox.showerror("Capture failed", str(exc))

    def apply_selected():
        target = template.get()
        if not messagebox.askyesno("Restore complete profile?",
                                  f"Apply snapshot '{target}' to the LIVE Shared Field?\n"
                                  "Captured blocks will be replaced. Newer unrelated blocks remain."):
            return
        try:
            rev = apply_template(target)
            messagebox.showinfo("Profile restored", f"'{target}' applied; revision {rev}.\n"
                                "Connected modules observe changes on their next read/poll.")
            refresh_inventory()
        except Exception as exc:
            messagebox.showerror("Restore failed", str(exc))

    ttk.Button(builder, text="Capture complete profile", command=capture_selected,
               state=("normal" if bridge_ready() else "disabled")).pack(anchor="w", pady=(0, 7))
    ttk.Button(builder, text="Apply saved profile", command=apply_selected,
               state=("normal" if bridge_ready() else "disabled")).pack(anchor="w", pady=(0, 7))
    ttk.Button(builder, text="Export customer build (connect packager later)", state="disabled").pack(anchor="w")
    ttk.Label(builder, text="Customer builds retain original module connection codes.\n"
              "This full private builder stays with the ORIGINAL and is not included in customer exports.",
              wraplength=750).pack(anchor="w", pady=(23, 0))

    ttk.Label(scripts, text="Script workspace · First Touch", font=("Segoe UI", 17, "bold")).pack(anchor="w")
    ttk.Label(scripts, text="Draft and save scripts here. Execution belongs to First Touch only, once integrated.",
              wraplength=750).pack(anchor="w", pady=(5, 12))
    line = ttk.Frame(scripts)
    line.pack(fill="x", pady=(0, 8))
    language = tk.StringVar(value="Python")
    name = tk.StringVar(value="new_script")
    ttk.Label(line, text="Language").pack(side="left")
    ttk.Combobox(line, textvariable=language, values=("Python", "PowerShell", "CMD"),
                 width=14, state="readonly").pack(side="left", padx=(8, 18))
    ttk.Label(line, text="Name").pack(side="left")
    ttk.Entry(line, textvariable=name, width=27).pack(side="left", padx=(8, 0))
    editor = tk.Text(scripts, undo=True, font=("Consolas", 10), wrap="none")
    editor.pack(fill="both", expand=True, pady=(4, 12))
    buttons = ttk.Frame(scripts)
    buttons.pack(fill="x")

    def save_script():
        try:
            file = safe_script_path(name.get(), language.get())
            file.parent.mkdir(parents=True, exist_ok=True)
            if file.exists() and not messagebox.askyesno("Replace script?", f"Overwrite {file.name}?"):
                return
            file.write_text(editor.get("1.0", "end-1c"), encoding="utf-8")
            messagebox.showinfo("Script saved", f"Saved to {file.relative_to(ROOT)}\nNothing was executed.")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Script save failed", str(exc))

    ttk.Button(buttons, text="Save draft", command=save_script).pack(side="left")
    ttk.Button(buttons, text="Run with First Touch (not wired yet)", state="disabled").pack(side="left", padx=12)
    ttk.Label(scripts, text=("First Touch file detected; execution API is not connected." if touch_ready()
                             else "First Touch has not been installed yet."),
              wraplength=750).pack(anchor="w", pady=(11, 0))

    # PRIVATE Block Workshop. This is a UI for the existing Shared Field API,
    # not a second implementation of blocks, or a tool shipped to customers.
    ttk.Label(blocks, text="Expandable Block Workshop", font=("Segoe UI", 17, "bold")).pack(anchor="w")
    ttk.Label(blocks, text="Every module keeps its stable connection code. Create a block once; expand it as needed.\n"
              "Blocks live in Shared Field. Template Bridge captures them along with every other section.",
              wraplength=750).pack(anchor="w", pady=(6, 14))
    ttk.Label(blocks, text="Connection code (permanent module identity)").pack(anchor="w")
    block_code = tk.StringVar(value="DINS.EXAMPLE.MODULE")
    ttk.Entry(blocks, textvariable=block_code, width=65).pack(anchor="w", pady=(4, 12))
    ttk.Label(blocks, text="Requested module number").pack(anchor="w")
    new_number = tk.StringVar(value="007")
    ttk.Entry(blocks, textvariable=new_number, width=30).pack(anchor="w", pady=(4, 10))
    ttk.Label(blocks, text="Persistent birth marker file (change for a different physical module)").pack(anchor="w")
    marker_file = tk.StringVar(value="identity_markers/007-a.json")
    ttk.Entry(blocks, textvariable=marker_file, width=65).pack(anchor="w", pady=(4, 12))
    ttk.Label(blocks, text="Initial values / changes as JSON object").pack(anchor="w")
    block_payload = tk.Text(blocks, height=8, width=85, font=("Consolas", 10), wrap="none")
    block_payload.insert("1.0", '{\n  "capabilities": {"enabled": true},\n  "settings": {}\n}')
    block_payload.pack(fill="x", pady=(5, 12))
    block_controls = ttk.Frame(blocks)
    block_controls.pack(fill="x")
    block_result = tk.Text(blocks, height=10, width=85, state="disabled", font=("Consolas", 10))
    block_result.pack(fill="both", expand=True, pady=(14, 0))

    def show_blocks(text):
        block_result.configure(state="normal")
        block_result.delete("1.0", "end")
        block_result.insert("1.0", text)
        block_result.configure(state="disabled")

    def block_json():
        value = json.loads(block_payload.get("1.0", "end-1c"))
        if not isinstance(value, dict):
            raise ValueError("Block content must be a JSON object")
        return value

    def create_block():
        try:
            initial = block_json()
            requested = new_number.get().strip()
            marker_text = marker_file.get().strip()

            if not marker_text or Path(marker_text).is_absolute():
                raise ValueError("Use a relative birth-marker path inside WhisperShell")

            marker = (ROOT / marker_text).resolve()
            if not marker.is_relative_to(ROOT) or marker == ROOT:
                raise ValueError("Birth marker must stay inside WhisperShell")

            field_module()
            import block_registry

            birth = block_registry.birth_marker(marker)
            result = block_registry.claim(requested, birth, initial)

            block_code.set(result["connection_code"])
            show_blocks(json.dumps(result, ensure_ascii=False, indent=2))
            refresh_inventory()

        except (ValueError, TypeError, OSError) as exc:
            messagebox.showerror("Block registration failed", str(exc))

    def expand_block():
        try:
            code = block_code.get().strip()
            if field_module().get_block(code, default=None) is None:
                messagebox.showwarning("Not registered", "Create this module block first.")
                return
            result = field_module().update_block(code, block_json())
            show_blocks(json.dumps(result, ensure_ascii=False, indent=2))
            refresh_inventory()
        except (ValueError, TypeError, OSError) as exc:
            messagebox.showerror("Block expansion failed", str(exc))

    def inspect_block():
        try:
            code = block_code.get().strip()
            result = field_module().get_block(code, default=None)
            show_blocks("Not registered" if result is None else json.dumps(result, ensure_ascii=False, indent=2))
        except (ValueError, TypeError, OSError) as exc:
            messagebox.showerror("Block lookup failed", str(exc))

    def list_blocks():
        state = field_module().load_field()
        show_blocks("Revision: " + str(state["revision"]) + "\n" +
                    "\n".join(sorted(state["blocks"].keys())))

    ttk.Button(block_controls, text="Create new block", command=create_block).pack(side="left")
    ttk.Button(block_controls, text="Expand existing", command=expand_block).pack(side="left", padx=8)
    ttk.Button(block_controls, text="Inspect", command=inspect_block).pack(side="left")
    ttk.Button(block_controls, text="List all", command=list_blocks).pack(side="left", padx=8)
    ttk.Label(blocks, text="A connection code is an address, not a password. Never put API keys in these blocks.",
              wraplength=750).pack(anchor="w", pady=(12, 0))

    # A living blueprint inventory, anchored in the ten historical schematics.
    # Plans stay plans until a module's source is installed and its behavior tested.
    ttk.Label(blueprint, text="Master Blueprint | Body + Mind", font=("Segoe UI", 17, "bold")).pack(anchor="w")
    ttk.Label(blueprint, text="Original historical schematics translated into tracked engineering goals.\n"
              "Working code, planned integration and research are labeled separately.",
              wraplength=760).pack(anchor="w", pady=(6, 14))
    filters = ttk.Frame(blueprint)
    filters.pack(anchor="w", fill="x")
    ttk.Label(filters, text="Region").pack(side="left")
    region = tk.StringVar(value="all")
    ttk.Combobox(filters, textvariable=region,
                 values=("all", "body", "mind", "support", "adapter", "tooling"),
                 width=17, state="readonly").pack(side="left", padx=(8, 20))
    ttk.Label(filters, text="Search").pack(side="left")
    search = tk.StringVar()
    ttk.Entry(filters, textvariable=search, width=27).pack(side="left", padx=(8, 12))
    overview = tk.Text(blueprint, height=22, width=95, state="disabled",
                       wrap="word", font=("Consolas", 9))
    overview.pack(fill="both", expand=True, pady=(12, 10))

    def refresh_blueprint():
        try:
            plan = read_blueprint()
            entries = blueprint_inventory()["components"]
            selected = region.get()
            term = search.get().lower().strip()
            lines = [f"{len(entries)} components | {len(plan['diagram_index'])} archived diagrams",
                     "LEGEND: implemented_tested / partial_tested / planned_integration / designed / research_only",
                     "Source present does NOT mean integrated or running.", ""]
            count = 0
            for item in entries:
                if selected != "all" and item["region"] != selected:
                    continue
                summary = next(x for x in plan["components"] if x["id"] == item["id"])
                searchable = (item["id"] + item["name"] + summary["description"]).lower()
                if term and term not in searchable:
                    continue
                count += 1
                lines.extend([f"[{item['region'].upper()}] {item['name']}",
                              f"  Phase: {item['phase']} | Source: {'PRESENT' if item['source_file_present'] else 'PENDING'}",
                              f"  Path:  {item['path']} | Schematics: {','.join(item['schematics']) or '-'}",
                              f"  {summary['description']}", ""])
            if not count:
                lines.append("No matching components.")
            lines.append("Full technical explanation: docs/MASTER_BLUEPRINT.md")
            lines.append("Original images: docs/schematics/")
            overview.configure(state="normal")
            overview.delete("1.0", "end")
            overview.insert("1.0", "\n".join(lines))
            overview.configure(state="disabled")
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror("Blueprint error", str(exc))

    ttk.Button(blueprint, text="Refresh master plan", command=refresh_blueprint).pack(anchor="w")
    refresh_blueprint()

    app.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="DINS WhisperShell ORIGINAL private orchestrator")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="Print module and configuration status as JSON")
    group.add_argument("--blueprint", action="store_true", help="Print machine-readable blueprint inventory")
    group.add_argument("--templates", action="store_true", help="List available template profiles")
    group.add_argument("--capture", metavar="NAME", help="Capture ALL Shared Field blocks to profile NAME")
    group.add_argument("--apply", metavar="NAME", help="Restore captured NAME into live Shared Field")
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
            print(f"Profile captured: {capture_template(args.capture)}")
        elif args.apply:
            print(f"Profile applied; revision: {apply_template(args.apply)}")
        else:
            run_gui()
    except (FileNotFoundError, RuntimeError, OSError, ValueError, TypeError) as exc:
        print(f"WhisperShell: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
