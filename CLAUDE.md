# Training pipeline: context for Claude Code

Prototype that turns an application's screens into narrated, multilingual
training videos (Synthesia avatars) packaged as SCORM 2004 4th Edition for
KnowBe4, refreshed on a schedule when the app's UI changes. See README.md for
the full design and commands.

## How it works
- `modules/<id>/module.yml` defines scenes (Playwright actions, highlight, screenshot),
  quiz answers and the Synthesia template mapping. Narration and quiz text per
  language live in `modules/<id>/i18n/<lang>.yml`.
- `pipeline/run.py` runs: capture (Playwright, per locale) -> pixel diff against
  `state/` baseline -> render only changed scenes (Synthesia, or dry-run stand-in
  clips) -> stitch + SCORM package + validate -> release bundle in `output/`.
- `tests/test_scorm.py <zip>` plays a package in a fake LMS and checks
  incomplete -> failed -> passed reporting.
- `pipeline/report.py` reads completions from the KnowBe4 Reporting API (read-only;
  sample data without a key).

## Commands (Windows PowerShell)
```
pip install -r requirements.txt
python -m playwright install chromium
python pipeline/run.py --module expense-claims                  # dry run, no accounts needed
python pipeline/run.py --module expense-claims --app-version 2  # simulate a UI change
python pipeline/run.py --module expense-claims --live --force   # real Synthesia renders
python tests/test_scorm.py output/expense-claims/<version>/<zip>
```
ffmpeg must be on the PATH (`winget install Gyan.FFmpeg`).

## Secrets
- `SYNTHESIA_API_KEY`, `KNOWBE4_API_KEY`, `KNOWBE4_REGION` come from environment
  variables only. Never write keys into code, YAML, or commits.
- `SYNTHESIA_TEST_MODE` defaults to `true` (watermarked renders that don't use credits).

## Status and next steps
1. Build the Synthesia Studio template with variables `script`, `screenshot`, `title`;
   put its ID in `module.yml` under `synthesia.template_id`.
2. First live run in test mode. The endpoint shapes in `pipeline/render.py`
   (`/v2/videos/fromTemplate`, asset upload) are unverified against a real
   account: check them against https://docs.synthesia.io/reference and fix on
   first error.
3. Upload the SCORM zips to KnowBe4 (ModStore > Custom Content). This is manual:
   the KnowBe4 API cannot upload content.
4. Point capture at a real application test environment instead of `demo_app/`.

## Conventions
- Scene clips are rendered per scene, keyed by a hash of screenshot + text + avatar,
  so unchanged scenes are never re-rendered (credit control).
- Package file names must stay ASCII-only (KnowBe4 rejects non-ASCII names).
- `work/` is scratch and git-ignored; `state/` is the approved baseline; `output/`
  holds release bundles.
- German text in `de.yml` is machine-translated starter text pending native review.
