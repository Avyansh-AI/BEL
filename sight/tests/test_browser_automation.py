import asyncio
import pytest

from sight_core.browser_automation import (
    BrowserAutomationService,
    BrowserSecurityError,
    validate_target_url,
)


def test_url_validation_safe_domains():
    assert validate_target_url("https://example.com") == "https://example.com"
    assert validate_target_url("http://github.com/repo") == "http://github.com/repo"
    assert validate_target_url("wikipedia.org") == "https://wikipedia.org"


def test_url_validation_prohibited_schemes():
    for bad_url in [
        "file:///C:/Windows/System32/cmd.exe",
        "javascript:alert(1)",
        "data:text/html,<h1>Pwned</h1>",
        "about:blank",
        "ws://localhost:8080",
    ]:
        with pytest.raises(BrowserSecurityError, match="scheme"):
            validate_target_url(bad_url)


def test_url_validation_prohibited_hosts():
    for local_url in [
        "http://127.0.0.1:8080/secret",
        "http://localhost:3000",
        "http://0.0.0.0",
        "http://169.254.169.254/metadata",
    ]:
        with pytest.raises(BrowserSecurityError, match="restricted"):
            validate_target_url(local_url, allow_localhost=False)

    # When localhost is explicitly authorized
    assert validate_target_url("http://127.0.0.1:8080/app", allow_localhost=True) == "http://127.0.0.1:8080/app"


def test_browser_page_interaction():
    async def run_test():
        service = BrowserAutomationService(headless=True)
        try:
            page = await service._ensure_page()
            html_content = """
            <!DOCTYPE html>
            <html>
            <head><title>Test Automation Page</title></head>
            <body>
                <h1>Welcome to BEL Browser</h1>
                <h2>Subheading Details</h2>
                <p>This is a paragraph of automated text content.</p>
                <a href="https://example.com/docs">Documentation Link</a>
                <form id="test-form">
                    <input id="username" name="user" type="text" placeholder="Enter username" />
                    <button id="submit-btn" type="button">Submit Query</button>
                </form>
            </body>
            </html>
            """
            await page.set_content(html_content, wait_until="domcontentloaded")

            # Extract content
            content = await service.extract_content()
            assert content.title == "Test Automation Page"
            assert "Welcome to BEL Browser" in content.headings
            assert "Subheading Details" in content.headings
            assert "automated text content" in content.text
            assert any("Documentation Link" in ln for ln in content.links)

            # Interactive elements
            elements = await service.get_interactive_elements()
            assert len(elements) >= 3
            tags = [e.tag for e in elements]
            assert "button" in tags
            assert "input" in tags
            assert "a" in tags

            # Fill field
            fill_res = await service.fill_field("#username", "agent_bel")
            assert fill_res["ok"] is True
            val = await page.input_value("#username")
            assert val == "agent_bel"

            # Click button
            click_res = await service.click_element("#submit-btn")
            assert click_res["ok"] is True

            # Screenshot
            shot_bytes = await service.capture_screenshot(format="jpeg")
            assert isinstance(shot_bytes, bytes)
            assert len(shot_bytes) > 200
            assert shot_bytes[:2] == b"\xff\xd8"
        finally:
            await service.close()

    asyncio.run(run_test())
