# Multilingual training pipeline (prototype)

Turns an application's screens into narrated, multilingual training for KnowBe4,
and refreshes it on a schedule when the app changes.

```
demo app ──► capture (Playwright, per language) ──► diff vs approved screens
                                                        │ only changed scenes
                                                        ▼
         KnowBe4 ◄── manual upload ◄── SCORM 2004 packages ◄── render (Synthesia, per scene)
            │
            └──► Reporting API (read-only) ──► completion report
```

Everything runs out of the box in **dry-run mode**: no Synthesia or KnowBe4
account needed. Dry-run clips show the screenshot, the narration as captions and
a placeholder where the avatar would be.

## Quick start

```bash
pip install -r requirements.txt
python -m playwright install chromium        # needs ffmpeg on the PATH too

python pipeline/run.py --module expense-claims                 # first build
python pipeline/run.py --module expense-claims                 # nothing changed -> no release
python pipeline/run.py --module expense-claims --app-version 2 # simulate a UI release
python tests/test_scorm.py output/expense-claims/v1.0.2/expense-claims_de_v1.0.2.zip
python pipeline/report.py --current v1.0.2
```

The `--app-version 2` run is the point of the demo: the demo app renames and
recolours its submit button, the pipeline spots that 3 of 5 scenes changed in
each language, re-renders only those 6 clips (reusing the other 4) and builds
release v1.0.2 with a review page.

## What's in a release (`output/<module>/v<version>/`)

| File | Use |
|---|---|
| `<module>_<lang>_v<version>.zip` | SCORM 2004 4th Ed package, one per language, checked against KnowBe4's rules (manifest at root, ASCII-only names, under 1 GB) |
| `artwork.png` | Square thumbnail for the KnowBe4 content item |
| `review.html` | Before / after / changed-pixel view of every changed scene, plus the narration; flags screens that changed when the narration didn't |
| `RELEASE.md` | What changed and the KnowBe4 upload checklist |

Each package plays the video, unlocks a three-question quiz once 90% has been
watched, reports score and Passed/Failed, and resumes where the learner stopped.

## Layout

```
demo_app/                 bilingual stand-in app (?lang=en|de, ?v=1|2)
modules/<id>/module.yml   scenes: browser actions, highlight, quiz answers, Synthesia template mapping
modules/<id>/i18n/*.yml   narration, titles, quiz text per language
pipeline/capture.py       Playwright capture + pixel diff
pipeline/render.py        Synthesia client (live) or stand-in clips (dry run); one clip per scene
pipeline/package.py       stitch clips, build + validate SCORM, review page, release notes
pipeline/report.py        KnowBe4 Reporting API completions (sample data without a key)
pipeline/run.py           runs the stages in order
tests/                    fake-LMS harness and package smoke test
state/                    approved screenshots + hashes (commit this; it is the baseline)
.github/workflows/        weekly schedule -> pull request for review
```

## Going live

### Synthesia
1. In Synthesia Studio, build one template with variables for the **script**,
   a **screenshot** image and a **title**. Publish it as a template.
2. Put its ID and your variable names in `module.yml` under `synthesia:`.
3. `export SYNTHESIA_API_KEY=...` and run with `--live`. `SYNTHESIA_TEST_MODE`
   defaults to `true` (watermarked test renders); set it to `false` for real ones.
4. Check the endpoint shapes in `render.py` against Synthesia's current API
   reference before relying on them, and swap polling for a webhook in production.

Cost control is built in: a clip only re-renders when its screenshot, script,
title or avatar changes.

### KnowBe4
- **Upload is manual**: the KnowBe4 API is read-only. First release: ModStore >
  Custom Content > Add Content > SCORM, then Add Translation per language.
  Updates: replace each language file in the existing item. `RELEASE.md` walks through it.
- **Reporting**: an Account Admin creates a Reporting API key (Account Settings > API).
  Set `KNOWBE4_API_KEY` and `KNOWBE4_REGION` (`us`, `eu`, `ca`, `uk`, `de`) and run
  `report.py`. Field names in the enrollment records may need adjusting once you
  see real data.
- Test each new package in SCORM Cloud or `tests/test_scorm.py` before uploading;
  it gives far clearer errors than KnowBe4.

### Your own application
Replace `demo_app/` with the URL of a test environment (edit `capture.py` to point
at it rather than the local server), add a login step to each scene's actions,
use a demo account with fake data, and write a `module.yml` per process.

### Scheduling
Push to GitHub, add `SYNTHESIA_API_KEY` as a repository secret, and the workflow
runs weekly (or on demand, or from your app's release pipeline). It opens a pull
request; merging it is the approval step.

## Known prototype limits
- Translations in `de.yml` are starter machine translations; a native speaker must review them.
- One avatar per language; no per-scene presenter changes.
- XSD schema files aren't bundled in the SCORM zip. KnowBe4 and SCORM Cloud accept
  this; a strict LMS may want them added.
- `state/` is updated by the run itself; in CI it only reaches `main` when the PR is merged.
