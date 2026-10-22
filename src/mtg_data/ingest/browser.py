"""Start the browser the scrapers drive, or say plainly why it didn't start.

melee.gg turns away headless browsers (since 2026-06-10), so its scrapers run
a visible window: installed Google Chrome when there is one, Playwright's own
Chromium otherwise. When neither starts, Playwright raises a stack of
launcher internals. A new user needs one line saying what to install.
"""


def launch(pw, headless=False, prefer_chrome=True):
    """A Playwright browser, or SystemExit with the fix spelled out."""
    errors = []
    if prefer_chrome:
        try:
            return pw.chromium.launch(channel="chrome", headless=headless)
        except Exception as exc:
            errors.append(exc)
    try:
        return pw.chromium.launch(headless=headless)
    except Exception as exc:
        errors.append(exc)
    detail = str(errors[-1]).strip().splitlines()[0] if errors else "unknown error"
    raise SystemExit(
        "Couldn't start a browser to scrape with.\n"
        "  Install Playwright's Chromium:  python -m playwright install chromium\n"
        "  (or install Google Chrome, which the melee.gg scraper prefers)\n"
        f"  Detail: {detail}")
