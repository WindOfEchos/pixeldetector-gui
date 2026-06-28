# Changelog

All notable changes to this project will be documented in this file.

This project follows [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-06-28

### Added

- Add processing progress bar with cancellable runs.
- Add output format selection: PNG, same as input, JPEG, WEBP, and BMP.
- Add JPEG artifact denoise levels: Auto, Off, Light, Medium, and Strong.
- Add `--denoise` command-line option.

### Changed

- Run GUI image processing in a background thread to keep the interface responsive.
- Save restored images as PNG by default to avoid reintroducing lossy JPEG artifacts.

## [1.0.0] - 2026-06-26

### Added

- Add Windows GUI for pixel-art image recovery.
- Add automatic pixel scale detection and manual scale selection.
- Add fast median and quality k-means downscale methods.
- Add optional palette reduction with fixed and auto-detected palette sizes.
