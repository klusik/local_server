"""Shared slate-and-cyan desktop styling and compact accessible controls."""

import math
import tkinter as tk
from tkinter import ttk
from typing import Any, cast


class _ThemeRoot(tk.Tk):
    """Type the image references retained on the application root."""

    _surface_images: list[tk.PhotoImage]


BACKGROUND = "#242D38"
SURFACE = "#28333F"
RAISED = "#303D4A"
INK = "#D5DFE7"
MUTED = "#A6B4C1"
ACCENT = "#76ACB8"


def _rounded_image(
    root: tk.Tk, color: str, radius: int = 6, *, gloss: float = 0.0
) -> tk.PhotoImage:
    """Build a subtly rounded nine-slice surface with antialiased corners.

    Args:
        root (tk.Tk): Tk application owning the theme images and styles.
        color (str): Hexadecimal surface color.
        radius (int): Corner radius in pixels.
        gloss (float): Intensity of the subtle surface highlight.

    Returns:
        tk.PhotoImage: Antialiased rounded surface image retained for the Tk theme
            lifetime.
    """
    size = 24
    image = tk.PhotoImage(master=root, width=size, height=size)
    foreground = tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))
    background = tuple(int(BACKGROUND[i : i + 2], 16) for i in (1, 3, 5))
    rows = []
    for y in range(size):
        row = []
        # Keep the stretched centre quiet; the fixed top/bottom slices carry
        # a soft reflected highlight and a shallow lower shadow.
        highlight = gloss * max(0.0, 1.0 - abs(y - 2) / 6)
        shadow = gloss * 0.45 * max(0.0, (y - (size - 6)) / 5)
        surface = tuple(
            round(channel + (255 - channel) * highlight - channel * shadow)
            for channel in foreground
        )
        for x in range(size):
            cx = min(max(x + 0.5, radius), size - radius)
            cy = min(max(y + 0.5, radius), size - radius)
            coverage = max(
                0.0, min(1.0, radius + 0.5 - math.hypot(x + 0.5 - cx, y + 0.5 - cy))
            )
            rgb = tuple(
                round(b + (f - b) * coverage) for f, b in zip(surface, background)
            )
            row.append("#%02x%02x%02x" % rgb)
        rows.append("{" + " ".join(row) + "}")
    image.put(" ".join(rows))
    return image


def _surface_element(
    style: ttk.Style,
    root: tk.Tk,
    name: str,
    colors: tuple[str, str, str],
    *,
    gloss: float = 0.0,
) -> None:
    """Register rounded state artwork, retaining images for the Tk lifetime.

    Args:
        style (ttk.Style): Tk theme style receiving the rounded artwork.
        root (tk.Tk): Tk application owning the theme images and styles.
        name (str): Unique Tk theme element identifier.
        colors (tuple[str, str, str]): Normal, active and pressed surface colors.
        gloss (float): Intensity of the subtle surface highlight.
    """
    images = [
        _rounded_image(root, color, gloss=gloss * (0.35 if index == 2 else 1.0))
        for index, color in enumerate(colors)
    ]
    cast(_ThemeRoot, root)._surface_images.extend(images)
    style.element_create(
        name,
        "image",
        images[0],
        ("pressed", images[2]),
        ("active", images[1]),
        border=7,
        sticky="nsew",
    )


def apply_theme(root: tk.Tk) -> None:
    """Configure one shared, portable theme without third-party dependencies.

    Args:
        root (tk.Tk): Tk application owning the theme images and styles.
    """
    root.configure(background=BACKGROUND)
    font = (
        "Segoe UI" if root.tk.call("tk", "windowingsystem") == "win32" else "Helvetica",
        10,
    )
    root.option_add("*Font", font)
    root.option_add("*TCombobox*Listbox.background", RAISED)
    root.option_add("*TCombobox*Listbox.foreground", INK)
    root.option_add("*TCombobox*Listbox.selectBackground", "#305266")
    style = ttk.Style(root)
    style.theme_use("clam")
    cast(_ThemeRoot, root)._surface_images = []
    style.configure(
        ".", background=BACKGROUND, foreground=INK, font=font, borderwidth=0
    )
    style.configure("TFrame", background=BACKGROUND)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("TLabel", background=BACKGROUND, foreground=INK)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Card.TLabel", background=SURFACE)
    style.configure(
        "TButton",
        background=RAISED,
        foreground=INK,
        padding=(12, 3),
        relief="flat",
        borderwidth=0,
        focuscolor="#9CBBC5",
    )
    style.configure("Icon.TButton", padding=(6, 3))
    style.map("TButton", foreground=[("disabled", "#788795")])
    style.configure("Primary.TButton", background=ACCENT, foreground=BACKGROUND)
    _surface_element(
        style, root, "Soft.button", (RAISED, "#394956", "#293744"), gloss=0.13
    )
    _surface_element(
        style, root, "Soft.primary", (ACCENT, "#86B6C0", "#679BA7"), gloss=0.15
    )
    for button_style, element in (
        ("TButton", "Soft.button"),
        ("Primary.TButton", "Soft.primary"),
    ):
        style.layout(
            button_style,
            [
                (
                    element,
                    {
                        "sticky": "nsew",
                        "children": [
                            (
                                "Button.focus",
                                {
                                    "sticky": "nsew",
                                    "children": [
                                        (
                                            "Button.padding",
                                            {
                                                "sticky": "nsew",
                                                "children": [
                                                    ("Button.label", {"sticky": "nsew"})
                                                ],
                                            },
                                        )
                                    ],
                                },
                            )
                        ],
                    },
                )
            ],
        )
    style.configure(
        "TEntry",
        fieldbackground=RAISED,
        foreground=INK,
        insertcolor=INK,
        padding=8,
        borderwidth=0,
    )
    style.configure(
        "TCombobox",
        fieldbackground=RAISED,
        background=RAISED,
        foreground=INK,
        arrowcolor=MUTED,
        padding=7,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", RAISED)],
        foreground=[("readonly", INK)],
        selectbackground=[("readonly", RAISED)],
        selectforeground=[("readonly", INK)],
    )
    _surface_element(style, root, "Soft.field", (RAISED, RAISED, RAISED))
    _surface_element(style, root, "Soft.card", (SURFACE, SURFACE, SURFACE), gloss=0.035)
    style.layout("Card.TFrame", [("Soft.card", {"sticky": "nsew"})])
    style.layout(
        "TEntry",
        [
            (
                "Soft.field",
                {
                    "sticky": "nsew",
                    "children": [
                        (
                            "Entry.padding",
                            {
                                "sticky": "nsew",
                                "children": [("Entry.textarea", {"sticky": "nsew"})],
                            },
                        )
                    ],
                },
            )
        ],
    )
    style.layout(
        "TCombobox",
        [
            (
                "Soft.field",
                {
                    "sticky": "nsew",
                    "children": [
                        ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
                        (
                            "Combobox.padding",
                            {
                                "sticky": "nsew",
                                "children": [("Combobox.textarea", {"sticky": "nsew"})],
                            },
                        ),
                    ],
                },
            )
        ],
    )
    style.configure(
        "TNotebook", background=BACKGROUND, borderwidth=0, tabmargins=(0, 0, 0, 12)
    )
    style.configure(
        "TNotebook.Tab",
        background=BACKGROUND,
        foreground=MUTED,
        padding=(18, 6),
        borderwidth=0,
    )
    # The clam tab element changes its inset when selected. Replace it with
    # fixed artwork and padding so selection never changes label geometry.
    tab_images = [
        _rounded_image(root, color, gloss=0.06 if index else 0)
        for index, color in enumerate((BACKGROUND, "#354551", "#2D3945"))
    ]
    cast(_ThemeRoot, root)._surface_images.extend(tab_images)
    style.element_create(
        "Soft.tab",
        "image",
        tab_images[0],
        ("selected", tab_images[1]),
        ("active", tab_images[2]),
        border=7,
        sticky="nsew",
    )
    style.layout(
        "TNotebook.Tab",
        [
            (
                "Soft.tab",
                {
                    "sticky": "nsew",
                    "children": [
                        (
                            "Notebook.padding",
                            {
                                "sticky": "nsew",
                                "children": [
                                    (
                                        "Notebook.focus",
                                        {
                                            "sticky": "nsew",
                                            "children": [
                                                ("Notebook.label", {"sticky": "nsew"})
                                            ],
                                        },
                                    )
                                ],
                            },
                        )
                    ],
                },
            )
        ],
    )
    style.map(
        "TNotebook.Tab",
        foreground=[("selected", "#B8CED5")],
        padding=[("selected", (18, 6)), ("!selected", (18, 6))],
        expand=[("selected", (0, 0, 0, 0)), ("!selected", (0, 0, 0, 0))],
    )
    style.layout("TNotebook", [("Notebook.client", {"sticky": "nsew"})])
    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=INK,
        rowheight=38,
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "Treeview.Heading",
        background=BACKGROUND,
        foreground=MUTED,
        padding=(10, 10),
        relief="flat",
        borderwidth=0,
    )
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nsew"})])
    style.layout(
        "Treeview.Heading",
        [
            (
                "Treeheading.padding",
                {
                    "sticky": "nsew",
                    "children": [
                        ("Treeheading.image", {"side": "right", "sticky": ""}),
                        ("Treeheading.text", {"sticky": "we"}),
                    ],
                },
            )
        ],
    )
    style.map(
        "Treeview", background=[("selected", "#394D5A")], foreground=[("selected", INK)]
    )
    style.configure(
        "Vertical.TScrollbar",
        background=RAISED,
        troughcolor=SURFACE,
        borderwidth=0,
        arrowsize=12,
    )
    style.configure(
        "Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor=SURFACE,
        borderwidth=0,
        thickness=7,
    )


class Tooltip:
    """Expose icon action names on hover and keyboard focus."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        """Bind hover and focus events to accessible action help.

        Args:
            widget (tk.Widget): Tk widget receiving tooltip bindings.
            text (str): Human-readable tooltip or diagnostic text.
        """
        self.widget = widget
        self.text = text
        self.popup: tk.Toplevel | None = None
        self.pending: str | None = None
        for event in ("<Enter>", "<FocusIn>"):
            widget.bind(event, self._schedule, add="+")
        for event in ("<Leave>", "<FocusOut>", "<ButtonPress>", "<Destroy>"):
            widget.bind(event, self._hide, add="+")

    def _schedule(self, _event: tk.Event) -> None:
        """Schedule tooltip display after hover or keyboard focus.

        Args:
            _event (tk.Event): Event payload supplied by Tk; unused fields are ignored.
        """
        self._hide()
        self.pending = self.widget.after(450, self._show)

    def _show(self) -> None:
        """Display the tooltip below its owning widget."""
        self.pending = None
        self.popup = tk.Toplevel(self.widget)
        self.popup.overrideredirect(True)
        self.popup.geometry(
            f"+{self.widget.winfo_rootx()}"
            f"+{self.widget.winfo_rooty() + self.widget.winfo_height() + 6}"
        )
        tk.Label(
            self.popup,
            text=self.text,
            background=RAISED,
            foreground=INK,
            padx=10,
            pady=6,
        ).pack()

    def _hide(self, _event: tk.Event | None = None) -> None:
        """Cancel pending tooltip display and destroy its popup.

        Args:
            _event (tk.Event | None): Event payload supplied by Tk; unused fields are
                ignored.
        """
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None


def icon_button(parent: tk.Misc, glyph: str, label: str, **kwargs: Any) -> ttk.Button:
    """Create a compact icon action with discoverable keyboard help.

    Args:
        parent (tk.Misc): Tk parent that owns this widget or dialog.
        glyph (str): Compact text symbol identifying the action.
        label (str): Human-readable accessible control label.
        kwargs (Any): Keyword options forwarded to the underlying Tk button.

    Returns:
        ttk.Button: Configured compact button with keyboard-accessible tooltip help.
    """
    kwargs.setdefault("style", "Icon.TButton")
    button = ttk.Button(parent, text=glyph, width=2, **kwargs)
    Tooltip(button, label)
    return button


class ToggleSwitch(tk.Canvas):
    """Boolean pill switch with mouse, Space and Return interaction."""

    def __init__(self, parent: tk.Misc, *, variable: tk.BooleanVar, label: str) -> None:
        """Bind an accessible pill control to a Tk boolean variable.

        Args:
            parent (tk.Misc): Tk parent that owns this widget or dialog.
            variable (tk.BooleanVar): Tk boolean variable storing the switch state.
            label (str): Human-readable accessible control label.
        """
        super().__init__(
            parent,
            width=210,
            height=36,
            background=BACKGROUND,
            highlightthickness=0,
            takefocus=True,
            cursor="hand2",
        )
        self.variable = variable
        self.label = label
        self._trace = variable.trace_add("write", self._draw)
        self.bind("<Button-1>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<Return>", self._toggle)
        self.bind("<FocusIn>", self._draw)
        self.bind("<FocusOut>", self._draw)
        self.bind("<Destroy>", self._cleanup)
        self._draw()

    def _toggle(self, _event: tk.Event) -> str:
        """Toggle the bound boolean state after a keyboard or mouse event.

        Args:
            _event (tk.Event): Event payload supplied by Tk; unused fields are ignored.

        Returns:
            str: Tk break sentinel preventing further handling of the toggle event.
        """
        self.focus_set()
        self.variable.set(not self.variable.get())
        return "break"

    def _draw(self, *_args: object) -> None:
        """Redraw the switch value and keyboard focus state.

        Args:
            _args (object): Event payload supplied by Tk; unused fields are ignored.
        """
        self.delete("all")
        on = self.variable.get()
        color = ACCENT if on else "#4A5A69"
        self.create_line(17, 18, 39, 18, fill=color, width=26, capstyle="round")
        x = 39 if on else 17
        self.create_oval(x - 9, 9, x + 9, 27, fill=INK, outline="")
        self.create_text(66, 18, text=self.label, anchor="w", fill=INK)
        if self.focus_get() == self:
            self.create_rectangle(1, 1, 208, 34, outline="#91B6C0", dash=(3, 3))

    def _cleanup(self, event: tk.Event) -> None:
        """Remove the variable trace when the owning switch is destroyed.

        Args:
            event (tk.Event): Event payload supplied by Tk; unused fields are ignored.
        """
        if event.widget == self:
            self.variable.trace_remove("write", self._trace)
