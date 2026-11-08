"""Stage 3: stitch clips into one video per language, wrap each in a
SCORM 2004 4th Edition package that meets KnowBe4's upload rules, and write
the release bundle (packages, artwork, review page, upload checklist)."""
import html
import json
import os
import subprocess
import zipfile
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import FONT_BOLD, OUTPUT, ROOT, WORK, log, repo_url, scene_state

KNOWBE4_MAX_BYTES = 1024 ** 3
PLAYER = (ROOT / "pipeline" / "scorm_player.html").read_text(encoding="utf-8")

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{ident}" version="{version}"
  xmlns="http://www.imsglobal.org/xsd/imscp_v1p1"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_v1p3"
  xmlns:adlseq="http://www.adlnet.org/xsd/adlseq_v1p3"
  xmlns:adlnav="http://www.adlnet.org/xsd/adlnav_v1p3"
  xmlns:imsss="http://www.imsglobal.org/xsd/imsss"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsglobal.org/xsd/imscp_v1p1 imscp_v1p1.xsd http://www.adlnet.org/xsd/adlcp_v1p3 adlcp_v1p3.xsd http://www.adlnet.org/xsd/adlseq_v1p3 adlseq_v1p3.xsd http://www.adlnet.org/xsd/adlnav_v1p3 adlnav_v1p3.xsd http://www.imsglobal.org/xsd/imsss imsss_v1p0.xsd">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>2004 4th Edition</schemaversion>
  </metadata>
  <organizations default="ORG-1">
    <organization identifier="ORG-1">
      <title>{title}</title>
      <item identifier="ITEM-1" identifierref="RES-1">
        <title>{title}</title>
        <imsss:sequencing>
          <imsss:objectives>
            <imsss:primaryObjective objectiveID="PRIMARY" satisfiedByMeasure="true">
              <imsss:minNormalizedMeasure>{pass_mark}</imsss:minNormalizedMeasure>
            </imsss:primaryObjective>
          </imsss:objectives>
        </imsss:sequencing>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="RES-1" type="webcontent" adlcp:scormType="sco" href="index.html">
      <file href="index.html"/>
      <file href="video.mp4"/>
      <file href="poster.jpg"/>
    </resource>
  </resources>
</manifest>
"""


def _concat(clips, dest):
    lst = dest.with_suffix(".txt")
    lst.write_text("".join(f"file '{c}'\n" for c in clips))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-movflags", "+faststart", str(dest)], check=True)
    lst.unlink()


def _poster(video, dest):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(video),
                    "-frames:v", "1", "-q:v", "3", str(dest)], check=True)


def _artwork(title, dest):
    """Square thumbnail KnowBe4 shows learners before they start."""
    img = Image.new("RGB", (600, 600), (31, 58, 95))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BOLD, 46)
    words, lines, line = title.split(), [], ""
    for w in words:
        if d.textlength(f"{line} {w}".strip(), font=font) > 500:
            lines.append(line); line = w
        else:
            line = f"{line} {w}".strip()
    lines.append(line)
    y = 300 - len(lines) * 30
    for ln in lines:
        d.text((300, y), ln, font=font, fill="white", anchor="mm"); y += 60
    img.save(dest)


def _validate(zip_path):
    problems = []
    if zip_path.stat().st_size > KNOWBE4_MAX_BYTES:
        problems.append("package is over KnowBe4's 1 GB limit")
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if "imsmanifest.xml" not in names:
            problems.append("imsmanifest.xml is not at the root of the zip")
        bad = [n for n in names + [zip_path.name] if not n.isascii()]
        if bad:
            problems.append(f"non-ASCII file names (KnowBe4 rejects these): {bad}")
        if "2004 4th Edition" not in z.read("imsmanifest.xml").decode():
            problems.append("manifest is not SCORM 2004 4th Edition")
    return problems


def package(module, state, changes):
    mid = module["id"]
    state["build"] += 1
    version = f"{module['version'].rsplit('.', 1)[0]}.{state['build']}"
    rel = OUTPUT / mid / f"v{version}"
    rel.mkdir(parents=True, exist_ok=True)
    built = []

    for loc in module["locales"]:
        s = module["strings"][loc]
        clips = [scene_state(state, loc, sc["id"])["clip"] for sc in module["scenes"]]
        pdir = WORK / mid / "scorm" / loc
        pdir.mkdir(parents=True, exist_ok=True)
        _concat(clips, pdir / "video.mp4")
        _poster(pdir / "video.mp4", pdir / "poster.jpg")
        strings = {"title": s["module_title"], "quiz": s["quiz"],
                   "questions": [{"text": s["quiz"][q["key"]]["text"], "options": s["quiz"][q["key"]]["options"],
                                  "correct": q["correct"]} for q in module["quiz"]]}
        page = (PLAYER.replace("__LANG__", loc).replace("__TITLE__", html.escape(s["module_title"]))
                .replace("__STRINGS__", json.dumps(strings, ensure_ascii=False))
                .replace("__PASS_MARK__", str(module["pass_mark"])))
        (pdir / "index.html").write_text(page, encoding="utf-8")
        (pdir / "imsmanifest.xml").write_text(MANIFEST.format(
            ident=f"{mid}-{loc}", version=version, title=html.escape(s["module_title"]),
            pass_mark=module["pass_mark"]), encoding="utf-8")

        zpath = rel / f"{mid}_{loc}_v{version}.zip"   # ASCII-only by construction
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ["imsmanifest.xml", "index.html", "poster.jpg"]:
                z.write(pdir / name, name)
            z.write(pdir / "video.mp4", "video.mp4", compress_type=zipfile.ZIP_STORED)
        problems = _validate(zpath)
        if problems:
            raise SystemExit(f"Package {zpath.name} failed checks: {problems}")
        built.append((loc, zpath))
        log(f"  packaged {zpath.name} ({zpath.stat().st_size / 1e6:.1f} MB) - passes KnowBe4 checks")

    _artwork(module["strings"][module["locales"][0]]["module_title"], rel / "artwork.png")
    _write_review(module, changes, rel)
    _write_release_notes(module, version, changes, built, rel)
    return rel, version


def _approve_url():
    """Link to the open review pull request, where merging is the approval step.

    In GitHub Actions the repo comes from GITHUB_SERVER_URL/GITHUB_REPOSITORY;
    locally from the git remote. REVIEW_BRANCH matches the workflow's PR branch.
    """
    branch = os.environ.get("REVIEW_BRANCH", "training-refresh")
    repo = repo_url()
    return f"{repo}/pulls?q=is%3Apr+is%3Aopen+head%3A{branch}" if repo else None


def _write_review(module, changes, rel):
    """Before/after page for the human reviewer (attach to the pull request)."""
    from common import STATE
    mid = module["id"]
    shots = rel / "review"
    shots.mkdir(exist_ok=True)
    rows = []
    for c in changes:
        loc, sid = c["locale"], c["scene"]
        cells = []
        for label, src in [("Before (approved)", STATE / mid / "screens" / loc / f"{sid}.png"),
                           ("After (this run)", WORK / mid / "screens" / loc / f"{sid}.png"),
                           ("Changed pixels", WORK / mid / "screens" / loc / f"{sid}.diff.png")]:
            if src.exists():
                dest = shots / f"{loc}_{sid}_{label.split()[0].lower()}.png"
                dest.write_bytes(src.read_bytes())
                cells.append(f"<figure><figcaption>{label}</figcaption><img src='review/{dest.name}'></figure>")
        script = module["strings"][loc]["scenes"][sid]["script"]
        flag = ("<p class='warn'>Screen changed but narration did not: check the script still matches what's on screen.</p>"
                if c["screen_changed"] and not c["text_changed"] else "")
        rows.append(f"<section><h2>{loc.upper()} - {sid}</h2><p class='why'>{', '.join(c['reasons'])}</p>{flag}"
                    f"<div class='grid'>{''.join(cells)}</div><blockquote>{html.escape(script)}</blockquote></section>")
    body = "".join(rows) or "<p>No changes in this run.</p>"
    url = _approve_url()
    approve = (f"<a class='approve' href='{html.escape(url)}' target='_blank' rel='noopener'>Approve changes</a>"
               f"<span class='hint'>Opens the review pull request on GitHub. Merging it approves these screens "
               f"as the new baseline and releases this version.</span>" if url else
               "<span class='hint'>To approve, merge the review pull request on GitHub.</span>")
    approve = f"<div class='bar'>{approve}</div>" if changes else ""
    (rel / "review.html").write_text(f"""<!doctype html><meta charset="utf-8"><title>Review: {mid}</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;color:#1d2433;background:#fff}}h2{{font-size:17px;margin:0 0 4px}}
.top{{position:sticky;top:0;z-index:10;background:#fff;margin:-24px -24px 20px;padding:16px 24px 14px;
border-bottom:1px solid #dde1e7;box-shadow:0 2px 6px rgba(29,36,51,.08)}}.top h1{{margin:0 0 4px;font-size:24px}}
.top p{{margin:0 0 10px}}.bar{{display:flex;align-items:center;gap:14px;flex-wrap:wrap}}.hint{{color:#5b6475;font-size:14px}}
.approve{{background:#1a7f5a;color:#fff;font-weight:bold;text-decoration:none;padding:10px 18px;border-radius:6px}}
.approve:hover{{background:#146a4a}}
section{{border:1px solid #dde1e7;border-radius:8px;padding:16px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
img{{width:100%;border:1px solid #ccc}}figcaption{{font-size:13px;color:#5b6475;margin-bottom:4px}}
.why{{color:#5b6475;margin:0 0 8px}}.warn{{background:#fff3d6;color:#8a5a00;padding:8px 10px;border-radius:6px}}
blockquote{{margin:12px 0 0;padding:8px 12px;border-left:3px solid #2c6ecb;background:#f4f5f7}}</style>
<header class='top'><h1>Review: {html.escape(module['strings']['en']['module_title'])}</h1>
<p>{len(changes)} scene/language change(s). Check each screen and its narration below.</p>{approve}</header>{body}""", encoding="utf-8")


def _write_release_notes(module, version, changes, built, rel):
    s0 = module["strings"][module["locales"][0]]
    langs = {"en": "English", "de": "German"}
    lines = [f"# Release v{version}: {s0['module_title']}", "", f"Built {date.today().isoformat()}.", "",
             "## What changed", ""]
    lines += [f"- {c['locale']}/{c['scene']}: {', '.join(c['reasons'])}" for c in changes] or ["- Nothing (rebuild only)"]
    lines += ["", "## Upload to KnowBe4 (manual - the KnowBe4 API is read-only)", "",
              "First release:", "1. ModStore > Custom Content > Add Content > SCORM.",
              f"2. Title: {s0['module_title']}. Description: {s0['module_description']}",
              "3. Artwork: artwork.png (square).",
              "4. Add Translation for each language file below, then Publish.", "",
              "Updates: open the existing content item and replace each language file listed below, then Publish.", "",
              "| Language | File |", "|---|---|"]
    lines += [f"| {langs.get(loc, loc)} | {zp.name} |" for loc, zp in built]
    lines += ["", "Then enrol yourself in a test campaign and check: language picker, video plays, quiz passes/fails, "
              "and the result shows in training reports.", "",
              "## Decide", "", "- Is this change material enough to re-enrol people who already completed the module?"]
    (rel / "RELEASE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
