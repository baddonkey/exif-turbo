#!/usr/bin/env python3
"""Build a short video from full-window application captures."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import subprocess
import sys

import av
import numpy as np
from PIL import Image


_ROOT = Path(__file__).resolve().parent.parent
_SCREENSHOTS = _ROOT / "docs" / "screenshots"
_OUTPUT = _SCREENSHOTS / "exif-turbo-demo.mp4"
_POSTER = _SCREENSHOTS / "exif-turbo-demo-poster.png"
_SIZE = (1920, 1080)
_FRAME_RATE = 15
_FRAMES_PER_SCENE = 30

_SCENES = (
    "demo_indexed_folders.png",
    "demo_exif_results.png",
    "demo_ai_mode.png",
    "demo_browse_tab.png",
)


def _load_scenes() -> list[Image.Image]:
    scenes = [
        Image.open(_SCREENSHOTS / filename).convert("RGB") for filename in _SCENES
    ]
    for filename, scene in zip(_SCENES, scenes, strict=True):
        if scene.size != _SIZE:
            raise ValueError(f"{filename} must be {_SIZE}, got {scene.size}")
    return scenes


def _animation_frames(scenes: list[Image.Image]):
    for index, scene in enumerate(scenes):
        for _ in range(_FRAMES_PER_SCENE):
            yield scene
        if index + 1 < len(scenes):
            next_scene = scenes[index + 1]
            for step in range(1, 7):
                yield Image.blend(scene, next_scene, step / 7)


def build_demo() -> tuple[Path, Path]:
    subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "take_screenshots.py"), "--demo-only"],
        cwd=_ROOT,
        check=True,
    )
    scenes = _load_scenes()
    scenes[_SCENES.index("demo_exif_results.png")].save(_POSTER, format="PNG", optimize=True)

    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(_OUTPUT), mode="w", options={"movflags": "+faststart"})
    stream = container.add_stream("libx264", rate=_FRAME_RATE)
    stream.width, stream.height = _SIZE
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "18", "preset": "medium"}

    for frame_index, image in enumerate(_animation_frames(scenes)):
        video_frame = av.VideoFrame.from_ndarray(np.asarray(image), format="rgb24")
        video_frame.pts = frame_index
        video_frame.time_base = Fraction(1, _FRAME_RATE)
        for packet in stream.encode(video_frame):
            container.mux(packet)

    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return _OUTPUT, _POSTER


if __name__ == "__main__":
    video, poster = build_demo()
    print(f"Created {video.relative_to(_ROOT)} ({video.stat().st_size:,} bytes)")
    print(f"Created {poster.relative_to(_ROOT)} ({poster.stat().st_size:,} bytes)")