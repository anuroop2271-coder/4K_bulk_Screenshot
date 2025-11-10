#Scale4_screenshot.py
#Bulk operations for taking high-resolution (4x) screenshots of web pages


import asyncio
import json
import logging
import getpass
from pathlib import Path
from playwright.async_api import async_playwright, Page

JSON_FILE = Path("screenshots.json")
SCREENSHOT_DIR = Path("screenshots")
USERDATA_DIR = Path("./userdata")
LOG_FILE = Path("screenshot_log.txt")
HIGH_RESOLUTION_SCALE = 4  # High-res factor


username = getpass.getuser()
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | user=%(username)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

class UsernameFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "username"):
            record.username = username
        return True

logger = logging.getLogger()
for handler in logger.handlers:
    handler.addFilter(UsernameFilter())

async def safe_goto(page, url, timeout=60000):
    """Navigate safely, ignoring interruptions or internal redirects."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            # Some SPAs never reach 'networkidle' — that's fine
            pass
        return True
    except Exception as e:
        print(f"[WARN] Navigation to {url} interrupted or redirected: {e}")
        return False



async def get_current_url(context):
    """Return the most recently active tab's current URL."""
    for page in reversed(context.pages):
        try:
            url = await page.evaluate("location.href")
            if url and not url.startswith("about:"):
                return page, url
        except Exception:
            continue
    # fallback
    return context.pages[-1], context.pages[-1].url


def convert_events_to_actions(events):
    """Convert raw JS events into structured Playwright actions."""
    if not events:
        return []
    actions = []
    last_time = events[0]["t"]
    for ev in events:
        delta = ev["t"] - last_time
        if delta > 40:
            actions.append({"type": "wait", "ms": delta})
        if ev["type"] == "click":
            actions.append({"type": "click", "x": ev["x"], "y": ev["y"]})
        elif ev["type"] == "scrollTo":
            actions.append({"type": "scrollTo", "x": ev["x"], "y": ev["y"]})
            
        elif ev["type"] == "mousedown":
            actions.append({"type": "mousedown", "x": ev["x"], "y": ev["y"]})
        elif ev["type"] == "mousemove":
            actions.append({"type": "mousemove", "x": ev["x"], "y": ev["y"]})
        elif ev["type"] == "mouseup":
            actions.append({"type": "mouseup", "x": ev["x"], "y": ev["y"]})            
        elif ev["type"] == "keydown":
            actions.append({"type": "keyboard", "key": ev["key"]})
        elif ev["type"] == "wheel":
            actions.append({"type": "wheel", "deltaX": ev.get("deltaX", 0), "deltaY": ev.get("deltaY", 0), "selector": ev.get("selector", "")})
        last_time = ev["t"]
    return actions

async def replay_actions(page, actions):
    for act in actions:
        typ = act["type"]

        if typ == "wait":
            await asyncio.sleep(act["ms"] / 1000)

        elif typ == "click":
            await page.mouse.click(act["x"], act["y"])

        elif typ == "mousedown":
            await page.mouse.move(act["x"], act["y"])
            await page.mouse.down()

        elif typ == "mousemove":
            await page.mouse.move(act["x"], act["y"])

        elif typ == "mouseup":
            await page.mouse.move(act["x"], act["y"])
            await page.mouse.up()

        elif typ == "scrollTo":
            await page.evaluate(f"window.scrollTo({act['x']}, {act['y']})")

        # ✅ Wheel event replay fix — now also handles missing selectors
        elif typ == "wheel":
            selector = act.get("selector", "")
            dx = act.get("deltaX", 0)
            dy = act.get("deltaY", 0)

            if selector:
                # Try dispatching a wheel event to the original element
                script = f"""
                (function(){{
                  try {{
                    const el = document.querySelector({json.dumps(selector)});
                    if (el) {{
                      const ev = new WheelEvent('wheel', {{
                        deltaX: {dx},
                        deltaY: {dy},
                        bubbles: true,
                        cancelable: true
                      }});
                      el.dispatchEvent(ev);
                      el.scrollBy({dx}, {dy});
                      return true;
                    }}
                  }} catch (e) {{
                    console.warn('Wheel replay failed for selector', e);
                  }}
                  return false;
                }})();
                """
                ok = await page.evaluate(script)
                if not ok:
                    try:
                        await page.mouse.wheel(dx, dy)
                    except Exception:
                        await page.evaluate(f"window.scrollBy({dx}, {dy})")
            else:
                # No selector available → fallback to page-level scroll
                try:
                    await page.mouse.wheel(dx, dy)
                except Exception:
                    await page.evaluate(f"window.scrollBy({dx}, {dy})")

        # ✅ Handle scrollable element replay (still needed for div.scrollable)
        elif typ == "scrollElement":
            selector = act.get("selector")
            if selector:
                script = f"""
                const el = document.querySelector({json.dumps(selector)});
                if (el) {{
                  el.scrollTo({act['x']}, {act['y']});
                }}
                """
                await page.evaluate(script)

        elif typ == "keyboard":
            try:
                await page.keyboard.press(act["key"])
            except Exception:
                await page.keyboard.insert_text(act["key"])





def ensure_json():
    if not JSON_FILE.exists():
        JSON_FILE.write_text("[]")


def load_json():
    return json.loads(JSON_FILE.read_text())


def save_json(data):
    JSON_FILE.write_text(json.dumps(data, indent=4))


async def select_region(page: Page):
    js_code = """
    () => new Promise(resolve => {
        const overlay = document.createElement('div');
        Object.assign(overlay.style, {
            position: 'fixed', top:0, left:0,
            width:'100%', height:'100%',
            backgroundColor:'rgba(0,0,0,0.3)',
            cursor:'crosshair', zIndex:999999
        });
        document.body.appendChild(overlay);

        let startX, startY, rect;

        function onMouseDown(e){
            startX=e.clientX; startY=e.clientY;
            rect=document.createElement('div');
            Object.assign(rect.style,{
                position:'absolute', border:'2px dashed red',
                backgroundColor:'rgba(255,0,0,0.2)',
                left:`${startX}px`, top:`${startY}px`, zIndex:1000000
            });
            overlay.appendChild(rect);
            overlay.addEventListener('mousemove', onMouseMove);
        }

        function onMouseMove(e){
            rect.style.left=`${Math.min(startX,e.clientX)}px`;
            rect.style.top=`${Math.min(startY,e.clientY)}px`;
            rect.style.width=`${Math.abs(e.clientX-startX)}px`;
            rect.style.height=`${Math.abs(e.clientY-startY)}px`;
        }

        function onMouseUp(e){
            overlay.removeEventListener('mousedown',onMouseDown);
            overlay.removeEventListener('mousemove',onMouseMove);
            overlay.removeEventListener('mouseup',onMouseUp);

            const scrollX=window.scrollX, scrollY=window.scrollY;
            const x=Math.min(startX,e.clientX)+scrollX;
            const y=Math.min(startY,e.clientY)+scrollY;
            const width=Math.abs(e.clientX-startX);
            const height=Math.abs(e.clientY-startY);

            overlay.remove();
            resolve({x,y,width,height});
        }

        overlay.addEventListener('mousedown', onMouseDown);
        overlay.addEventListener('mouseup', onMouseUp);
    })
    """
    return await page.evaluate(js_code)




RECORD_ACTIONS_JS = r"""
async () => {
  if (window._inlineRecorderActive) return 'already';
  window._inlineRecorderActive = true;
  const send = window.recordEventBridge;
  const start = Date.now();
  let lastMove = { x: 0, y: 0, t: 0 };
  let lastScroll = { x: window.scrollX, y: window.scrollY, t: start };

  function emit(type, payload) {
    payload.t = Date.now() - start;
    send({ type, ...payload });
  }

  function uniqueSelector(el) {
    if (!el || !el.tagName) return '';
    const path = [];
    while (el && el.nodeType === Node.ELEMENT_NODE) {
      let selector = el.nodeName.toLowerCase();
      if (el.id) {
        selector += '#' + el.id;
        path.unshift(selector);
        break;
      } else {
        const sibs = Array.from(el.parentNode?.children || []);
        const index = sibs.indexOf(el) + 1;
        selector += `:nth-child(${index})`;
      }
      path.unshift(selector);
      el = el.parentNode;
    }
    return path.join(' > ');
  }

  function onMouseDown(e) { emit('mousedown', { x: e.clientX, y: e.clientY }); }
  function onMouseUp(e)   { emit('mouseup',   { x: e.clientX, y: e.clientY }); }
  function onMouseMove(e) {
    const now = Date.now();
    const dist = Math.abs(e.clientX - lastMove.x) + Math.abs(e.clientY - lastMove.y);
    if (dist > 2 || now - lastMove.t > 40) {
      emit('mousemove', { x: e.clientX, y: e.clientY });
      lastMove = { x: e.clientX, y: e.clientY, t: now };
    }
  }
  function onClick(e) { emit('click', { x: e.clientX, y: e.clientY }); }
  function onKey(e) { emit('keyboard', { key: e.key }); }
  function onWheel(e) {
    emit('wheel', {
      deltaX: e.deltaX,
      deltaY: e.deltaY,
      selector: uniqueSelector(e.target)
    });
  }
  function onScroll() {
    const now = Date.now();
    const x = window.scrollX, y = window.scrollY;
    if ((x !== lastScroll.x || y !== lastScroll.y) && (now - lastScroll.t) > 50) {
      emit('scrollTo', { x, y });
      lastScroll = { x, y, t: now };
    }
  }

  window.addEventListener('mousedown', onMouseDown, true);
  window.addEventListener('mouseup', onMouseUp, true);
  window.addEventListener('mousemove', onMouseMove, true);
  window.addEventListener('scroll', onScroll, true);
  window.addEventListener('click', onClick, true);
  window.addEventListener('keydown', onKey, true);
  window.addEventListener('wheel', onWheel, { passive: true, capture: true });

  window.__stopInlineRecorder = () => {
    window.removeEventListener('mousedown', onMouseDown, true);
    window.removeEventListener('mouseup', onMouseUp, true);
    window.removeEventListener('mousemove', onMouseMove, true);
    window.removeEventListener('scroll', onScroll, true);
    window.removeEventListener('click', onClick, true);
    window.removeEventListener('keydown', onKey, true);
    window.removeEventListener('wheel', onWheel, true);
    window._inlineRecorderActive = false;
  };

  console.log('[Recorder] Started with full mouse + wheel + scroll tracking');
  return 'recording_started';
}
"""








STOP_RECORDING_JS = "() => (window.__stopInlineRecorder ? window.__stopInlineRecorder() : []);"


async def take_screenshot(page: Page, path, clip):
    #dpr = await page.evaluate("window.devicePixelRatio")
    #scaled_clip = {
       # "x": int(clip["x"] * HIGH_RESOLUTION_SCALE),
       # "y": int(clip["y"] * HIGH_RESOLUTION_SCALE),
       # "width": int(clip["width"] * HIGH_RESOLUTION_SCALE),
       # "height": int(clip["height"] * HIGH_RESOLUTION_SCALE)
   # }
    #clip = scaled_clip
    try:
        await page.evaluate(f'window.scrollTo({clip["x"]}, {clip["y"]})')
        await page.screenshot(path=path, clip=clip, scale="device")
        print(f"[SAVED] {path}")
    except Exception as e:
        print(f"[ERROR] Failed to take screenshot {path}: {e}")


async def run_json_editor(context, page: Page, recorded_events_buffer):
    recorded_events_buffer.clear()


    ensure_json()
    data = load_json()
    loop = True

    while loop:
        print("\n[JSON EDITOR]")
        print("1. View entries")
        print("2. Add entry")
        print("3. Remove entry")
        print("4. Edit entry")
        print("5. Go to Main Menu")
        choice = input("Choose: ").strip()

        if choice == "1":
            print(json.dumps(data, indent=4))

        elif choice == "2":
            png_name = input("Enter PNG name: ").strip()
            if not png_name.lower().endswith(".png"):
                 png_name += ".png"
            import re
            png_name = re.sub(r'[<>:"/\\|?*]', '_', png_name)


            print("[INFO] Recording user actions has started... (click, scroll, keys)")
            page, url = await get_current_url(context)
            if not url or url.startswith("about:"):
                print("[ACTION REQUIRED] No URL found in active tabs. Taking single.mcns.io as URL")
                url = "https://single.mcns.io"
                await page.goto(url, wait_until="networkidle", timeout=60000)
                


            #Bring page front and start recording
            await page.bring_to_front()
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_load_state("networkidle")
            await page.evaluate("document.readyState")  # ensure loaded
            await page.goto(url, wait_until="networkidle", timeout=60000)

            status = await page.evaluate(RECORD_ACTIONS_JS)
            recorded_events_buffer.clear()
            print(f"[INFO] Recorder status: {status}")
            print("[ACTION] Interact with the page (click, scroll, type, drag), then press Enter here to stop recording...")
            
            input()
            await page.evaluate("window.__stopInlineRecorder && window.__stopInlineRecorder();")

            print(f"[DEBUG] Stopped recorder; {len(recorded_events_buffer)} events were streamed back.")
            if not recorded_events_buffer:
                print("[WARN] No actions recorded. Did you interact inside the browser tab (not terminal)?")


            # Now recorded[] has all events from browser

            actions = convert_events_to_actions(recorded_events_buffer)
            print(f"[INFO] Recorded {len(recorded_events_buffer)} raw events → {len(actions)} actions")
            logging.info(f"Recorded {len(recorded_events_buffer)} raw events, {len(actions)} actions for {url}")
                
                
                

            #url = page.url or ""
            #if not url:
            #    url = input("Enter URL: ").strip()
            #input("[ACTION] Log in if required, then press Enter to continue...")
            print("[Action required] Click, drag, and release the mouse to select region for screenshot.")
            
            
            def is_approx_default(clip, default, tol=5):
                """Return True if clip is approximately equal to default region (within ±tol pixels)."""
                if not clip:
                    return True
                for key in ("x", "y", "width", "height"):
                    if abs(clip.get(key, 0) - default[key]) > tol:
                        return False
                return True


            DEFAULT_CLIP = {"x": 0, "y": 0, "width": 1280, "height": 715}
            
            clip = await select_region(page)
            
            #After user selects region:
            if not clip or clip.get("width", 0) < 5 or clip.get("height", 0) < 5 or is_approx_default(clip, DEFAULT_CLIP):
                print("[INFO] Using default clip 1280x715 (Standard Fullscreen).")
                clip = DEFAULT_CLIP.copy()



            data.append({"url": url, "png_name": png_name, "clip": clip, "actions": actions})
            save_json(data)
            print(f"[ADDED] {url} → {png_name} with clip {clip}")
            logging.info(f"Added entry {png_name} for URL={url} with clip={clip} and {len(actions)} actions")

        elif choice == "3":
            for i, entry in enumerate(data):
                print(f"{i+1}. {entry['url']} -> {entry.get('png_name','')}")
            idx = int(input("Enter index to remove: ")) - 1
            if 0 <= idx < len(data):
                removed = data.pop(idx)
                save_json(data)
                print(f"[REMOVED] {removed['url']}")
            else:
                print("[ERROR] Invalid index")

        elif choice == "4":
            for i, entry in enumerate(data):
                print(f"{i+1}. {entry.get('png_name','')} -> {entry['url']}")
            idx = int(input("Enter index to edit: ")) - 1

            if 0 <= idx < len(data):
                entry = data[idx]
                print(f"Editing: {entry.get('png_name','')} -> {entry['url']}")

                new_url = input(f"Enter new URL (current: {entry['url']}): ").strip()
                if new_url:
                    entry["url"] = new_url
                    print(f"[SAVED] URL updated to: {entry['url']}")
                else:
                    print("[INFO] URL unchanged.")


                new_png = input(f"Enter new PNG name (current: {entry.get('png_name','')}): ").strip()
                if new_png:
                    if not new_png.lower().endswith(".png"):
                        new_png += ".png"
                    entry["png_name"] = new_png
                    print(f"[SAVED] PNG name updated to: {entry['png_name']}")
                else:
                    print("[INFO] PNG name unchanged.")

                # --- Re-record actions ---
                edit_actions = input("Re-record actions? (y/n): ").strip().lower()
                if edit_actions == "y":
                    print(f"[INFO] Opening {entry['url']} for action recording...")
                    await safe_goto(page, entry['url'])

                    print("[ACTION] Log in if required")
                    if not entry['url'] or entry['url'].startswith("about:"):
                        print("[ACTION REQUIRED] No URL found. Taking single.mcns.io as URL")
                        await page.goto("https://single.mcns.io", wait_until="networkidle", timeout=60000)

                    await page.bring_to_front()
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await page.wait_for_load_state("networkidle")
                    await page.evaluate("document.readyState")
                    recorded_events_buffer.clear()
                    status = await page.evaluate(RECORD_ACTIONS_JS)
                    print(f"[INFO] Recorder status: {status}")
                    print("[ACTION] Interact with the page, then press Enter here to stop recording...")
                    input()
                    await page.evaluate("window.__stopInlineRecorder && window.__stopInlineRecorder();")

                    if not recorded_events_buffer:
                        print("[WARN] No actions recorded.\n Keeping the existing actions.")
                        
                    else:
                        actions = convert_events_to_actions(recorded_events_buffer)
                        entry["actions"] = actions
                        print(f"[INFO] Recorded {len(actions)} actions.")
                        logging.info(f"Re-recorded {len(actions)} actions for {entry['png_name']}")

                edit_clip = input("Edit clip? (y/n): ").strip().lower()
                if edit_clip == "y":
                    print(f"[INFO] Opening {entry['url']} for clip selection...")
                    await safe_goto(page, entry['url'])

                    print("[ACTION] Log in if required, contunuing in 1 second...")
                    clip = await select_region(page)
                    entry["clip"] = clip
                    print(f"[UPDATED] Clip saved: {clip}")


                save_json(data)
                print("[UPDATED] Entry saved")
            else:
                print("[ERROR] Invalid index")

        elif choice == "5":
            return  # Go back to main menu
            loop = False  # Exit program        
        else:
            print("[ERROR] Invalid choice")



async def run_screenshots(page: Page):
    ensure_json()
    data = load_json()
    SCREENSHOT_DIR.mkdir(exist_ok=True)

    

    for file in SCREENSHOT_DIR.glob("*.png"):
        file.unlink()

    for entry in data:
        png_name = entry.get("png_name", "")
        if not png_name.lower().endswith(".png"):
            entry["png_name"] = f"{png_name}.png"
            logging.warning(f"Missing .png extension for {png_name}; fixed automatically.")
    save_json(data)


    print("[INFO] Open the login page if required and log in manually.")
    #input("[ACTION] After logging in, press Enter to continue...")

    for entry in data:
        url = entry.get("url")
        png_name = entry.get("png_name")
        clip = entry.get("clip")

        if not url or not png_name or not clip:
            print(f"[SKIP] Missing URL or PNG in entry: {entry}")
            continue

        print(f"\n Taking {png_name} screenshot for {url} ")
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"[ERROR] Failed to open {url}: {e}")
            continue

        if not png_name.lower().endswith(".png"):
            png_name += ".png"
        path = SCREENSHOT_DIR / png_name


        
        actions = entry.get("actions", [])
        
        if actions:
            print(f"[INFO] Replaying {len(actions)} actions for {entry['png_name']}")
            await replay_actions(page, actions)
        else:
            print(f"[INFO] No recorded actions for {entry['png_name']} — skipping replay.")

        await take_screenshot(page, path, clip)
        #input("[ACTION] Finished, press Enter to continue...")


async def main():
    ensure_json()
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USERDATA_DIR),
            headless=False,
            viewport=None,
            device_scale_factor=HIGH_RESOLUTION_SCALE,
            args=["--start-maximized"]
        )
        page = context.pages[0] if context.pages else await context.new_page()

        recorded_events_buffer = []

        async def record_event(event):
            recorded_events_buffer.append(event)

        await page.expose_function("recordEventBridge", record_event)
        logging.info("recordEventBridge exposed once at startup.")

        while True:
            print("\n[MAIN MENU]")
            print("1. Take screenshots")
            print("2. Edit JSON entries")
            print("3. Exit program")
            choice = input("Choose: ").strip()

            if choice == "1":
                await run_screenshots(page)
            elif choice == "2":
                await run_json_editor(context, page, recorded_events_buffer)
            elif choice == "3":
                break
            else:
                print("[ERROR] Invalid choice")

        await context.close()



if __name__ == "__main__":
    asyncio.run(main())
