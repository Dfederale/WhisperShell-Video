
"""WhisperShell ORIGINAL: reusable module capability hints."""

from dataclasses import dataclass
import tkinter as tk


@dataclass(frozen=True)
class CapabilityRange:
    name: str
    min_ram_gib: float
    max_ram_gib: float
    platforms: tuple[str, ...] = ()
    mode: str = ""

    def __post_init__(self):
        if self.min_ram_gib < 0 or self.max_ram_gib < self.min_ram_gib:
            raise ValueError("Invalid RAM range")

    def describe(self, available_gib=None):
        lines = [
            self.name,
            f"Estimated additional RAM: "
            f"{self.min_ram_gib:g}-{self.max_ram_gib:g} GiB",
        ]

        if self.platforms:
            lines.append("Platforms: " + ", ".join(self.platforms))

        if self.mode:
            lines.append("Mode: " + self.mode)

        if available_gib is not None:
            lines.append(f"Available now: {available_gib:.2f} GiB")

            if available_gib < self.min_ram_gib:
                lines.append("WARNING: Below estimated minimum")
            elif available_gib < self.max_ram_gib:
                lines.append("CAUTION: Limited memory headroom")

        return "\n".join(lines)


class HoverHint:
    """Show a tooltip beside any Tkinter widget."""

    def __init__(self, widget, text, delay_ms=350):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.job = None
        self.popup = None

        widget.bind("<Enter>", self.schedule, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def schedule(self, event=None):
        self.hide()
        self.job = self.widget.after(self.delay_ms, self.show)

    def show(self):
        self.job = None
        message = self.text() if callable(self.text) else self.text

        if not message or not self.widget.winfo_exists():
            return

        self.popup = tk.Toplevel(self.widget)
        self.popup.wm_overrideredirect(True)

        x = self.widget.winfo_pointerx() + 16
        y = self.widget.winfo_pointery() + 18
        self.popup.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            self.popup,
            text=message,
            justify="left",
            background="#fff8dc",
            foreground="#202020",
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=8,
        )
        label.pack()

    def hide(self, event=None):
        if self.job is not None:
            self.widget.after_cancel(self.job)
            self.job = None

        if self.popup is not None:
            self.popup.destroy()
            self.popup = None
