import os, argparse, time
from PIL import Image
import numpy as np
import scipy.ndimage
import scipy.signal
from itertools import product


DOWNSCALE_METHODS = ("fast", "quality")
PALETTE_METHODS = ("fixed", "auto")
DENOISE_LEVELS = ("off", "light", "medium", "strong")


class ProcessingCancelled(Exception):
    pass


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise ProcessingCancelled("Processing cancelled")


def _report_progress(progress_callback, message: str, current: int, total: int):
    if progress_callback is not None:
        progress_callback(message, current, total)


def kCentroid(image: Image, width: int, height: int, centroids: int, progress_callback=None, cancel_event=None):
    image = image.convert("RGB")

    downscaled = np.zeros((height, width, 3), dtype=np.uint8)

    wFactor = image.width / width
    hFactor = image.height / height
    total = width * height
    processed = 0

    for x, y in product(range(width), range(height)):
        _check_cancel(cancel_event)
        tile = image.crop((x * wFactor, y * hFactor, (x * wFactor) + wFactor, (y * hFactor) + hFactor))
        tile = tile.quantize(colors=centroids, method=1, kmeans=centroids).convert("RGB")

        color_counts = tile.getcolors()
        most_common_color = max(color_counts, key=lambda x: x[0])[1]
        downscaled[y, x, :] = most_common_color

        processed += 1
        if processed == total or processed % 100 == 0:
            _report_progress(progress_callback, "Recovering pixels", processed, total)

    return Image.fromarray(downscaled, mode="RGB")


def fast_downscale(image: Image, width: int, height: int, progress_callback=None, cancel_event=None):
    _check_cancel(cancel_event)
    image = image.convert("RGB")
    width = max(1, width)
    height = max(1, height)

    if image.width % width == 0 and image.height % height == 0:
        block_width = image.width // width
        block_height = image.height // height
        pixels = np.array(image, dtype=np.uint8)
        blocks = pixels.reshape(height, block_height, width, block_width, 3)
        downscaled = np.median(blocks, axis=(1, 3)).astype(np.uint8)
        _report_progress(progress_callback, "Recovering pixels", 1, 1)
        return Image.fromarray(downscaled, mode="RGB")

    output = image.resize((width, height), Image.Resampling.BOX)
    _report_progress(progress_callback, "Recovering pixels", 1, 1)
    return output


def downscale_image(image: Image, width: int, height: int, centroids: int, method: str, progress_callback=None, cancel_event=None):
    if method not in DOWNSCALE_METHODS:
        raise ValueError(f"Downscale method must be one of: {', '.join(DOWNSCALE_METHODS)}")

    if method == "quality":
        return kCentroid(image, width, height, centroids, progress_callback, cancel_event)

    return fast_downscale(image, width, height, progress_callback, cancel_event)


def pixel_detect(image: Image, centroids: int = 2, separate_xy_scale: bool = False, downscale_method: str = "quality", progress_callback=None, cancel_event=None):
    # Thanks to https://github.com/paultron for optimizing my garbage code
    # I swapped the axis so they accurately reflect the horizontal and vertical scaling factor for images with uneven ratios

    _check_cancel(cancel_event)
    _report_progress(progress_callback, "Detecting pixel scale", 0, 1)
    npim = np.array(image)[..., :3].astype(np.int16)

    hdiff = np.sqrt(np.sum((npim[:, :-1, :] - npim[:, 1:, :]) ** 2, axis=2))
    hsum = np.sum(hdiff, 0)

    vdiff = np.sqrt(np.sum((npim[:-1, :, :] - npim[1:, :, :]) ** 2, axis=2))
    vsum = np.sum(vdiff, 1)

    _check_cancel(cancel_event)
    hpeaks, _ = scipy.signal.find_peaks(hsum, distance=1, height=0.0)
    vpeaks, _ = scipy.signal.find_peaks(vsum, distance=1, height=0.0)

    hspacing = np.diff(hpeaks)
    vspacing = np.diff(vpeaks)

    hf = float(np.median(hspacing))
    vf = float(np.median(vspacing))

    if not np.isfinite(hf) or not np.isfinite(vf) or hf <= 0 or vf <= 0:
        raise ValueError("Could not detect pixel scale from this image")

    if separate_xy_scale:
        output_width = max(1, round(image.width / hf))
        output_height = max(1, round(image.height / vf))
        used_scale = max(hf, vf)
    else:
        used_scale = round((hf + vf) / 2)
        used_scale = max(1, used_scale)
        output_width = max(1, round(image.width / used_scale))
        output_height = max(1, round(image.height / used_scale))

    _report_progress(progress_callback, "Detecting pixel scale", 1, 1)
    return downscale_image(image, output_width, output_height, centroids, downscale_method, progress_callback, cancel_event), hf, vf, used_scale


def denoise_image(image: Image, level: str):
    if level not in DENOISE_LEVELS:
        raise ValueError(f"Denoise level must be one of: {', '.join(DENOISE_LEVELS)}")

    if level == "off":
        return image.convert("RGB")

    kernel_size = 3 if level in ("light", "medium") else 5
    pixels = np.array(image.convert("RGB"), dtype=np.uint8)
    denoised = scipy.ndimage.median_filter(pixels, size=(kernel_size, kernel_size, 1))

    if level == "light":
        denoised = ((pixels.astype(np.uint16) + denoised.astype(np.uint16)) // 2).astype(np.uint8)

    return Image.fromarray(denoised, mode="RGB")


def determine_best_k(image: Image, max_k: int, progress_callback=None, cancel_event=None):
    if max_k <= 1:
        return 1

    image = image.convert("RGB")

    pixels = np.array(image)
    pixel_indices = np.reshape(pixels, (-1, 3))

    distortions = []
    for k in range(1, max_k + 1):
        _check_cancel(cancel_event)
        quantized_image = image.quantize(colors=k, method=0, kmeans=k, dither=0)
        centroids = np.array(quantized_image.getpalette()[:k * 3]).reshape(-1, 3)

        distances = np.linalg.norm(pixel_indices[:, np.newaxis] - centroids, axis=2)
        min_distances = np.min(distances, axis=1)
        distortions.append(np.sum(min_distances ** 2))
        _report_progress(progress_callback, "Detecting palette", k, max_k)

    previous_distortions = np.array(distortions[:-1])
    rate_of_change = np.divide(
        np.diff(distortions),
        previous_distortions,
        out=np.zeros_like(previous_distortions, dtype=float),
        where=previous_distortions != 0,
    )

    if len(rate_of_change) == 0:
        best_k = 2
    else:
        elbow_index = np.argmax(rate_of_change) + 1
        best_k = elbow_index + 2

    return min(best_k, max_k)


def repair_image(
    image: Image,
    max_colors: int = 128,
    reduce_palette: bool = False,
    scale: int | None = None,
    centroids: int = 2,
    separate_xy_scale: bool = False,
    downscale_method: str = "quality",
    palette_method: str = "auto",
    denoise_level: str = "off",
    progress_callback=None,
    cancel_event=None,
):
    if max_colors < 1:
        raise ValueError("Max colors must be 1 or greater")

    if centroids < 1:
        raise ValueError("Centroids must be 1 or greater")

    if scale is not None and scale < 1:
        raise ValueError("Scale must be 1 or greater")

    if downscale_method not in DOWNSCALE_METHODS:
        raise ValueError(f"Downscale method must be one of: {', '.join(DOWNSCALE_METHODS)}")

    if palette_method not in PALETTE_METHODS:
        raise ValueError(f"Palette method must be one of: {', '.join(PALETTE_METHODS)}")

    if denoise_level not in DENOISE_LEVELS:
        raise ValueError(f"Denoise level must be one of: {', '.join(DENOISE_LEVELS)}")

    image = image.convert("RGB")

    _check_cancel(cancel_event)
    if denoise_level != "off":
        _report_progress(progress_callback, "Denoising JPEG artifacts", 0, 1)
        image = denoise_image(image, denoise_level)
        _report_progress(progress_callback, "Denoising JPEG artifacts", 1, 1)

    start = round(time.time() * 1000)

    if scale is None:
        downscale, hf, vf, used_scale = pixel_detect(image, centroids, separate_xy_scale, downscale_method, progress_callback, cancel_event)
    else:
        hf = scale
        vf = scale
        used_scale = scale
        downscale = downscale_image(
            image,
            max(1, round(image.width / scale)),
            max(1, round(image.height / scale)),
            centroids,
            downscale_method,
            progress_callback,
            cancel_event,
        )

    resize_time = round(time.time() * 1000) - start

    output = downscale
    best_k = None
    palette_time = None

    if reduce_palette:
        start = round(time.time() * 1000)

        if palette_method == "auto":
            best_k = determine_best_k(downscale, max_colors, progress_callback, cancel_event)
            _check_cancel(cancel_event)
            _report_progress(progress_callback, "Applying palette", 0, 1)
            output = downscale.quantize(colors=best_k, method=1, kmeans=best_k, dither=0).convert("RGB")
        else:
            best_k = max_colors
            _check_cancel(cancel_event)
            _report_progress(progress_callback, "Applying palette", 0, 1)
            output = downscale.quantize(colors=max_colors, method=1, kmeans=0, dither=0).convert("RGB")

        _report_progress(progress_callback, "Applying palette", 1, 1)
        palette_time = round(time.time() * 1000) - start

    return {
        "image": output,
        "input_width": image.width,
        "input_height": image.height,
        "output_width": output.width,
        "output_height": output.height,
        "resize_time_ms": resize_time,
        "palette_time_ms": palette_time,
        "palette_colors": best_k,
        "scale": used_scale,
        "horizontal_scale": hf,
        "vertical_scale": vf,
        "manual_scale": scale,
        "separate_xy_scale": separate_xy_scale,
        "downscale_method": downscale_method,
        "palette_method": palette_method,
        "denoise_level": denoise_level,
    }


def process_image(
    input_path: str,
    output_path: str,
    max_colors: int = 128,
    reduce_palette: bool = False,
    scale: int | None = None,
    centroids: int = 2,
    separate_xy_scale: bool = False,
    downscale_method: str = "quality",
    palette_method: str = "auto",
    denoise_level: str = "off",
):
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input image not found: {input_path}")

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    image = Image.open(input_path).convert("RGB")
    stats = repair_image(image, max_colors, reduce_palette, scale, centroids, separate_xy_scale, downscale_method, palette_method, denoise_level)
    output = stats.pop("image")
    output.save(output_path)
    stats.update({
        "output_path": output_path,
    })
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", required=True, help="Path to input image")
    ap.add_argument("-o", "--output", required=False, default="output.png", help="Path to save output image")
    ap.add_argument("-m", "--max", required=False, type=int, default=128, help="Max colors for computation, more = slower")
    ap.add_argument("-p", "--palette", required=False, action="store_true", help="Automatically reduce the image to predicted color palette")
    ap.add_argument("--method", choices=DOWNSCALE_METHODS, default="quality", help="Downscale method")
    ap.add_argument("--palette-method", choices=PALETTE_METHODS, default="auto", help="Palette reduction method")
    ap.add_argument("--denoise", choices=DENOISE_LEVELS, default="off", help="JPEG artifact denoise strength")
    args = vars(ap.parse_args())

    stats = process_image(
        args["input"],
        args["output"],
        args["max"],
        args["palette"],
        downscale_method=args["method"],
        palette_method=args["palette_method"],
        denoise_level=args["denoise"],
    )

    print(
        f"Size detected and reduced from {stats['input_width']}x{stats['input_height']} "
        f"to {stats['output_width']}x{stats['output_height']} in {stats['resize_time_ms']} milliseconds"
    )

    if args["palette"]:
        print(f"Palette reduced to {stats['palette_colors']} colors in {stats['palette_time_ms']} milliseconds")

    print(f"Saved output to {stats['output_path']}")


if __name__ == "__main__":
    main()
