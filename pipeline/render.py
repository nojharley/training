"""Stage 2: turn each (scene, language) into a narrated avatar video.

One Synthesia video per scene, not per module, so a UI change to one screen
re-renders one short clip instead of the whole course. Clips are stitched
together in the package stage.

Without SYNTHESIA_API_KEY this runs in dry-run mode: it makes a stand-in clip
(screenshot + caption + presenter placeholder) so the rest of the pipeline
can be tested end to end for free.
"""
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from common import WORK, env, log, scene_state, sha

API = "https://api.synthesia.io/v2"
UPLOAD_API = "https://upload.api.synthesia.io/v2"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# ---------- live Synthesia ----------
# Endpoint shapes follow Synthesia's public API docs (videos/fromTemplate, assets).
# Check them against https://docs.synthesia.io/reference before going live.

class Synthesia:
    def __init__(self, api_key, test_mode=True):
        self.s = requests.Session()
        self.s.headers["Authorization"] = api_key
        self.test_mode = test_mode

    def upload_image(self, path):
        r = self.s.post(f"{UPLOAD_API}/assets", data=Path(path).read_bytes(),
                        headers={"Content-Type": "image/png"}, timeout=120)
        r.raise_for_status()
        return r.json()["id"]

    def render_from_template(self, template_id, title, data):
        body = {"test": self.test_mode, "templateId": template_id, "title": title,
                "visibility": "private", "templateData": data}
        r = self.s.post(f"{API}/videos/fromTemplate", json=body, timeout=60)
        r.raise_for_status()
        return r.json()["id"]

    def wait_and_download(self, video_id, dest, timeout_s=1800):
        # Production: use a Synthesia webhook instead of polling.
        start = time.time()
        while time.time() - start < timeout_s:
            r = self.s.get(f"{API}/videos/{video_id}", timeout=30)
            r.raise_for_status()
            v = r.json()
            if v.get("status") == "complete":
                with self.s.get(v["download"], stream=True, timeout=300) as dl:
                    dl.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in dl.iter_content(1 << 20):
                            f.write(chunk)
                return
            if v.get("status") in ("error", "rejected"):
                raise RuntimeError(f"Synthesia render {video_id} failed: {v}")
            time.sleep(20)
        raise TimeoutError(f"Synthesia render {video_id} still running after {timeout_s}s")


# ---------- dry run ----------

def _wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _dry_run_clip(screen, title, script, locale, dest):
    W, H = 1280, 720
    frame = Image.new("RGB", (W, H), (16, 24, 40))
    shot = Image.open(screen).convert("RGB")
    shot.thumbnail((W - 330, H - 190))
    frame.paste(shot, (30, 70))
    d = ImageDraw.Draw(frame)
    d.text((30, 22), title, font=ImageFont.truetype(FONT_BOLD, 28), fill="white")
    # presenter placeholder where the Synthesia avatar would stand
    px = W - 270
    d.rounded_rectangle((px, 70, W - 30, 70 + 300), radius=16, fill=(44, 62, 92))
    d.ellipse((px + 70, 110, px + 170, 210), fill=(140, 160, 190))
    d.rounded_rectangle((px + 45, 220, px + 195, 330), radius=40, fill=(140, 160, 190))
    small = ImageFont.truetype(FONT, 15)
    d.text((px + 120, 345), f"AI presenter ({locale})", font=small, fill=(200, 210, 225), anchor="mm")
    # caption = the narration Synthesia would speak
    cap_font = ImageFont.truetype(FONT, 19)
    lines = _wrap(d, script, cap_font, W - 80)[:4]
    top = H - 30 - len(lines) * 26
    d.rectangle((0, top - 12, W, H), fill=(0, 0, 0))
    for i, ln in enumerate(lines):
        d.text((40, top + i * 26), ln, font=cap_font, fill="white")
    d.text((W - 30, 30), "DRY RUN - not a Synthesia render", font=small, fill=(255, 190, 80), anchor="rm")
    png = Path(dest).with_suffix(".frame.png")
    frame.save(png)
    seconds = max(4, round(len(script.split()) / 2.4))  # ~ natural speaking pace
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png),
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(seconds),
                    "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
                    "-pix_fmt", "yuv420p", "-r", "25", "-c:a", "aac", "-shortest", str(dest)], check=True)
    png.unlink()


# ---------- stage ----------

def render(module, state, live=False):
    mid = module["id"]
    cfg = module["synthesia"]
    api_key = env("SYNTHESIA_API_KEY")
    live = live and bool(api_key)
    client = Synthesia(api_key, test_mode=env("SYNTHESIA_TEST_MODE", "true") == "true") if live else None
    mode = "live" if live else "dry-run"
    rendered = skipped = 0

    for loc in module["locales"]:
        outdir = WORK / mid / "clips" / loc
        outdir.mkdir(parents=True, exist_ok=True)
        for scene in module["scenes"]:
            sid = scene["id"]
            st = scene_state(state, loc, sid)
            text = module["strings"][loc]["scenes"][sid]
            screen = st["candidate_screen"]
            avatar = cfg.get("avatar_by_locale", {}).get(loc, "")
            key = sha(Path(screen).read_bytes(), text["title"], text["script"], avatar, mode)
            clip = outdir / f"{sid}.mp4"
            if st.get("render_key") == key and clip.exists():
                skipped += 1
                continue
            if live:
                asset_id = client.upload_image(screen)
                data = {cfg["script_variable"]: text["script"], cfg["image_variable"]: asset_id,
                        cfg["title_variable"]: text["title"]}
                vid = client.render_from_template(cfg["template_id"], f"{mid}/{loc}/{sid}", data)
                log(f"  rendering {loc}/{sid} on Synthesia ({vid})")
                client.wait_and_download(vid, clip)
            else:
                _dry_run_clip(screen, text["title"], text["script"], loc, clip)
                log(f"  rendered {loc}/{sid} (dry run)")
            st["render_key"] = key
            st["clip"] = str(clip)
            rendered += 1
    log(f"  {rendered} clip(s) rendered, {skipped} reused unchanged [{mode}]")
    return rendered
