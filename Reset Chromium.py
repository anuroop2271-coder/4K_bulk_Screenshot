import shutil, asyncio
from pathlib import Path
from playwright.async_api import async_playwright

USERDATA_DIR = Path("./userdata")

# Delete profile
if USERDATA_DIR.exists():
    shutil.rmtree(USERDATA_DIR)
    print("Chromium reset successfully")

# Launch fresh browser
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(USERDATA_DIR),
            headless=False,
            viewport=None,
            args=["--start-maximized"]
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto("https://example.com")
        input("Press Enter to exit...")
        await browser.close()

asyncio.run(main())
