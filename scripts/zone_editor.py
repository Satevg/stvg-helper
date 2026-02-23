#!/usr/bin/env python3
"""Dev-only tool: visually define parking zone rectangles per camera.

Usage:
    # Define zone for a specific camera
    uv run scripts/zone_editor.py "Авиационная 8" 1

    # Iterate through all cameras in PARKING_CAMERAS order
    uv run scripts/zone_editor.py

Controls:
    Click and drag  — draw a zone rectangle (auto-added on release)
    Backspace       — undo last rectangle
    Enter           — accept all rectangles and advance to next camera
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
) -> Optional[list[Zone]]:
    """Open a tkinter window and let the user drag zone rectangles.

    Returns a list of normalised Zone tuples, or None if the user skipped.
    """
    img_orig = Image.open(BytesIO(jpeg)).convert("RGB")
    img_scaled, scale = _scale_image(img_orig)
    disp_w, disp_h = img_scaled.size

    result: list[Optional[list[Zone]]] = [None]
    drag_start: list[Optional[tuple[int, int]]] = [None]
    current_drag: list[Optional[tuple[int, int, int, int]]] = [None]
    committed_rects: list[tuple[int, int, int, int]] = []

    root = tk.Tk()
    root.title(f"Zone editor — {building} — Камера {cam_num:02d} | drag to add zones, Enter=accept, Esc=skip")
    root.resizable(False, False)

    canvas = tk.Canvas(root, width=disp_w, height=disp_h, cursor="crosshair")
    canvas.pack()

    status_var = tk.StringVar(value="Drag to add parking zones. Backspace=undo, Enter=accept, Esc=skip.")
    status_label = ttk.Label(root, textvariable=status_var, anchor="w", padding=(4, 2))
    status_label.pack(fill=tk.X)

    def _render() -> None:
        base = img_scaled.copy().convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        _draw_grid(draw, disp_w, disp_h)
        for rect in committed_rects:
            x1, y1, x2, y2 = rect
            draw.rectangle([x1, y1, x2, y2], outline=(60, 200, 60, 255), width=2)
            draw.rectangle([x1, y1, x2, y2], fill=(60, 200, 60, 40))
        if current_drag[0]:
            x1, y1, x2, y2 = current_drag[0]
            draw.rectangle([x1, y1, x2, y2], outline=(255, 60, 60, 255), width=2)
            draw.rectangle([x1, y1, x2, y2], fill=(255, 60, 60, 40))
        composite = Image.alpha_composite(base, overlay).convert("RGB")
        photo = ImageTk.PhotoImage(composite)
        canvas.image = photo  # type: ignore[attr-defined]  # keep reference
        canvas.create_image(0, 0, anchor=tk.NW, image=photo)

    _render()

    def _update_status() -> None:
        n = len(committed_rects)
        if n == 0:
            status_var.set("Drag to add parking zones. Backspace=undo, Enter=accept, Esc=skip.")
        else:
            status_var.set(f"{n} zone(s) defined. Drag to add more, Backspace=undo, Enter=accept, Esc=skip.")

    def on_press(event: tk.Event) -> None:  # type: ignore[type-arg]
        drag_start[0] = (event.x, event.y)
        current_drag[0] = None

    def on_drag(event: tk.Event) -> None:  # type: ignore[type-arg]
        if drag_start[0] is None:
            return
        x0, y0 = drag_start[0]
        x1 = max(0, min(event.x, disp_w))
        y1 = max(0, min(event.y, disp_h))
        rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        current_drag[0] = rect
        _render()
        x1n = rect[0] / disp_w
        y1n = rect[1] / disp_h
        x2n = rect[2] / disp_w
        y2n = rect[3] / disp_h
        status_var.set(f"Drawing: ({x1n:.3f}, {y1n:.3f}, {x2n:.3f}, {y2n:.3f}) — release to add")

    def on_release(event: tk.Event) -> None:  # type: ignore[type-arg]
        if drag_start[0] is None:
            return
        x0, y0 = drag_start[0]
        x1 = max(0, min(event.x, disp_w))
        y1 = max(0, min(event.y, disp_h))
        rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        drag_start[0] = None
        current_drag[0] = None
        rx1, ry1, rx2, ry2 = rect
        if rx2 > rx1 and ry2 > ry1:
            committed_rects.append(rect)
        _render()
        _update_status()

    def on_accept(event: Optional[tk.Event] = None) -> None:  # type: ignore[type-arg]
        if not committed_rects:
            status_var.set("No zones defined — drag at least one rectangle first.")
            return
        zones: list[Zone] = [
            (
                round(r[0] / disp_w, 4),
                round(r[1] / disp_h, 4),
                round(r[2] / disp_w, 4),
                round(r[3] / disp_h, 4),
            )
            for r in committed_rects
        ]
        result[0] = zones
        root.destroy()

    def on_undo(event: Optional[tk.Event] = None) -> None:  # type: ignore[type-arg]
        if committed_rects:
            committed_rects.pop()
            _render()
            _update_status()

    def on_skip(event: Optional[tk.Event] = None) -> None:  # type: ignore[type-arg]
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Return>", on_accept)
    root.bind("<Escape>", on_skip)
    root.bind("<BackSpace>", on_undo)

    accept_btn = ttk.Button(root, text="Accept (Enter)", command=on_accept)
    undo_btn = ttk.Button(root, text="Undo (Backspace)", command=on_undo)
    skip_btn = ttk.Button(root, text="Skip (Esc)", command=on_skip)
    btn_frame = ttk.Frame(root)
    btn_frame.pack(pady=4)
    accept_btn.pack(in_=btn_frame, side=tk.LEFT, padx=8)
    undo_btn.pack(in_=btn_frame, side=tk.LEFT, padx=8)
    skip_btn.pack(in_=btn_frame, side=tk.LEFT, padx=8)

    root.mainloop()

    return result[0]


def _process_camera(cameras: list, building: str, cam_num: int) -> Optional[list[Zone]]:
    cam = find_camera(cameras, building, cam_num)
    if cam is None:
        print(f"  Camera not found: {building} — Камера {cam_num:02d}")
        return None

    print(f"  Fetching snapshot for {building} — Камера {cam_num:02d}...")
    jpeg = _fetch_jpeg(cam)
    if jpeg is None:
        print("  No snapshot available, skipping.")
        return None

    zones = _edit_zone(jpeg, building, cam_num)
    if zones is None:
        print("  Skipped.")
        return None

    zones_str = ", ".join(f"({z[0]}, {z[1]}, {z[2]}, {z[3]})" for z in zones)
    line = f'    ("{building}", {cam_num}): [{zones_str}],'
    print(f"\n  Paste into PARKING_ZONES:\n{line}\n")
    return zones


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
        print("Press Enter to accept zones, Esc to skip.\n")
        for building, cam_nums in PARKING_CAMERAS:
            for cam_num in cam_nums:
                print(f"--- {building} — Камера {cam_num:02d} ---")
                _process_camera(cameras, building, cam_num)


if __name__ == "__main__":
    main()
