"""Build the public review site (GitHub Pages) from the release bundles in output/.

    python pipeline/pages.py [--out site]

Each version gets its own folder with the review page, a playable MP4 per
language (taken out of the SCORM zip) and the zips themselves. The front page
lists every version, newest first. A version whose RELEASE.md is not yet
committed is still waiting in a review pull request and is shown as
"Pending review"; committed versions are "Approved" and link to their GitHub
Release.
"""
import argparse
import html
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from common import OUTPUT, ROOT, log, repo_url

LANGS = {"en": "English", "de": "German"}


def _tracked(path):
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", str(path)],
                       capture_output=True, text=True)
    return r.returncode == 0


def _version_key(name):
    return tuple(int(x) for x in re.findall(r"\d+", name))


def _release_info(vdir):
    notes = (vdir / "RELEASE.md").read_text(encoding="utf-8") if (vdir / "RELEASE.md").exists() else ""
    title = re.search(r"^# Release [^:]+:\s*(.+)$", notes, re.M)
    built = re.search(r"^Built (\d{4}-\d{2}-\d{2})", notes, re.M)
    changes = re.findall(r"^- (\w+)/([\w-]+): (.+)$", notes.split("## Upload")[0], re.M)
    return (title.group(1).strip() if title else vdir.parent.name,
            built.group(1) if built else "", changes)


def build(out):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    repo = repo_url()
    sections = []

    for mdir in sorted(p for p in OUTPUT.iterdir() if p.is_dir()):
        cards, module_title = [], mdir.name
        for vdir in sorted((p for p in mdir.iterdir() if p.is_dir()), key=lambda p: _version_key(p.name), reverse=True):
            dest = out / mdir.name / vdir.name
            dest.mkdir(parents=True)
            title, built, changes = _release_info(vdir)
            module_title = title
            pending = not _tracked(vdir / "RELEASE.md")

            if (vdir / "review.html").exists():
                shutil.copy2(vdir / "review.html", dest)
                if (vdir / "review").is_dir():
                    shutil.copytree(vdir / "review", dest / "review")
            for extra in ("artwork.png",):
                if (vdir / extra).exists():
                    shutil.copy2(vdir / extra, dest)

            videos, zips = [], []
            order = list(LANGS)
            for z in sorted(vdir.glob("*.zip"), key=lambda p: (order.index(p.stem.split("_")[-2])
                                                               if p.stem.count("_") >= 2 and p.stem.split("_")[-2] in order
                                                               else len(order), p.name)):
                shutil.copy2(z, dest)
                lang = z.stem.split("_")[-2] if z.stem.count("_") >= 2 else ""
                label = LANGS.get(lang, lang.upper() or z.stem)
                zips.append(f"<a href='{mdir.name}/{vdir.name}/{z.name}'>{label} (SCORM)</a>")
                with zipfile.ZipFile(z) as zf:
                    if "video.mp4" in zf.namelist():
                        mp4 = dest / f"{z.stem}.mp4"
                        mp4.write_bytes(zf.read("video.mp4"))
                        videos.append(f"<figure><figcaption>{label}</figcaption>"
                                      f"<video controls preload='metadata' "
                                      f"src='{mdir.name}/{vdir.name}/{mp4.name}#t=1'></video></figure>")

            status = ("<span class='badge pending'>Pending review</span>" if pending
                      else "<span class='badge ok'>Approved</span>")
            links = []
            if (dest / "review.html").exists():
                links.append(f"<a class='primary' href='{mdir.name}/{vdir.name}/review.html'>"
                             f"{'Review and approve' if pending else 'Review page'}</a>")
            if not pending and repo:
                links.append(f"<a href='{repo}/releases/tag/{mdir.name}-{vdir.name}'>GitHub Release</a>")
            links += zips
            summary = (f"{len(changes)} scene/language change(s)" if changes else "No scene changes")
            changed = "".join(f"<li>{html.escape(loc)}/{html.escape(sid)}: {html.escape(why)}</li>"
                              for loc, sid, why in changes[:12])
            video_block = f"<div class='videos'>{''.join(videos)}</div>" if videos else ""
            if video_block and cards and not pending:  # older approved versions: videos on demand
                video_block = f"<details class='watch'><summary>Watch videos</summary>{video_block}</details>"
            cards.append(
                f"<article class='{'is-pending' if pending else ''}'><header><h3>{html.escape(vdir.name)}</h3>{status}"
                f"<span class='meta'>{html.escape(built)} · {summary}</span></header>"
                f"<div class='links'>{''.join(links)}</div>"
                f"{f'<details><summary>What changed</summary><ul>{changed}</ul></details>' if changed else ''}"
                f"{video_block}</article>")
        sections.append(f"<section><h2>{html.escape(module_title)}</h2>{''.join(cards)}</section>")
        log(f"  site: {mdir.name} ({len(cards)} version(s))")

    repo_link = f"<a href='{repo}'>Source on GitHub</a>" if repo else ""
    (out / "index.html").write_text(f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Training releases</title>
<style>
:root{{--ink:#1d2433;--muted:#5b6475;--line:#dde1e7;--ok:#1a7f5a;--warn:#8a5a00;--warnbg:#fff3d6}}
*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,sans-serif;color:var(--ink);background:#f6f7f9}}
.top{{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid var(--line);padding:16px}}
.top h1{{margin:0;font-size:22px}}.top p{{margin:4px 0 0;color:var(--muted);font-size:14px}}
main{{max-width:1100px;margin:0 auto;padding:16px}}h2{{font-size:19px;margin:8px 0 12px}}
article{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:14px}}
article.is-pending{{border-color:#e7c46a;box-shadow:0 0 0 2px var(--warnbg)}}
article header{{display:flex;flex-wrap:wrap;align-items:center;gap:10px}}h3{{margin:0;font-size:18px}}
.badge{{font-size:12px;font-weight:bold;padding:3px 8px;border-radius:99px}}
.badge.ok{{background:#e3f4ec;color:var(--ok)}}.badge.pending{{background:var(--warnbg);color:var(--warn)}}
.meta{{color:var(--muted);font-size:14px}}.links{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}}
.links a{{border:1px solid var(--line);border-radius:6px;padding:7px 12px;color:var(--ink);text-decoration:none;font-size:14px}}
.links a.primary{{background:var(--ok);border-color:var(--ok);color:#fff;font-weight:bold}}
details{{font-size:14px;color:var(--muted);margin-bottom:10px}}
.videos{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:12px}}
figure{{margin:0}}figcaption{{font-size:13px;color:var(--muted);margin-bottom:4px}}
video{{width:100%;aspect-ratio:16/9;object-fit:contain;border-radius:6px;background:#000}}
details.watch summary{{cursor:pointer;color:var(--ink);font-size:14px;margin-bottom:10px}}footer{{color:var(--muted);font-size:13px;padding:8px 0 24px}}
footer a{{color:var(--muted)}}
</style>
<div class="top"><h1>Training releases</h1>
<p>Narrated how-to videos built from the app's screens, packaged as SCORM for KnowBe4. Newest first.</p></div>
<main>{''.join(sections) or '<p>No releases yet.</p>'}<footer>{repo_link}</footer></main></html>""", encoding="utf-8")
    (out / ".nojekyll").write_text("")
    log(f"Site ready: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "site"))
    build(Path(ap.parse_args().out))
