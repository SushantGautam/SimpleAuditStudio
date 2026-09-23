"""Browser-level E2E tests using Playwright.

These tests exercise the full SPA against a running Docker Compose stack.
They require the stack to be up (docker compose up -d) with at least one
completed audit run present.

Run locally:
    docker compose up -d
    .venv/bin/python e2e/test_ui.py

In CI (GitHub Actions):
    The workflow builds the stack, waits for health, then runs this script.
"""

import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import Page, expect, sync_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && python -m playwright install chromium")
    sys.exit(1)

BASE_URL = "http://localhost:8000"
ADMIN_USER = "admin"
ADMIN_PASS = "e2etestpass123"


def wait_for_health(timeout: int = 60) -> None:
    """Wait until the web service reports healthy."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(f"{BASE_URL}/healthz", timeout=3)
            if resp.status == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"Web service did not become healthy within {timeout}s")


def login(page: Page) -> None:
    """Sign in via the SPA auth screen."""
    page.goto(BASE_URL)
    page.wait_for_selector("#auth-username", timeout=10_000)
    page.fill("#auth-username", ADMIN_USER)
    page.fill("#auth-password", ADMIN_PASS)
    page.click("#auth-submit")
    # Wait for the app shell (nav bar appears after successful auth)
    page.wait_for_selector("nav button", timeout=15_000)


def test_login_and_dashboard(page: Page) -> None:
    """Login succeeds and dashboard shows stats + runs table."""
    login(page)
    # Dashboard heading
    expect(page.locator("main h2")).to_have_text("Dashboard")
    # Stats cards present
    expect(page.locator("main .stat-card, main [class*=stat]")).to_have_count(4)
    # Runs table exists
    expect(page.locator("table")).to_be_visible()


def test_navigation_all_views(page: Page) -> None:
    """All 6 nav buttons switch the main view correctly."""
    login(page)
    views = [
        ("Dashboard", "Dashboard"),
        ("New Audit", "New Audit"),
        ("Queue", "Audit Queue"),
        ("Scenarios", "Scenario Library"),
        ("Models", "Models & Profiles"),
        ("Compare", "Compare Audits"),
    ]
    for i, (btn_text, expected_heading) in enumerate(views, start=1):
        page.click(f"nav button:nth-child({i})")
        page.wait_for_timeout(300)
        heading = page.locator("main h2").first
        expect(heading).to_contain_text(expected_heading.split()[0])


def test_new_audit_form_populated(page: Page) -> None:
    """New Audit view has populated selectors (set, models)."""
    login(page)
    page.click("nav button:nth-child(2)")  # New Audit
    page.wait_for_timeout(500)
    # Scenario set selector should have at least one option
    set_select = page.locator("select").first
    options = set_select.locator("option")
    expect(options.first).to_be_attached()
    # Submit button present
    expect(page.locator("button:has-text('Submit audit')")).to_be_visible()


def test_scenario_library_export_import_buttons(page: Page) -> None:
    """Scenario Library shows Export and Import buttons."""
    login(page)
    page.click("nav button:nth-child(4)")  # Scenarios
    page.wait_for_timeout(500)
    expect(page.locator("button:has-text('Export')")).to_be_visible()
    expect(page.locator("button:has-text('Import')")).to_be_visible()
    expect(page.locator("button:has-text('+ New scenario')")).to_be_visible()


def test_models_view_shows_endpoints(page: Page) -> None:
    """Models view displays registered endpoints."""
    login(page)
    page.click("nav button:nth-child(5)")  # Models
    page.wait_for_timeout(500)
    # Should show at least the mock model endpoint
    expect(page.locator("main")).to_contain_text("Mock Model")
    # Add endpoint form present
    expect(page.locator("button:has-text('Add endpoint')")).to_be_visible()


def test_queue_shows_finished_runs(page: Page) -> None:
    """Queue view shows finished runs section."""
    login(page)
    page.click("nav button:nth-child(3)")  # Queue
    page.wait_for_timeout(500)
    expect(page.locator("main")).to_contain_text("Finished")


def test_audit_detail_frozen_manifest(page: Page) -> None:
    """Clicking a run opens detail with frozen reproducibility manifest."""
    login(page)
    # Go to dashboard
    page.click("nav button:nth-child(1)")
    page.wait_for_timeout(500)
    # Click first row in the runs table
    rows = page.locator("table tbody tr")
    count = rows.count()
    if count == 0:
        print("SKIP: no audit runs in database")
        return
    rows.first.click()
    page.wait_for_timeout(1000)
    # Detail view should show the frozen manifest fields
    main = page.locator("main")
    expect(main).to_contain_text("Set hash")
    expect(main).to_contain_text("SimpleAudit")
    expect(main).to_contain_text("Git commit")


def test_compare_empty_state(page: Page) -> None:
    """Compare view shows appropriate message when <2 completed runs."""
    login(page)
    page.click("nav button:nth-child(6)")  # Compare
    page.wait_for_timeout(500)
    main = page.locator("main")
    # Either shows selection UI or the "need at least two" message
    text = main.inner_text()
    assert "compare" in text.lower() or "at least two" in text.lower(), f"Unexpected compare view: {text[:200]}"


def main() -> int:
    wait_for_health()
    passed = 0
    failed = 0
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        tests = [
            ("login_and_dashboard", test_login_and_dashboard),
            ("navigation_all_views", test_navigation_all_views),
            ("new_audit_form_populated", test_new_audit_form_populated),
            ("scenario_library_export_import", test_scenario_library_export_import_buttons),
            ("models_view_endpoints", test_models_view_shows_endpoints),
            ("queue_finished_runs", test_queue_shows_finished_runs),
            ("audit_detail_manifest", test_audit_detail_frozen_manifest),
            ("compare_empty_state", test_compare_empty_state),
        ]

        for name, fn in tests:
            try:
                # Fresh page per test to avoid state leakage
                page.goto(BASE_URL)
                page.wait_for_timeout(500)
                fn(page)
                print(f"  PASS  {name}")
                passed += 1
            except Exception as e:
                print(f"  FAIL  {name}: {e}")
                failed += 1
                errors.append((name, str(e)))

        browser.close()

    print(f"\n{'='*50}")
    print(f"E2E UI Results: {passed} passed, {failed} failed, {passed+failed} total")
    if errors:
        print("\nFailures:")
        for name, err in errors:
            print(f"  - {name}: {err[:120]}")
    print(f"{'='*50}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
