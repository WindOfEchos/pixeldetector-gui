import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

from pixeldetector import repair_image


IMAGE_TYPES = [
    ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
    ("All files", "*.*"),
]

SCALE_OPTIONS = ["Auto", "2x", "3x", "4x", "6x", "8x", "12x", "16x"]
DOWNSCALE_METHOD_OPTIONS = ["Fast median", "Quality k-means"]
PALETTE_METHOD_OPTIONS = ["Fast fixed", "Auto detect"]

HELP_TEXT = {
    "scale": (
        "Controls how much the input is reduced to recover the original pixel grid.\n\n"
        "Auto detects the scale from pixel edges. Choose a manual value when detection is wrong. "
        "Example: if a 16x16 sprite was enlarged to 64x64, use 4x to return it to 16x16."
    ),
    "centroids": (
        "Controls how many color candidates are tested inside each recovered pixel.\n\n"
        "Lower values remove JPEG noise more aggressively. Higher values can preserve noisy details. "
        "Example: keep 2 for most pixel art, try 3-4 if small highlights disappear."
    ),
    "separate_xy_scale": (
        "Lets the app use different horizontal and vertical scales.\n\n"
        "Enable it only when the image was stretched unevenly. Example: a sprite scaled 4x wide and 3x tall. "
        "Leave it off for normal pixel art to keep square pixels."
    ),
    "downscale_method": (
        "Changes how each enlarged pixel block becomes one output pixel.\n\n"
        "Fast median is quick and removes common compression noise. Quality k-means can keep more subtle colors, "
        "but is much slower. Example: use Fast median for screenshots, Quality k-means for small detailed sprites."
    ),
    "palette_method": (
        "Applies only when Reduce palette is enabled.\n\n"
        "Fast fixed limits the result to Max colors. Auto detect searches for a suitable palette size up to Max colors, "
        "but can be slow. Example: set Max colors to 16 with Fast fixed for strict 16-color art."
    ),
}


class HelpButton(ttk.Button):
    def __init__(self, master, title, text):
        super().__init__(master, text="?", width=2, command=self._show_help)
        self.title = title
        self.text = text
        self.tooltip = None
        self.bind("<Enter>", self._show_tooltip)
        self.bind("<Leave>", self._hide_tooltip)

    def _show_help(self):
        messagebox.showinfo(self.title, self.text)

    def _show_tooltip(self, _event):
        if self.tooltip is not None:
            return

        x = self.winfo_rootx() + self.winfo_width() + 6
        y = self.winfo_rooty()
        self.tooltip = tk.Toplevel(self)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        label = ttk.Label(self.tooltip, text=self.text, padding=8, wraplength=300, relief="solid", borderwidth=1)
        label.pack()

    def _hide_tooltip(self, _event):
        if self.tooltip is not None:
            self.tooltip.destroy()
            self.tooltip = None


class PixelDetectorApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Pixel Detector")
        self.resizable(False, False)

        self.input_path = tk.StringVar()
        self.reduce_palette = tk.BooleanVar(value=False)
        self.max_colors = tk.IntVar(value=128)
        self.scale = tk.StringVar(value="Auto")
        self.centroids = tk.IntVar(value=2)
        self.separate_xy_scale = tk.BooleanVar(value=False)
        self.downscale_method = tk.StringVar(value="Fast median")
        self.palette_method = tk.StringVar(value="Fast fixed")
        self.advanced_visible = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Choose an input image to begin.")
        self.preview_info = tk.StringVar(value="Preview is not generated yet.")
        self.preview_photo = None
        self.result_image = None
        self.result_stats = None
        self.save_button = None
        self.advanced_frame = None

        self._build_ui()
        self._watch_settings()

    def _build_ui(self):
        frame = ttk.Frame(self, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, sticky="nsew")

        preview = ttk.LabelFrame(frame, text="Preview", padding=10)
        preview.grid(row=0, column=1, padx=(16, 0), sticky="n")

        ttk.Label(controls, text="Input image").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.input_path, width=30).grid(row=1, column=0, padx=(0, 8), sticky="ew")
        ttk.Button(controls, text="Browse...", command=self._choose_input).grid(row=1, column=1)

        options = ttk.Frame(controls)
        options.grid(row=2, column=0, columnspan=2, pady=(12, 0), sticky="w")

        ttk.Checkbutton(options, text="Reduce palette", variable=self.reduce_palette).grid(row=0, column=0, sticky="w")
        ttk.Label(options, text="Max colors").grid(row=0, column=1, padx=(18, 6), sticky="w")
        ttk.Spinbox(options, from_=1, to=256, textvariable=self.max_colors, width=8).grid(row=0, column=2, sticky="w")

        advanced_toggle = ttk.Checkbutton(
            controls,
            text="Advanced settings",
            variable=self.advanced_visible,
            command=self._toggle_advanced,
        )
        advanced_toggle.grid(row=3, column=0, columnspan=2, pady=(12, 0), sticky="w")

        self.advanced_frame = ttk.LabelFrame(controls, text="Advanced", padding=10)
        ttk.Label(self.advanced_frame, text="Scale").grid(row=0, column=0, sticky="w")
        ttk.Combobox(self.advanced_frame, textvariable=self.scale, values=SCALE_OPTIONS, width=8, state="readonly").grid(row=0, column=1, padx=(8, 4), sticky="w")
        HelpButton(self.advanced_frame, "Scale", HELP_TEXT["scale"]).grid(row=0, column=2, sticky="w")

        ttk.Label(self.advanced_frame, text="Centroids").grid(row=1, column=0, pady=(8, 0), sticky="w")
        ttk.Spinbox(self.advanced_frame, from_=1, to=16, textvariable=self.centroids, width=8).grid(row=1, column=1, padx=(8, 4), pady=(8, 0), sticky="w")
        HelpButton(self.advanced_frame, "Centroids", HELP_TEXT["centroids"]).grid(row=1, column=2, pady=(8, 0), sticky="w")

        ttk.Checkbutton(self.advanced_frame, text="Allow separate X/Y scale", variable=self.separate_xy_scale).grid(row=2, column=0, columnspan=2, pady=(8, 0), sticky="w")
        HelpButton(self.advanced_frame, "Allow separate X/Y scale", HELP_TEXT["separate_xy_scale"]).grid(row=2, column=2, pady=(8, 0), sticky="w")

        ttk.Label(self.advanced_frame, text="Downscale method").grid(row=3, column=0, pady=(8, 0), sticky="w")
        ttk.Combobox(self.advanced_frame, textvariable=self.downscale_method, values=DOWNSCALE_METHOD_OPTIONS, width=16, state="readonly").grid(row=3, column=1, padx=(8, 4), pady=(8, 0), sticky="w")
        HelpButton(self.advanced_frame, "Downscale method", HELP_TEXT["downscale_method"]).grid(row=3, column=2, pady=(8, 0), sticky="w")

        ttk.Label(self.advanced_frame, text="Palette method").grid(row=4, column=0, pady=(8, 0), sticky="w")
        ttk.Combobox(self.advanced_frame, textvariable=self.palette_method, values=PALETTE_METHOD_OPTIONS, width=16, state="readonly").grid(row=4, column=1, padx=(8, 4), pady=(8, 0), sticky="w")
        HelpButton(self.advanced_frame, "Palette method", HELP_TEXT["palette_method"]).grid(row=4, column=2, pady=(8, 0), sticky="w")

        actions = ttk.Frame(controls)
        actions.grid(row=5, column=0, columnspan=2, pady=(14, 0), sticky="ew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Run", command=self._run).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.save_button = ttk.Button(actions, text="Save as...", command=self._save_as, state="disabled")
        self.save_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        ttk.Label(controls, textvariable=self.status, wraplength=360, justify="left", width=52).grid(row=6, column=0, columnspan=2, pady=(10, 0), sticky="w")

        self.preview_label = ttk.Label(preview, text="No preview", anchor="center", width=48)
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        ttk.Label(preview, textvariable=self.preview_info, wraplength=340, justify="left").grid(row=1, column=0, pady=(10, 0), sticky="w")

    def _choose_input(self):
        path = filedialog.askopenfilename(title="Choose input image", filetypes=IMAGE_TYPES)
        if not path:
            return

        self.input_path.set(path)

    def _run(self):
        input_path = self.input_path.get().strip()

        if not input_path:
            messagebox.showerror("Missing input", "Choose an input image first.")
            return

        self.status.set("Processing...")
        self.update_idletasks()

        try:
            image = Image.open(input_path).convert("RGB")
            stats = repair_image(
                image,
                self.max_colors.get(),
                self.reduce_palette.get(),
                self._selected_scale(),
                self.centroids.get(),
                self.separate_xy_scale.get(),
                self._selected_downscale_method(),
                self._selected_palette_method(),
            )
        except Exception as exc:
            self.status.set("Processing failed.")
            messagebox.showerror("Pixel Detector", str(exc))
            return

        self.result_image = stats.pop("image")
        self.result_stats = stats.copy()
        self._show_preview(self.result_image, stats)
        self.save_button.configure(state="normal")
        self.status.set(self._format_status(stats))

    def _save_as(self):
        if self.result_image is None:
            messagebox.showerror("Pixel Detector", "Run processing before saving.")
            return

        default_path = self._default_output_path(self.input_path.get().strip())
        initial_dir = os.path.dirname(default_path) or os.getcwd()
        initial_file = os.path.basename(default_path) or "output_repaired.png"
        path = filedialog.asksaveasfilename(
            title="Save repaired image",
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=os.path.splitext(initial_file)[1] or ".png",
            filetypes=IMAGE_TYPES,
        )
        if not path:
            return

        try:
            self.result_image.save(path)
        except Exception as exc:
            self.status.set("Save failed.")
            messagebox.showerror("Pixel Detector", str(exc))
            return

        self.status.set(f"Saved: {path}")

    def _show_preview(self, image, stats):
        preview_image = image.copy()
        preview_image.thumbnail((480, 480), Image.Resampling.NEAREST)
        self.preview_photo = ImageTk.PhotoImage(preview_image)
        self.preview_label.configure(image=self.preview_photo, text="")
        self.preview_info.set(self._format_preview_info(stats))

    def _format_preview_info(self, stats):
        palette = "disabled"
        if stats["palette_colors"] is not None:
            palette = f"{stats['palette_colors']} colors"

        scale_label = f"{stats['scale']:.2f}x" if isinstance(stats["scale"], float) else f"{stats['scale']}x"
        manual = stats.get("manual_scale")
        mode = f"manual {manual}x" if manual else "auto"

        return (
            f"Input: {stats['input_width']}x{stats['input_height']}\n"
            f"Output: {stats['output_width']}x{stats['output_height']}\n"
            f"Mode: {mode}\n"
            f"Used scale: {scale_label}\n"
            f"Detected X/Y: {stats['horizontal_scale']:.2f}x / {stats['vertical_scale']:.2f}x\n"
            f"Separate X/Y: {'yes' if stats['separate_xy_scale'] else 'no'}\n"
            f"Method: {stats['downscale_method']}\n"
            f"Palette: {palette}\n"
            f"Palette method: {stats['palette_method']}"
        )

    def _format_status(self, stats):
        lines = [
            "Processing finished.",
            f"Size: {stats['input_width']}x{stats['input_height']} -> {stats['output_width']}x{stats['output_height']}",
            f"Resize time: {stats['resize_time_ms']} ms",
        ]

        if stats["palette_colors"] is not None:
            lines.append(f"Palette: {stats['palette_colors']} colors, {stats['palette_time_ms']} ms")

        lines.append("Use Save as to save the result.")
        return "\n".join(lines)

    def _selected_scale(self):
        value = self.scale.get()
        if value == "Auto":
            return None
        return int(value.removesuffix("x"))

    def _selected_downscale_method(self):
        if self.downscale_method.get() == "Quality k-means":
            return "quality"
        return "fast"

    def _selected_palette_method(self):
        if self.palette_method.get() == "Auto detect":
            return "auto"
        return "fixed"

    def _toggle_advanced(self):
        if self.advanced_visible.get():
            self.advanced_frame.grid(row=4, column=0, columnspan=2, pady=(8, 0), sticky="ew")
        else:
            self.advanced_frame.grid_remove()

    def _watch_settings(self):
        for variable in (
            self.input_path,
            self.reduce_palette,
            self.max_colors,
            self.scale,
            self.centroids,
            self.separate_xy_scale,
            self.downscale_method,
            self.palette_method,
        ):
            variable.trace_add("write", self._mark_result_dirty)

    def _mark_result_dirty(self, *_args):
        if self.result_image is None:
            return

        self.result_image = None
        self.result_stats = None
        self.save_button.configure(state="disabled")
        self.status.set("Settings changed. Run again to refresh the result.")

    @staticmethod
    def _default_output_path(input_path):
        if not input_path:
            return ""

        folder, filename = os.path.split(input_path)
        name, ext = os.path.splitext(filename)
        return os.path.join(folder, f"{name}_repaired{ext or '.png'}")


if __name__ == "__main__":
    app = PixelDetectorApp()
    app.mainloop()
