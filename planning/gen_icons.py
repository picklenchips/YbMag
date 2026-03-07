"""Generate crop and reset ROI icon PNGs for light and dark themes."""

import struct, zlib, os, math
from pathlib import Path


def make_chunk(chunk_type, data):
    c = chunk_type + data
    return (
        struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    )


def make_png(pixels, size):
    raw = b"".join(pixels)
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        header
        + make_chunk(b"IHDR", ihdr)
        + make_chunk(b"IDAT", zlib.compress(raw))
        + make_chunk(b"IEND", b"")
    )


def save_png(filepath: Path, png):
    os.makedirs(filepath.parent, exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(png)
    print(f"Saved icon: {filepath}")


def create_digilent_icon(filepath, fg_color, bg_color=(0, 0, 0, 0), size=24, width=1):
    """digilent icon: sine overlayed on square wave"""
    pixels = []
    top = (size - 1) * 7 // 8
    bot = size * 1 // 8
    mid = size // 2
    sine = lambda x: size * math.sin(2 * math.pi * x / size) / 2 + mid
    square = lambda x: bot if x <= size // 2 else top
    for y in range(size):
        row = []
        for x in range(size):
            s = sine(x)
            q = square(x)
            if (
                abs(y - s) <= width
                or y == q
                or (x == size // 2 and y >= bot and y <= top)
            ):
                row.extend(fg_color)
            else:
                row.extend(bg_color)
        pixels.append(bytes([0] + row))

    save_png(filepath, make_png(pixels, size))


def create_power_icon_png(filepath, fg_color, bg_color=(0, 0, 0, 0), size=24):
    pixels = []
    cx, cy = size // 2, size // 2
    r_outer = size // 2 - 2
    r_inner = r_outer - 2
    for y in range(size):
        row = []
        for x in range(size):
            dx, dy = x - cx, y - cy
            dist = (dx * dx + dy * dy) ** 0.5
            in_circle = r_inner <= dist <= r_outer
            in_gap = abs(dx) <= 1.5 and dy < 0
            in_line = abs(dx) <= 1.2 and -r_outer <= dy <= 2
            if in_line or (in_circle and not in_gap):
                row.extend(fg_color)
            else:
                row.extend(bg_color)
        pixels.append(bytes([0] + row))

    save_png(filepath, make_png(pixels, size))


def create_crop_icon_png(filepath, fg_color, bg_color=(0, 0, 0, 0), size=24, width=2):
    """Create a crop icon with two intersecting L-shapes forming + at corners."""
    pixels = []
    border_width = width - 1
    bracket_len = 3 * size // 4 + border_width  # Length of each L arm
    c0 = (bracket_len, bracket_len)
    c1 = (size - bracket_len - 1, size - bracket_len - 1)

    for y in range(size):
        row = []
        for x in range(size):
            is_fg = False

            # left horizontal line
            if x <= c0[0] and c0[1] - border_width <= y <= c0[1]:
                is_fg = True
            # bottom-right vertical line
            if c0[0] - border_width <= x <= c0[0] and y <= c0[1]:
                is_fg = True
            # bottom-right horizontal line
            if c1[0] <= x and c1[1] <= y <= c1[1] + border_width:
                is_fg = True
            # top-left vertical line
            if c1[0] <= x <= c1[0] + border_width and c1[1] <= y:
                is_fg = True

            if is_fg:
                row.extend(fg_color)
            else:
                row.extend(bg_color)
        pixels.append(bytes([0] + row))

    save_png(filepath, make_png(pixels, size))


def create_fullsize_icon_png(
    filepath, fg_color, bg_color=(0, 0, 0, 0), size=24, width=2
):
    """Create a full-size/reset icon with arrows from center to corners with bracket-style arrowheads."""
    pixels = []
    cx, cy = size // 2, size // 2
    line_width = width
    bracket_size = 10  # Size of L-shaped arrowhead
    cdx = (4, 4)

    for y in range(size):
        row = []
        for x in range(size):
            is_fg = False
            dx, dy = x - cx, y - cy

            # Top-left: diagonal line + L-bracket arrowhead at corner
            if dx < -cdx[0] and dy < -cdx[1]:
                # Diagonal line from center
                if abs(dx - dy) <= line_width // 2:
                    is_fg = True
                # L-bracket arrowhead at top-left corner
                if (x <= bracket_size and y < line_width) or (
                    x < line_width and y <= bracket_size
                ):
                    is_fg = True

            # Top-right: diagonal line + L-bracket arrowhead at corner
            elif dx > cdx[0] and dy < -cdx[1]:
                # Diagonal line from center
                if abs(dx + dy) <= line_width // 2:
                    is_fg = True
                # L-bracket arrowhead at top-right corner
                if (x >= size - bracket_size - 1 and y < line_width) or (
                    x > size - line_width - 1 and y <= bracket_size
                ):
                    is_fg = True

            # Bottom-left: diagonal line + L-bracket arrowhead at corner
            elif dx < -cdx[0] and dy > cdx[1]:
                # Diagonal line from center
                if abs(dx + dy) <= line_width // 2:
                    is_fg = True
                # L-bracket arrowhead at bottom-left corner
                if (x <= bracket_size and y > size - line_width - 1) or (
                    x < line_width and y >= size - bracket_size - 1
                ):
                    is_fg = True

            # Bottom-right: diagonal line + L-bracket arrowhead at corner
            elif dx > cdx[0] and dy > cdx[1]:
                # Diagonal line from center
                if abs(dx - dy) <= line_width // 2:
                    is_fg = True
                # L-bracket arrowhead at bottom-right corner
                if (x >= size - bracket_size - 1 and y > size - line_width - 1) or (
                    x > size - line_width - 1 and y >= size - bracket_size - 1
                ):
                    is_fg = True
            if is_fg:
                row.extend(fg_color)
            else:
                row.extend(bg_color)
        pixels.append(bytes([0] + row))

    save_png(filepath, make_png(pixels, size))


parent = Path(__file__).parent  # old
home = parent.parent
image_dir = home / "app" / "resources" / "images"
for theme, color in zip(
    ["+theme_light", "+theme_dark"], [(50, 50, 60, 255), (220, 220, 230, 255)]
):
    path = image_dir / theme / "digilent.png"
    create_digilent_icon(path, color)


print("ROI icons created successfully:")
print("  - crop.png (light and dark)")
print("  - fullsize.png (light and dark)")
print("  - digilent.png (light and dark)")
