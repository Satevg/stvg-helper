#!/usr/bin/env python3
"""Dev-only tool: visually define parking zone rectangles per camera.

Usage:
    # Define zone for a specific camera
    uv run scripts/zone_editor.py "Авиационная 8" 1

    # Iterate through all cameras in PARKING_CAMERAS order
    uv run scripts/zone_editor.py

Controls:
    Click and drag  — draw zone rectangle
    Enter           — accept and advance to next camera
    Esc             — skip this camera

Requires tkinter (built into CPython) and Pillow (already a bot dependency).
"""

import os
import sys
import tkinter as tk
from tkinter import ttk
from io import BytesIO
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

from parking import PARKING_CAMERAS, _fetch_jpeg, find_camera, fetch_cameras  # noqa: E402
from parking import Zone  # noqa: E402

# Try importing ImageTk — available when Pillow is built with Tk support.
try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    print("Pillow is required. Run: uv sync")
    sys.exit(1)

MAX_W = 1200
MAX_H = 800
_GRID_COLS = 6
_GRID_ROWS = 4


def _scale_image(img: Image.Image) -> tuple[Image.Image, float]:
    """Scale image to fit within MAX_W×MAX_H, return (scaled_img, scale_factor)."""
    w, h = img.size
    scale = min(MAX_W / w, MAX_H / h, 1.0)
    if scale < 1.0:
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
    return img, scale


def _draw_grid(draw: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Draw faint grid overlay to show cell alignment."""
    cell_w, cell_h = w // _GRID_COLS, h // _GRID_ROWS
    for col in range(1, _GRID_COLS):
        x = col * cell_w
        draw.line([(x, 0), (x, h)], fill=(200, 200, 200, 80), width=1)
    for row in range(1, _GRID_ROWS):
        y = row * cell_h
        draw.line([(0, y), (w, y)], fill=(200, 200, 200, 80), width=1)


def _edit_zone(
    jpeg: bytes,
    building: str,
    cam_num: int,
) -> Optional[Zone]:
    """Open a tkinter window and let the user drag a zone rectangle.

    Returns the normalised Zone tuple, or None if the user skipped.
    """
    img_orig = Image.open(BytesIO(jpeg)).convert("RGB")
    orig_w, orig_h = img_orig.size
    img_scaled, scale = _scale_image(img_orig)
    disp_w, disp_h = img_scaled.size

    result: list[Optional[Zone]] = [None]
    drag_start: list[Optional[tuple[int, int]]] = [None]
    drag_rect: list[Optional[tuple[int, int, int, int]]] = [None]

    root = tk.Tk()
    root.title(f"Zone editor — {building} — Камера {cam_num:02d} | drag to select zone, Enter=accept, Esc=skip")
    root.resizable(False, False)

    canvas = tk.Canvas(root, width=disp_w, height=disp_h, cursor="crosshair")
    canvas.pack()

    status_var = tk.StringVar(value="Drag to select parking zone. Enter=accept, Esc=skip.")
    status_label = ttk.Label(root, textvariable=status_var, anchor="w", padding=(4, 2))
    status_label.pack(fill=tk.X)

    def _render(rect: Optional[tuple[int, int, int, int]] = None) -> None:
        base = img_scaled.copy().convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        _draw_grid(draw, disp_w, disp_h)
        if rect:
            x1, y1, x2, y2 = rect
            draw.rectangle([x1, y1, x2 - 1, y2 - 1], outline=(255, 60, 60, 255), width=2)
            draw.rectangle([x1, y1, x2 - 1, y2 - 1], fill=(255, 60, 60, 40))
        composite = Image.alpha_composite(base, overlay).convert("RGB")
        photo = ImageTk.PhotoImage(composite)
        canvas.image = photo  # type: ignore[attr-defined]  # keep reference
        canvas.create_image(0, 0, anchor=tk.NW, image=photo)

    _render()

    def on_press(event: tk.Event) -> None:  # type: ignore[type-arg]
        drag_start[0] = (event.x, event.y)
        drag_rect[0] = None

    def on_drag(event: tk.Event) -> None:  # type: ignore[type-arg]
        if drag_start[0] is None:
            return
        x0, y0 = drag_start[0]
        x1, y1 = (
            max(0, min(event.x, disp_w)),
            max(0, min(event.y, disp_h)),
        )
        rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        drag_rect[0] = rect
        _render(rect)
        x1n = rect[0] / disp_w
        y1n = rect[1] / disp_h
        x2n = rect[2] / disp_w
        y2n = rect[3] / disp_h
        status_var.set(f"Zone: ({x1n:.3f}, {y1n:.3f}, {x2n:.3f}, {y2n:.3f}) — press Enter to accept")

    def on_release(event: tk.Event) -> None:  # type: ignore[type-arg]
        on_drag(event)

    def on_accept(event: Optional[tk.Event] = None) -> None:  # type: ignore[type-arg]
        rect = drag_rect[0]
        if rect is None:
            status_var.set("No zone drawn — drag a rectangle first.")
            return
        x1, y1, x2, y2 = rect
        if x2 <= x1 or y2 <= y1:
            status_var.set("Zone too small — drag a larger rectangle.")
            return
        zone: Zone = (
            round(x1 / disp_w, 4),
            round(y1 / disp_h, 4),
            round(x2 / disp_w, 4),
            round(y2 / disp_h, 4),
        )
        result[0] = zone
        root.destroy()

    def on_skip(event: Optional[tk.Event] = None) -> None:  # type: ignore[type-arg]
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Return>", on_accept)
    root.bind("<Escape>", on_skip)

    accept_btn = ttk.Button(root, text="Accept (Enter)", command=on_accept)
    skip_btn = ttk.Button(root, text="Skip (Esc)", command=on_skip)
    btn_frame = ttk.Frame(root)
    btn_frame.pack(pady=4)
    accept_btn.pack(in_=btn_frame, side=tk.LEFT, padx=8)
    skip_btn.pack(in_=btn_frame, side=tk.LEFT, padx=8)

    root.mainloop()

    # Scale zone back to original image coordinates to produce normalised values.
    # (We already divided by disp_w/disp_h above, which equals dividing by orig*scale/scale.)
    return result[0]


def _process_camera(cameras: list, building: str, cam_num: int) -> Optional[Zone]:
    cam = find_camera(cameras, building, cam_num)
    if cam is None:
        print(f"  Camera not found: {building} — Камера {cam_num:02d}")
        return None

    print(f"  Fetching snapshot for {building} — Камера {cam_num:02d}...")
    jpeg = _fetch_jpeg(cam)
    if jpeg is None:
        print("  No snapshot available, skipping.")
        return None

    zone = _edit_zone(jpeg, building, cam_num)
    if zone is None:
        print("  Skipped.")
        return None

    x1, y1, x2, y2 = zone
    line = f'    ("{building}", {cam_num}): [({x1}, {y1}, {x2}, {y2})],'
    print(f"\n  Paste into PARKING_ZONES:\n{line}\n")
    return zone


def main() -> None:
    args = sys.argv[1:]

    print("Fetching camera list from Watcher...")
    cameras = fetch_cameras()
    print(f"Found {len(cameras)} cameras.\n")

    if len(args) == 2:
        building = args[0]
        cam_num = int(args[1])
        _process_camera(cameras, building, cam_num)
    else:
        if args:
            print(f"Usage: {sys.argv[0]} [\"Building Name\" camera_number]")
            sys.exit(1)

        print("Iterating through all cameras in PARKING_CAMERAS order.")
        print("Press Enter to accept zone, Esc to skip.\n")
        for building, cam_nums in PARKING_CAMERAS:
            for cam_num in cam_nums:
                print(f"--- {building} — Камера {cam_num:02d} ---")
                _process_camera(cameras, building, cam_num)


if __name__ == "__main__":
    main()
