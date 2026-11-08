"""Run the whole refresh: capture -> detect changes -> render -> package -> release bundle.

  python pipeline/run.py --module expense-claims                 # dry run, demo app v1
  python pipeline/run.py --module expense-claims --app-version 2 # simulate a UI release
  python pipeline/run.py --module expense-claims --live          # real Synthesia renders
"""
import argparse
import sys

from capture import approve_screens, capture
from common import load_module, load_state, log, save_state
from package import package
from render import render


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", required=True)
    ap.add_argument("--app-version", default="1", help="demo app UI version (1 or 2)")
    ap.add_argument("--live", action="store_true", help="render with Synthesia (needs SYNTHESIA_API_KEY)")
    ap.add_argument("--force", action="store_true", help="build a release even if nothing changed")
    a = ap.parse_args()

    module = load_module(a.module)
    state = load_state(a.module)

    log("1/4 Capturing screens")
    changes = capture(module, state, a.app_version)
    if not changes and not a.force:
        log("No changes detected. Nothing to release.")
        return 0
    log(f"    {len(changes)} scene/language change(s)")

    log("2/4 Rendering narrated clips")
    render(module, state, live=a.live)

    log("3/4 Packaging SCORM for KnowBe4")
    rel, version = package(module, state, changes)

    log("4/4 Approving new baseline")
    # In CI this happens when the reviewer merges the pull request.
    approve_screens(module, state)
    save_state(a.module, state)
    log(f"Release v{version} ready: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
