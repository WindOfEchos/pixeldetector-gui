import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

from pixeldetector import ProcessingCancelled, repair_image


IMAGE_TYPES = [
    ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
    ("All files", "*.*"),
]
SAVE_FORMATS = ["PNG", "Same as input", "JPEG", "WEBP", "BMP"]
FORMAT_EXTENSIONS = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "WEBP": ".webp",
    "BMP": ".bmp",
}
FORMAT_FILETYPES = {
    "PNG": [("PNG image", "*.png")],
    "JPEG": [("JPEG image", "*.jpg *.jpeg")],
    "WEBP": [("WebP image", "*.webp")],
    "BMP": [("Bitmap image", "*.bmp")],
}
INPUT_FORMATS = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".bmp": "BMP",
}
SCALE_OPTIONS = ["Auto", "2x", "3x", "4x", "6x", "8x", "12x", "16x"]
DOWNSCALE_METHOD_OPTIONS = ["Fast median", "Quality k-means"]
PALETTE_METHOD_OPTIONS = ["Fast fixed", "Auto detect"]
DENOISE_OPTIONS = ["Auto", "Off", "Light", "Medium", "Strong"]

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
    "denoise": (
        "Reduces JPEG compression artifacts before detecting and recovering pixels.\n\n"
        "Auto uses Medium for .jpg/.jpeg files and Off for other formats. Strong can remove heavy noise, "
        "but may blur tiny details before recovery."
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
        self.output_format = tk.StringVar(value="PNG")
        self.reduce_palette = tk.BooleanVar(value=False)
        self.max_colors = tk.IntVar(value=128)
        self.scale = tk.StringVar(value="Auto")
        self.centroids = tk.IntVar(value=2)
        self.separate_xy_scale = tk.BooleanVar(value=False)
        self.downscale_method = tk.StringVar(value="Quality k-means")
        self.palette_method = tk.StringVar(value="Auto detect")
        self.denoise_level = tk.StringVar(value="Auto")
        self.advanced_visible = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Choose an input image to begin.")
        self.preview_info = tk.StringVar(value="Preview is not generated yet.")
        self.progress_value = tk.DoubleVar(value=0)
        self.preview_photo = None
        self.result_image = None
        self.result_stats = None
        self.run_button = None
        self.cancel_button = None
        self.save_button = None
        self.advanced_frame = None
        self.progress_bar = None
        self.worker_queue = None
        self.cancel_event = None
        self.processing = False

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

        ttk.Label(controls, text="Output format").grid(row=2, column=0, pady=(8, 0), sticky="w")
        ttk.Combobox(controls, textvariable=self.output_format, values=SAVE_FORMATS, width=16, state="readonly").grid(row=3, column=0, padx=(0, 8), sticky="w")

        options = ttk.Frame(controls)
        options.grid(row=4, column=0, columnspan=2, pady=(12, 0), sticky="w")

        ttk.Checkbutton(options, text="Reduce palette", variable=self.reduce_palette).grid(row=0, column=0, sticky="w")
        ttk.Label(options, text="Max colors").grid(row=0, column=1, padx=(18, 6), sticky="w")
        ttk.Spinbox(options, from_=1, to=256, textvariable=self.max_colors, width=8).grid(row=0, column=2, sticky="w")

        advanced_toggle = ttk.Checkbutton(
            controls,
            text="Advanced settings",
            variable=self.advanced_visible,
            command=self._toggle_advanced,
        )
        advanced_toggle.grid(row=5, column=0, columnspan=2, pady=(12, 0), sticky="w")

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

        ttk.Label(self.advanced_frame, text="JPEG denoise").grid(row=5, column=0, pady=(8, 0), sticky="w")
        ttk.Combobox(self.advanced_frame, textvariable=self.denoise_level, values=DENOISE_OPTIONS, width=16, state="readonly").grid(row=5, column=1, padx=(8, 4), pady=(8, 0), sticky="w")
        HelpButton(self.advanced_frame, "JPEG denoise", HELP_TEXT["denoise"]).grid(row=5, column=2, pady=(8, 0), sticky="w")

        actions = ttk.Frame(controls)
        actions.grid(row=7, column=0, columnspan=2, pady=(14, 0), sticky="ew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=1)
        self.run_button = ttk.Button(actions, text="Run", command=self._run)
        self.run_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_button.grid(row=0, column=1, padx=(0, 6), sticky="ew")
        self.save_button = ttk.Button(actions, text="Save as...", command=self._save_as, state="disabled")
        self.save_button.grid(row=0, column=2, sticky="ew")

        self.progress_bar = ttk.Progressbar(controls, variable=self.progress_value, maximum=100, mode="determinate")
        self.progress_bar.grid(row=8, column=0, columnspan=2, pady=(10, 0), sticky="ew")

        ttk.Label(controls, textvariable=self.status, wraplength=360, justify="left", width=52).grid(row=9, column=0, columnspan=2, pady=(10, 0), sticky="w")

        self.preview_label = ttk.Label(preview, text="No preview", anchor="center", width=48)
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        ttk.Label(preview, textvariable=self.preview_info, wraplength=340, justify="left").grid(row=1, column=0, pady=(10, 0), sticky="w")

    def _choose_input(self):
        path = filedialog.askopenfilename(title="Choose input image", filetypes=IMAGE_TYPES)
        if not path:
            return

        self.input_path.set(path)

    def _run(self):
        if self.processing:
            return

        input_path = self.input_path.get().strip()
        if not input_path:
            messagebox.showerror("Missing input", "Choose an input image first.")
            return

        self.processing = True
        self.result_image = None
        self.result_stats = None
        self.progress_value.set(0)
        self.run_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.save_button.configure(state="disabled")
        self.status.set("Processing...")

        self.worker_queue = queue.Queue()
        self.cancel_event = threading.Event()
        args = self._processing_args(input_path)
        thread = threading.Thread(target=self._run_worker, args=args, daemon=True)
        thread.start()
        self.after(50, self._poll_worker)

    def _processing_args(self, input_path):
        return (
            input_path,
            self.max_colors.get(),
            self.reduce_palette.get(),
            self._selected_scale(),
            self.centroids.get(),
            self.separate_xy_scale.get(),
            self._selected_downscale_method(),
            self._selected_palette_method(),
            self._selected_denoise_level(),
        )

    def _run_worker(self, input_path, max_colors, reduce_palette, scale, centroids, separate_xy_scale, downscale_method, palette_method, denoise_level):
        denoise_end = 15 if denoise_level != "off" else 5
        detect_end = denoise_end + 15 if scale is None else denoise_end
        recover_end = 75 if reduce_palette else 95
        stage_ranges = {
            "Loading image": (0, 5),
            "Denoising JPEG artifacts": (5, denoise_end),
            "Detecting pixel scale": (denoise_end, detect_end),
            "Recovering pixels": (detect_end, recover_end),
            "Detecting palette": (recover_end, 90),
            "Applying palette": (90, 95),
        }

        def progress(message, current, total):
            start, end = stage_ranges.get(message, (0, 95))
            local_percent = 0 if total <= 0 else max(0, min(1, current / total))
            percent = start + (end - start) * local_percent
            self.worker_queue.put(("progress", message, percent, 100))

        try:
            progress("Loading image", 0, 1)
            image = Image.open(input_path).convert("RGB")
            progress("Loading image", 1, 1)
            stats = repair_image(
                image,
                max_colors,
                reduce_palette,
                scale,
                centroids,
                separate_xy_scale,
                downscale_method,
                palette_method,
                denoise_level,
                progress,
                self.cancel_event,
            )
        except ProcessingCancelled:
            self.worker_queue.put(("cancelled",))
        except Exception as exc:
            self.worker_queue.put(("error", str(exc)))
        else:
            self.worker_queue.put(("done", stats))

    def _poll_worker(self):
        while self.worker_queue is not None:
            try:
                message = self.worker_queue.get_nowait()
            except queue.Empty:
                break

            kind = message[0]
            if kind == "progress":
                _, label, current, total = message
                percent = 0 if total <= 0 else max(0, min(100, current / total * 100))
                self.progress_value.set(percent)
                self.status.set(f"{label}: {percent:.0f}%")
            elif kind == "done":
                self._finish_processing(message[1])
                return
            elif kind == "cancelled":
                self._reset_processing_controls()
                self.progress_value.set(0)
                self.status.set("Processing cancelled.")
                return
            elif kind == "error":
                self._reset_processing_controls()
                self.progress_value.set(0)
                self.status.set("Processing failed.")
                messagebox.showerror("Pixel Detector", message[1])
                return

        if self.processing:
            self.after(50, self._poll_worker)

    def _finish_processing(self, stats):
        self._reset_processing_controls()
        self.progress_value.set(100)
        self.result_image = stats.pop("image")
        self.result_stats = stats.copy()
        self._show_preview(self.result_image, stats)
        self.save_button.configure(state="normal")
        self.status.set(self._format_status(stats))

    def _reset_processing_controls(self):
        self.processing = False
        self.cancel_event = None
        self.worker_queue = None
        self.run_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")

    def _cancel(self):
        if self.cancel_event is not None:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status.set("Cancelling...")

    def _save_as(self):
        if self.result_image is None:
            messagebox.showerror("Pixel Detector", "Run processing before saving.")
            return

        save_format = self._selected_save_format()
        default_path = self._default_output_path(self.input_path.get().strip(), save_format)
        initial_dir = os.path.dirname(default_path) or os.getcwd()
        initial_file = os.path.basename(default_path) or f"output_repaired{FORMAT_EXTENSIONS[save_format]}"
        filetypes = FORMAT_FILETYPES[save_format] + [("All files", "*.*")]
        path = filedialog.asksaveasfilename(
            title="Save repaired image",
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=FORMAT_EXTENSIONS[save_format],
            filetypes=filetypes,
        )
        if not path:
            return

        path = self._ensure_extension(path, save_format)

        try:
            self._save_image(path, save_format)
        except Exception as exc:
            self.status.set("Save failed.")
            messagebox.showerror("Pixel Detector", str(exc))
            return

        self.status.set(f"Saved: {path}")

    def _save_image(self, path, save_format):
        options = {}
        if save_format == "PNG":
            options["optimize"] = True
        elif save_format == "JPEG":
            options.update({"quality": 95, "subsampling": 0, "optimize": True})
        elif save_format == "WEBP":
            options.update({"lossless": True, "quality": 100})

        self.result_image.save(path, format=save_format, **options)

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
        denoise = stats.get("denoise_level", "off")

        return (
            f"Input: {stats['input_width']}x{stats['input_height']}\n"
            f"Output: {stats['output_width']}x{stats['output_height']}\n"
            f"Mode: {mode}\n"
            f"Used scale: {scale_label}\n"
            f"Detected X/Y: {stats['horizontal_scale']:.2f}x / {stats['vertical_scale']:.2f}x\n"
            f"Separate X/Y: {'yes' if stats['separate_xy_scale'] else 'no'}\n"
            f"Method: {stats['downscale_method']}\n"
            f"Denoise: {denoise}\n"
            f"Palette: {palette}\n"
            f"Palette method: {stats['palette_method']}"
        )

    def _format_status(self, stats):
        lines = [
            "Processing finished.",
            f"Size: {stats['input_width']}x{stats['input_height']} -> {stats['output_width']}x{stats['output_height']}",
            f"Resize time: {stats['resize_time_ms']} ms",
        ]

        if stats.get("denoise_level") != "off":
            lines.append(f"Denoise: {stats['denoise_level']}")

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

    def _selected_denoise_level(self):
        value = self.denoise_level.get()
        if value == "Auto":
            ext = os.path.splitext(self.input_path.get().strip())[1].lower()
            return "medium" if ext in (".jpg", ".jpeg") else "off"
        return value.lower()

    def _selected_save_format(self):
        value = self.output_format.get()
        if value != "Same as input":
            return value

        ext = os.path.splitext(self.input_path.get().strip())[1].lower()
        return INPUT_FORMATS.get(ext, "PNG")

    def _toggle_advanced(self):
        if self.advanced_visible.get():
            self.advanced_frame.grid(row=6, column=0, columnspan=2, pady=(8, 0), sticky="ew")
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
            self.denoise_level,
        ):
            variable.trace_add("write", self._mark_result_dirty)

    def _mark_result_dirty(self, *_args):
        if self.processing:
            return

        if self.result_image is None:
            return

        self.result_image = None
        self.result_stats = None
        self.save_button.configure(state="disabled")
        self.status.set("Settings changed. Run again to refresh the result.")

    @staticmethod
    def _ensure_extension(path, save_format):
        ext = FORMAT_EXTENSIONS[save_format]
        if os.path.splitext(path)[1].lower() not in (ext, ".jpeg" if save_format == "JPEG" else ext):
            return f"{os.path.splitext(path)[0]}{ext}"
        return path

    @staticmethod
    def _default_output_path(input_path, save_format):
        if not input_path:
            return f"output_repaired{FORMAT_EXTENSIONS[save_format]}"

        folder, filename = os.path.split(input_path)
        name, _ext = os.path.splitext(filename)
        return os.path.join(folder, f"{name}_repaired{FORMAT_EXTENSIONS[save_format]}")


if __name__ == "__main__":
    app = PixelDetectorApp()
    app.mainloop()
