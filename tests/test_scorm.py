"""Smoke-test a built SCORM package inside a fake LMS: the quiz should stay locked
until the video is watched, a wrong attempt should fail, a right one should pass.

  python tests/test_scorm.py output/expense-claims/v1.0.2/expense-claims_de_v1.0.2.zip
"""
import functools
import http.server
import shutil
import socketserver
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def main(zip_path):
    tmp = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp / "pkg")
    shutil.copy(ROOT / "tests" / "scorm_harness.html", tmp / "harness.html")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    httpd = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(tmp)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/harness.html?pkg=pkg/index.html"

    module = yaml.safe_load((ROOT / "modules" / "expense-claims" / "module.yml").read_text())
    right = [q["correct"] for q in module["quiz"]]
    wrong = ["a" if r != "a" else "b" for r in right]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(url)
        sco = page.frame_locator("#sco")
        store = lambda: page.evaluate("() => ({...window.lmsStore})")

        sco.locator("#quiz.locked").wait_for()
        assert store().get("cmi.completion_status") == "incomplete", store()
        print("ok  started: completion_status=incomplete, quiz locked")

        page.frames[1].evaluate("""() => new Promise(r => { const v = document.getElementById('video');
            const go = () => { v.currentTime = v.duration - 0.1; v.dispatchEvent(new Event('ended')); r(); };
            v.readyState >= 1 ? go() : v.addEventListener('loadedmetadata', go); })""")
        sco.locator("#quiz:not(.locked)").wait_for()
        print("ok  quiz unlocked after video watched")

        sco.locator("#submit").click()
        assert sco.locator("#err").inner_text().strip(), "expected an 'answer every question' error"
        print("ok  empty submit blocked:", sco.locator("#err").inner_text())

        for i, a in enumerate(wrong):
            sco.locator(f"input[name=q{i}][value={a}]").check()
        sco.locator("#submit").click()
        assert store()["cmi.success_status"] == "failed", store()
        print("ok  wrong answers ->", sco.locator("#result").inner_text())

        for i, a in enumerate(right):
            sco.locator(f"input[name=q{i}][value={a}]").check()
        sco.locator("#submit").click()
        s = store()
        assert s["cmi.success_status"] == "passed" and s["cmi.completion_status"] == "completed", s
        print("ok  right answers ->", sco.locator("#result").inner_text())
        print("    LMS now holds:", {k: v for k, v in s.items() if "status" in k or "score" in k})
        page.screenshot(path=str(Path(zip_path).with_suffix(".test.png")))
        browser.close()
    httpd.shutdown()
    print("PASS")


if __name__ == "__main__":
    main(sys.argv[1])
