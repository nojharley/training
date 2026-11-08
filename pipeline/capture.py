"""Stage 1: drive the app with Playwright in each language, screenshot every scene,
and compare against the last approved screenshots to find what changed."""
import functools
import http.server
import shutil
import socketserver
import threading

from PIL import Image, ImageChops

from common import DEMO_APP, STATE, WORK, env, log, scene_state, sha

# Ignore anti-aliasing noise: a scene only counts as changed if more than
# this share of pixels differ noticeably.
CHANGE_THRESHOLD = 0.001
PIXEL_TOLERANCE = 24


def _serve(directory):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _launch(p):
    exe = env("CHROME_PATH")
    if exe:
        return p.chromium.launch(executable_path=exe)
    try:
        return p.chromium.launch()
    except Exception:
        return p.chromium.launch(channel="chrome")


def _run_actions(page, actions, strings):
    for act in actions:
        if "click" in act:
            page.click(act["click"])
        elif "fill" in act:
            a = act["fill"]
            value = strings[a["value_key"]] if "value_key" in a else a["value"]
            page.fill(a["selector"], value)
        elif "select" in act:
            page.select_option(act["select"]["selector"], act["select"]["value"])


def _diff(old_path, new_path, overlay_path):
    old, new = Image.open(old_path).convert("RGB"), Image.open(new_path).convert("RGB")
    if old.size != new.size:
        return 1.0
    diff = ImageChops.difference(old, new).convert("L").point(lambda v: 255 if v > PIXEL_TOLERANCE else 0)
    changed = sum(1 for v in diff.getdata() if v)
    ratio = changed / (diff.width * diff.height)
    if ratio > CHANGE_THRESHOLD:
        # Review aid: new screenshot, faded, with changed pixels in magenta.
        base = Image.blend(new, Image.new("RGB", new.size, "white"), 0.55)
        base.paste(Image.new("RGB", new.size, (230, 0, 160)), mask=diff)
        base.save(overlay_path)
    return ratio


def capture(module, state, app_version="1"):
    from playwright.sync_api import sync_playwright

    mid = module["id"]
    vp = module["app"]["viewport"]
    httpd = _serve(DEMO_APP)
    base = f"http://127.0.0.1:{httpd.server_address[1]}{module['app']['path']}"
    changes = []

    with sync_playwright() as p:
        browser = _launch(p)
        for loc in module["locales"]:
            strings = module["strings"][loc]
            outdir = WORK / mid / "screens" / loc
            outdir.mkdir(parents=True, exist_ok=True)
            for scene in module["scenes"]:
                sid = scene["id"]
                ctx = browser.new_context(viewport=vp, locale=loc, device_scale_factor=1)
                page = ctx.new_page()
                page.goto(f"{base}?lang={loc}&v={app_version}")
                _run_actions(page, scene["actions"], strings)
                page.wait_for_load_state("networkidle")
                if scene.get("highlight"):
                    # Draw attention to the control the narration talks about.
                    page.locator(scene["highlight"]).evaluate(
                        "el => { el.style.outline = '4px solid #f5a623'; el.style.outlineOffset = '4px'; }")
                sel = scene.get("screenshot", "viewport")
                target = page if sel == "viewport" else page.locator(sel)
                shot = outdir / f"{sid}.png"
                target.screenshot(path=str(shot), animations="disabled", caret="hide")
                ctx.close()

                approved = STATE / mid / "screens" / loc / f"{sid}.png"
                st = scene_state(state, loc, sid)
                reasons = []
                if not approved.exists():
                    reasons.append("new scene")
                else:
                    ratio = _diff(approved, shot, outdir / f"{sid}.diff.png")
                    if ratio > CHANGE_THRESHOLD:
                        reasons.append(f"screen changed ({ratio:.1%} of pixels)")
                text = strings["scenes"][sid]
                text_hash = sha(text["title"], text["script"])
                if st.get("text_hash") and st["text_hash"] != text_hash:
                    reasons.append("narration edited")
                if reasons:
                    changes.append({"locale": loc, "scene": sid, "reasons": reasons,
                                    "screen_changed": any("screen" in r for r in reasons),
                                    "text_changed": "narration edited" in reasons})
                st["candidate_text_hash"] = text_hash
                st["candidate_screen"] = str(shot)
                log(f"  captured {loc}/{sid}" + (f"  -> {', '.join(reasons)}" if reasons else ""))
        browser.close()
    httpd.shutdown()
    return changes


def approve_screens(module, state):
    """Promote this run's screenshots to the approved baseline (in CI: merging the PR)."""
    mid = module["id"]
    for loc in module["locales"]:
        dest = STATE / mid / "screens" / loc
        dest.mkdir(parents=True, exist_ok=True)
        for scene in module["scenes"]:
            st = scene_state(state, loc, scene["id"])
            shutil.copyfile(st["candidate_screen"], dest / f"{scene['id']}.png")
            st["text_hash"] = st.pop("candidate_text_hash")
            st.pop("candidate_screen", None)
