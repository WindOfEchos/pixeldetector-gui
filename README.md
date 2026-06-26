# Pixel Detector GUI

Windows GUI fork of [Astropulse/pixeldetector](https://github.com/Astropulse/pixeldetector) by WindOfEchos.

Pixel Detector repairs pixel art that was enlarged, blurred, or damaged by compression. It detects the enlarged pixel grid, downsizes the image back to a cleaner pixel-art resolution, and can optionally reduce the color palette.

![Example](https://github.com/Astropulse/pixeldetector/assets/61034487/f8ae2802-42c1-4dba-af56-fe849ac8915c)

## Download

Download `PixelDetector.exe` from the GitHub Releases page and run it. No Python installation is required for the packaged Windows build.

## Run From Source

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python pixeldetector_gui.py
```

## GUI Usage

Choose an image with `Browse...`, press `Run`, check the preview, then use `Save as...` to save the repaired image.

Main options:

- `Reduce palette`: reduce colors after resizing.
- `Max colors`: palette limit, for example `16`, `32`, or `128`.
- `Scale`: use `Auto` or set the original enlargement manually, for example `4x`.
- `Downscale method`: `Fast median` for speed, `Quality k-means` for slower detailed cleanup.

## Command Line

```powershell
python pixeldetector.py -i input.png -o output.png
```

Palette example:

```powershell
python pixeldetector.py -i input.jpg -o output.png -p -m 32 --method fast --palette-method fixed
```

## Build Windows EXE

```powershell
python -m pip install -r requirements-build.txt
.\build-windows.ps1
```

The executable is created at `dist\PixelDetector.exe`. Upload it as a GitHub Release artifact instead of committing it to git.

## Credits

- Original project: [Astropulse/pixeldetector](https://github.com/Astropulse/pixeldetector).
- GUI fork: WindOfEchos.
- Thanks to [paultron](https://github.com/paultron) for optimizing the downscale calculation in the original project.
- Test image by Skeddles: https://lospec.com/gallery/skeddles/rock-and-grass

## License

MIT License. See `LICENSE` for details.
