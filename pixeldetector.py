import os, argparse, time
from PIL import Image
import numpy as np
import scipy
import scipy.signal
from itertools import product


DOWNSCALE_METHODS = ("fast", "quality")
PALETTE_METHODS = ("fixed", "auto")

def kCentroid(image: Image, width: int, height: int, centroids: int):
    image = image.convert("RGB")

    # Create an empty array for the downscaled image
    downscaled = np.zeros((height, width, 3), dtype=np.uint8)

    # Calculate the scaling factors
    wFactor = image.width/width
    hFactor = image.height/height

    # Iterate over each tile in the downscaled image
    for x, y in product(range(width), range(height)):
            # Crop the tile from the original image
            tile = image.crop((x*wFactor, y*hFactor, (x*wFactor)+wFactor, (y*hFactor)+hFactor))

            # Quantize the colors of the tile using k-means clustering
            tile = tile.quantize(colors=centroids, method=1, kmeans=centroids).convert("RGB")

            # Get the color counts and find the most common color
            color_counts = tile.getcolors()
            most_common_color = max(color_counts, key=lambda x: x[0])[1]

            # Assign the most common color to the corresponding pixel in the downscaled image
            downscaled[y, x, :] = most_common_color

    return Image.fromarray(downscaled, mode='RGB')


def fast_downscale(image: Image, width: int, height: int):
    image = image.convert("RGB")
    width = max(1, width)
    height = max(1, height)

    if image.width % width == 0 and image.height % height == 0:
        block_width = image.width // width
        block_height = image.height // height
        pixels = np.array(image, dtype=np.uint8)
        blocks = pixels.reshape(height, block_height, width, block_width, 3)
        downscaled = np.median(blocks, axis=(1, 3)).astype(np.uint8)
        return Image.fromarray(downscaled, mode="RGB")

    return image.resize((width, height), Image.Resampling.BOX)


def downscale_image(image: Image, width: int, height: int, centroids: int, method: str):
    if method not in DOWNSCALE_METHODS:
        raise ValueError(f"Downscale method must be one of: {', '.join(DOWNSCALE_METHODS)}")

    if method == "quality":
        return kCentroid(image, width, height, centroids)

    return fast_downscale(image, width, height)


def pixel_detect(image: Image, centroids: int = 2, separate_xy_scale: bool = False, downscale_method: str = "quality"):
    # Thanks to https://github.com/paultron for optimizing my garbage code 
    # I swapped the axis so they accurately reflect the horizontal and vertical scaling factor for images with uneven ratios

    # Convert the image to a NumPy array
    npim = np.array(image)[..., :3].astype(np.int16)

    # Compute horizontal differences between pixels
    hdiff = np.sqrt(np.sum((npim[:, :-1, :] - npim[:, 1:, :])**2, axis=2))
    hsum = np.sum(hdiff, 0)

    # Compute vertical differences between pixels
    vdiff = np.sqrt(np.sum((npim[:-1, :, :] - npim[1:, :, :])**2, axis=2))
    vsum = np.sum(vdiff, 1)

    # Find peaks in the horizontal and vertical sums
    hpeaks, _ = scipy.signal.find_peaks(hsum, distance=1, height=0.0)
    vpeaks, _ = scipy.signal.find_peaks(vsum, distance=1, height=0.0)
    
    # Compute spacing between the peaks
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

    # Resize input image using kCentroid with the calculated scale.
    return downscale_image(image, output_width, output_height, centroids, downscale_method), hf, vf, used_scale

def determine_best_k(image: Image, max_k: int):
    # Convert the image to RGB mode
    image = image.convert("RGB")

    # Prepare arrays for distortion calculation
    pixels = np.array(image)
    pixel_indices = np.reshape(pixels, (-1, 3))

    # Calculate distortion for different values of k
    distortions = []
    for k in range(1, max_k + 1):
        quantized_image = image.quantize(colors=k, method=0, kmeans=k, dither=0)
        centroids = np.array(quantized_image.getpalette()[:k * 3]).reshape(-1, 3)
        
        # Calculate distortions
        distances = np.linalg.norm(pixel_indices[:, np.newaxis] - centroids, axis=2)
        min_distances = np.min(distances, axis=1)
        distortions.append(np.sum(min_distances ** 2))

    # Calculate the rate of change of distortions
    previous_distortions = np.array(distortions[:-1])
    rate_of_change = np.divide(
        np.diff(distortions),
        previous_distortions,
        out=np.zeros_like(previous_distortions, dtype=float),
        where=previous_distortions != 0,
    )
    
    # Find the elbow point (best k value)
    if len(rate_of_change) == 0:
        best_k = 2
    else:
        elbow_index = np.argmax(rate_of_change) + 1
        best_k = elbow_index + 2

    return best_k

def repair_image(
    image: Image,
    max_colors: int = 128,
    reduce_palette: bool = False,
    scale: int | None = None,
    centroids: int = 2,
    separate_xy_scale: bool = False,
    downscale_method: str = "quality",
    palette_method: str = "auto",
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

    image = image.convert('RGB')

    # Start timer
    start = round(time.time()*1000)

    if scale is None:
        # Find 1:1 pixel scale
        downscale, hf, vf, used_scale = pixel_detect(image, centroids, separate_xy_scale, downscale_method)
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
        )

    resize_time = round(time.time()*1000)-start

    output = downscale
    best_k = None
    palette_time = None

    if reduce_palette:
        # Start timer
        start = round(time.time()*1000)

        if palette_method == "auto":
            # Reduce color palette using elbow method.
            best_k = determine_best_k(downscale, max_colors)
            output = downscale.quantize(colors=best_k, method=1, kmeans=best_k, dither=0).convert('RGB')
        else:
            best_k = max_colors
            output = downscale.quantize(colors=max_colors, method=1, kmeans=0, dither=0).convert('RGB')

        palette_time = round(time.time()*1000)-start
    
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
):
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input image not found: {input_path}")

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    image = Image.open(input_path).convert('RGB')
    stats = repair_image(image, max_colors, reduce_palette, scale, centroids, separate_xy_scale, downscale_method, palette_method)
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
    args = vars(ap.parse_args())

    stats = process_image(
        args["input"],
        args["output"],
        args["max"],
        args["palette"],
        downscale_method=args["method"],
        palette_method=args["palette_method"],
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
