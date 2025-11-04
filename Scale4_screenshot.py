import asyncio
from playwright.async_api import async_playwright

OVERLAY_JS = r"""
(() => {
  // Avoid injecting multiple times
  if (window.__overlay_injected__) return;
  window.__overlay_injected__ = true;

  // Create overlay container
  const overlay = document.createElement("div");
  overlay.id = "custom-draggable-overlay";
  overlay.style.position = "fixed";
  overlay.style.top = "120px";
  overlay.style.left = "120px";
  overlay.style.width = "220px";
  overlay.style.height = "130px";
  overlay.style.background = "rgba(0, 0, 0, 0.6)";
  overlay.style.color = "white";
  overlay.style.border = "1px solid #fff";
  overlay.style.borderRadius = "8px";
  overlay.style.padding = "10px";
  overlay.style.zIndex = "999999";
  overlay.style.cursor = "move";
  overlay.style.userSelect = "none";
  overlay.innerHTML = `
    <div style="font-weight:bold;margin-bottom:5px;">Overlay Panel</div>
    <div style="font-size:13px;">You can drag this box anywhere.</div>
  `;
  document.body.appendChild(overlay);

  // Drag handling
  let isDragging = false;
  let offsetX = 0, offsetY = 0;

  overlay.addEventListener("mousedown", (e) => {
    isDragging = true;
    offsetX = e.clientX - overlay.offsetLeft;
    offsetY = e.clientY - overlay.offsetTop;
    overlay.style.opacity = "0.7";
  });

  document.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    overlay.style.left = `${e.clientX - offsetX}px`;
    overlay.style.top = `${e.clientY - offsetY}px`;
  });

  document.addEventListener("mouseup", () => {
    isDragging = false;
    overlay.style.opacity = "1";
  });
})();
"""

async def main():
    async with async_playwright() as p:
        print("[INFO] Launching Chromium with persistent context...")
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto("https://single.mcns.io", wait_until="domcontentloaded")
        print("[INFO] Page loaded successfully.")

        # Inject overlay
        print("[INFO] Injecting draggable overlay...")
        await page.add_script_tag(content=OVERLAY_JS)
        print("[INFO] Overlay injected. You can now drag it around in the browser.")

        # Keep the browser running
        print("[INFO] Press Ctrl+C to close.")
        await asyncio.sleep(3600)  # Keep open for an hour

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
