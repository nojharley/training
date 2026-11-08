"""Shared helpers: paths, module loading, state (what was last captured/rendered/released)."""
import hashlib
import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "modules"
DEMO_APP = ROOT / "demo_app"
STATE = ROOT / "state"
WORK = ROOT / "work"
OUTPUT = ROOT / "output"


def _first_font(*names):
    """First font file that exists on this machine (Linux DejaVu, Windows, macOS)."""
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in names:
        p = Path(name) if os.path.isabs(name) else windir / name
        if p.exists():
            return str(p)
    raise FileNotFoundError(f"none of these fonts found: {names}")


FONT = _first_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "arial.ttf",
                   "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf")
FONT_BOLD = _first_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "arialbd.ttf",
                        "/Library/Fonts/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")


def load_module(module_id):
    mdir = MODULES / module_id
    module = yaml.safe_load((mdir / "module.yml").read_text(encoding="utf-8"))
    strings = {}
    for loc in module["locales"]:
        strings[loc] = yaml.safe_load((mdir / "i18n" / f"{loc}.yml").read_text(encoding="utf-8"))
    module["strings"] = strings
    return module


def sha(*parts):
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, str):
            p = p.encode("utf-8")
        h.update(p)
        h.update(b"\x00")
    return h.hexdigest()[:16]


def state_path(module_id):
    return STATE / module_id / "state.json"


def load_state(module_id):
    p = state_path(module_id)
    if p.exists():
        return json.loads(p.read_text())
    return {"build": 0, "scenes": {}}


def save_state(module_id, state):
    p = state_path(module_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def scene_state(state, locale, scene_id):
    return state["scenes"].setdefault(locale, {}).setdefault(scene_id, {})


def log(msg):
    print(msg, flush=True)


def env(name, default=None):
    v = os.environ.get(name)
    return v if v else default
