#Scale4_screenshot.py
# Selected SS


import asyncio
import json
import logging
import getpass
import re
from pathlib import Path
from playwright.async_api import async_playwright, Page
from PIL import Image, ImageChops, ImageOps

JSON_FILE = Path("screenshots.json")
SCREENSHOT_DIR = Path("screenshots")
TEMP_SCREENSHOT_DIR = Path("screenshots_tmp")
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


def log_action(action_type: str, details: str):
    """Standardized logging helper for troubleshooting."""
    logging.info(f"[ACTION] {action_type} | {details}")

def save_json(data):
    JSON_FILE.write_text(json.dumps(data, indent=4))
    log_action("JSON_SAVE", f"File saved with {len(data)} entries → {JSON_FILE.resolve()}")



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


def parse_indices(input_str, total_entries):
    indices = set()
    for part in input_str.split(','):
        part = part.strip()
        if '-' in part:
            try:
                start, end = map(int, part.split('-'))
                indices.update(range(start, end + 1))
            except ValueError:
                print(f"[WARNING] Skipping invalid range: {part}")
        else:
            try:
                indices.add(int(part))
            except ValueError:
                print(f"[WARNING] Skipping invalid entry: {part}")
    # Ensure indices are valid
    return [i for i in sorted(indices) if 1 <= i <= total_entries]


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
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=30000)
        await page.wait_for_timeout(1000)        
        await page.evaluate(f'window.scrollTo({clip["x"]}, {clip["y"]})')
        await asyncio.sleep(2)
        await page.screenshot(path=path, clip=clip, scale="device")
        print(f"[SAVED] {path}")


        with Image.open(path) as img:
            bordered = ImageOps.expand(img, border=5, fill="black")
            bordered.save(path)

        print(f"[UPDATED] Added black borders")


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
            print("\nSaved Entries: ")
            for i, entry in enumerate(data):                
                print(f"{i+1}. {entry.get('png_name','')} -> {entry['url']} -> {len(entry.get('actions',[]))} actions")
            
            try:
                vw_idx = int(input("Enter index to view clip area (0 to skip): ")) - 1
            except ValueError:
                print("\n Invalid input")
                input("\nPress Enter to continue")
                return
            
            if 0 <= vw_idx < len(data):
                clip = data[vw_idx].get("clip", {})
                print("\n Clip area:")
                print(f" x: {clip.get('x',0)}")
                print(f" y: {clip.get('y',0)}")
                print(f" width: {clip.get('width',0)}")
                print(f" height: {clip.get('height',0)}")
            else:
                print("\n Existing...")
                loop = False
            
            
            return


        elif choice == "2":

            while True:
                png_name = input("\nEnter PNG name (or type exit to stop): ").strip()
                if png_name.lower() == "exit" or png_name == "":
                    print("\nStopping entry add mode...")
                    break

                if not png_name.lower().endswith(".png"):
                    png_name += ".png"


                png_name = re.sub(r'[<>:"/\\|?*]', '_', png_name)

                print("[INFO] Recording user actions has started... (click, scroll, keys)")

                page, url = await get_current_url(context)
                if not url or url.startswith("about:"):
                    print("[ACTION REQUIRED] No URL found in active tabs. Taking single.mcns.io as URL")
                    url = "https://single.mcns.io"
                    await page.goto(url, wait_until="networkidle", timeout=60000)

                await page.bring_to_front()
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                await page.wait_for_load_state("networkidle")
                await page.evaluate("document.readyState")
                await page.goto(url, wait_until="networkidle", timeout=60000)

                status = await page.evaluate(RECORD_ACTIONS_JS)
                recorded_events_buffer.clear()
                print(f"[INFO] Recorder status: {status}")
                print("[ACTION] Interact with the page, then press Enter here to stop recording...")

                input()
                await page.evaluate("window.__stopInlineRecorder && window.__stopInlineRecorder();")

                print(f"[DEBUG] Stopped recorder; {len(recorded_events_buffer)} events were recorded.")
                if not recorded_events_buffer:
                    print("[WARN] No actions recorded.")

                actions = convert_events_to_actions(recorded_events_buffer)
                print(f"[INFO] Recorded {len(recorded_events_buffer)} raw events → {len(actions)} actions")
                logging.info(f"Recorded {len(recorded_events_buffer)} raw events, {len(actions)} actions for {url}")

                print("[ACTION REQUIRED] Click and drag to select clip region.")

                DEFAULT_CLIP = {"x": 0, "y": 0, "width": 1280, "height": 715}

                def is_approx_default(clip, default, tol=5):
                    if not clip:
                        return True
                    for key in ("x", "y", "width", "height"):
                        if abs(clip.get(key, 0) - default[key]) > tol:
                            return False
                    return True

                clip = await select_region(page)

                if not clip or clip.get("width", 0) < 5 or clip.get("height", 0) < 5 or is_approx_default(clip, DEFAULT_CLIP):
                    print("[INFO] Using default clip 1280x715.")
                    clip = DEFAULT_CLIP.copy()

                data.append({"url": url, "png_name": png_name, "clip": clip, "actions": actions})
                save_json(data)
                print(f"[ADDED] {png_name} with clip {clip}")
                log_action("JSON_ADD", f"Added entry {png_name} with clip {clip} and {len(actions)} actions")


        elif choice == "3":
            for i, entry in enumerate(data):
                print(f"{i+1}. {entry['url']} -> {entry.get('png_name','')}")
            idx = int(input("Enter index to remove: ")) - 1
            if 0 <= idx < len(data):
                removed = data.pop(idx)
                save_json(data)
                print(f"[REMOVED] {removed['url']}")
                log_action("JSON_REMOVE", f"Removed entry: {removed.get('png_name')} ({removed.get('url')})")
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
                    log_action("JSON_EDIT", f"Updated URL: {entry.get('png_name')} | URL={entry.get('url')} | Clip={entry.get('clip')}")
                else:
                    print("[INFO] URL unchanged.")


                new_png = input(f"Enter new PNG name (current: {entry.get('png_name','')}): ").strip()
                if new_png:
                    if not new_png.lower().endswith(".png"):
                        new_png += ".png"
                    entry["png_name"] = new_png
                    print(f"[SAVED] PNG name updated to: {entry['png_name']}")
                    log_action("JSON_EDIT", f"Updated PNG name: {entry.get('png_name')} | URL={entry.get('url')} | Clip={entry.get('clip')}")
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
                        entry["url"] = "https://single.mcns.io"
                        log_action("JSON_EDIT", f"URL not found: Used default URL with {entry.get('png_name')} | URL={entry.get('url')} | Clip={entry.get('clip')}")

                    await page.bring_to_front()
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await page.wait_for_load_state("networkidle")
                    await page.evaluate("document.readyState")
                    recorded_events_buffer.clear()
                    status = await page.evaluate(RECORD_ACTIONS_JS)
                    print(f"[INFO] Recorder status: {status}\n Wait until the page is fully loaded before interacting.")
                    print("[ACTION] Interact with the page, then press Enter here to stop recording...")
                    input()
                    await page.evaluate("window.__stopInlineRecorder && window.__stopInlineRecorder();")

                    if not recorded_events_buffer:
                        print("[WARN] No actions recorded.\n Keeping the existing actions.")
                        log_action("JSON_EDIT", f"No actions recorded with {entry.get('png_name')} | URL={entry.get('url')} | Clip={entry.get('clip')}")
                        
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
                    log_action("JSON_EDIT", f"Clip area edited with {entry.get('png_name')} | URL={entry.get('url')} | Clip={entry.get('clip')}")


                save_json(data)
                print("[UPDATED] Entry saved")
                log_action("JSON_EDIT", f"JSON updated for {entry.get('png_name')} | URL={entry.get('url')} | Clip={entry.get('clip')}")
            else:
                print("[ERROR] Invalid index")

        elif choice == "5":
            return  # Go back to main menu
            loop = False  # Exit program        
        else:
            print("[ERROR] Invalid choice")



async def run_screenshots(page: Page, entries=None, selection_filter: str = None):
    ensure_json()
    data = load_json()

    # -------------------------------
    # Determine which entries to process
    # -------------------------------
    if selection_filter:
        indices = set()
        for part in selection_filter.split(','):
            part = part.strip()
            if '-' in part:
                try:
                    start, end = map(int, part.split('-'))
                    indices.update(range(start, end + 1))
                except ValueError:
                    print(f"[WARNING] Skippingw invalid range: {part}")
            else:
                try:
                    indices.add(int(part))
                except ValueError:
                    print(f"[WARNING] Skipping invalid index: {part}")

        selected_data = [entry for i, entry in enumerate(data, start=1) if i in indices]
        print(f"[INFO] Selected entries: {sorted(indices)}")
    elif entries is not None:
        selected_data = entries
        print(f"[INFO] Using pre-filtered entries ({len(entries)} total).")
    else:
        selected_data = data
        print("[INFO] No filter applied, processing all entries.")

    # -------------------------------
    # Directory setup and cleanup
    # -------------------------------
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    TEMP_SCREENSHOT_DIR.mkdir(exist_ok=True)
    for file in TEMP_SCREENSHOT_DIR.glob("*.png"):
        file.unlink()

    # -------------------------------
    # Fix missing extensions
    # -------------------------------
    for entry in selected_data:
        png_name = entry.get("png_name", "")
        if not png_name.lower().endswith(".png"):
            entry["png_name"] = f"{png_name}.png"
            logging.warning(f"Missing .png extension for {png_name}; fixed automatically.")
    save_json(data)

    print("[INFO] Open the login page if required and log in manually.")

    # -------------------------------
    # Main screenshot loop
    # -------------------------------
    for entry in selected_data:
        url = entry.get("url")
        png_name = entry.get("png_name")
        clip = entry.get("clip")

        if not url or not png_name or not clip:
            print(f"[SKIP] Missing URL or PNG in entry: {entry}")
            logging.warning(f"Missing URL or PNG name or clip for entry: {entry}; skipping.")
            continue

        print(f"\nTaking {png_name} screenshot for {url}")
        logging.warning(f"Taking screenshot for: {png_name}: {url}")

        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            if "saml_login" in page.url:
                print("[INFO] Redirected to login page. Please log in manually.")
                await page.wait_for_url("**/single.mcns.io/**", timeout=0)
        except Exception as e:
            print(f"[ERROR] Failed to open {url}: {e}")
            logging.warning(f"Failed to open: {url}")
            continue
        if not png_name.lower().endswith(".png"):
            png_name += ".png"  

        path = TEMP_SCREENSHOT_DIR / png_name
        logging.warning(f"png_name saved to TEMP_SCREENSHOT_DIR.")

        actions = entry.get("actions", [])
        if actions:
            print(f"[INFO] Replaying {len(actions)} actions for {png_name}")
            await replay_actions(page, actions)
            logging.warning(f"Replayed {len(actions)} actions for {png_name}")
        else:
            print(f"[INFO] No recorded actions for {png_name} — skipping replay.")
            logging.info(f"No recorded actions for {png_name} — skipping replay.")

        await take_screenshot(page, path, clip)
        logging.info(f"Screenshot taken for {png_name} at {path}")

    await compare_and_prompt(page)
    logging.info("All selected screenshots processed and compared.")




async def compare_and_prompt(page: Page):
    """Compare screenshots one by one, show single browser preview, and ask user in CLI to replace or discard."""

    # Create or reuse one tab for preview
    compare_tab = await page.context.new_page()

    for tmp_file in TEMP_SCREENSHOT_DIR.glob("*.png"):
        main_file = SCREENSHOT_DIR / tmp_file.name

        # If old screenshot doesn’t exist — just move it
        if not main_file.exists():
            tmp_file.replace(main_file)
            print(f"[NEW] Saved new screenshot: {main_file.name}")
            continue

        # Compare old and new
        img1 = Image.open(main_file).convert("RGB")
        img2 = Image.open(tmp_file).convert("RGB")
        diff = ImageChops.difference(img1, img2)

        if diff.getbbox() is None:
            print(f"[NO CHANGE] {main_file.name} — identical, discarding new image.")
            tmp_file.unlink()
            continue

        # Save diff image
        diff_path = TEMP_SCREENSHOT_DIR / f"diff_{tmp_file.name}"
        diff.save(diff_path)

        # Prepare HTML for visual comparison
        html = f"""
<html>
<head>
<style>
  body {{
    background: #222;
    color: #fff;
    font-family: sans-serif;
    text-align: center;
    margin: 0;
    overflow-x: hidden;
  }}
  h2 {{
    color: #ffd700;
    margin-top: 20px;
  }}
  .container {{
    display: flex;
    flex-direction: row;
    justify-content: center;
    align-items: flex-start;
    gap: 20px;
    padding: 20px;
  }}
  .images {{
    flex: 3;
  }}
  .zoom-preview {{
    flex: 1;
    border: 3px solid #555;
    background: #111;
    width: 400px;
    height: 400px;
    overflow: hidden;
    position: sticky;
    top: 50px;
  }}
  .zoom-preview h3 {{
    color: #0ff;
    font-size: 16px;
    margin: 5px 0;
  }}
  img {{
    max-width: 45%;
    border: 3px solid #444;
    margin: 10px;
  }}
</style>
</head>
<body>
<h2>Compare: {tmp_file.name}</h2>

<div class="container">
  <div class="images">
    <div>
      <h3>Old</h3>
      <img id="imgOld" src="file:///{main_file.resolve()}" />
    </div>
    <div>
      <h3>New</h3>
      <img id="imgNew" src="file:///{tmp_file.resolve()}" />
    </div>
    <div>
      <h3>Diff</h3>
      <img id="imgDiff" src="file:///{diff_path.resolve()}" />
    </div>
  </div>

  <div class="zoom-preview" id="zoomBox">
    <h3>Zoom preview</h3>
    <canvas id="zoomCanvas" width="400" height="370"></canvas>
  </div>
</div>

<script>
function enableFixedZoom(imgIDs, zoom = 2) {{
  const zoomCanvas = document.getElementById("zoomCanvas");
  const ctx = zoomCanvas.getContext("2d");
  const zoomBox = document.getElementById("zoomBox");

  imgIDs.forEach(id => {{
    const img = document.getElementById(id);
    img.addEventListener("mousemove", e => showZoom(e, img));
    img.addEventListener("mouseleave", clearZoom);
  }});

  function showZoom(e, img) {{
    const rect = img.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const scaleX = img.naturalWidth / img.width;
    const scaleY = img.naturalHeight / img.height;
    const realX = x * scaleX;
    const realY = y * scaleY;

    const zoomSize = 150;
    const sx = Math.max(0, realX - zoomSize / 2);
    const sy = Math.max(0, realY - zoomSize / 2);
    const sWidth = zoomSize;
    const sHeight = zoomSize;

    const imgElement = new Image();
    imgElement.src = img.src;
    imgElement.onload = () => {{
      ctx.clearRect(0, 0, zoomCanvas.width, zoomCanvas.height);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(
        imgElement,
        sx, sy, sWidth, sHeight,
        0, 0, zoomCanvas.width, zoomCanvas.height
      );
    }};
  }}

  function clearZoom() {{
    ctx.clearRect(0, 0, zoomCanvas.width, zoomCanvas.height);
  }}
}}

enableFixedZoom(["imgOld", "imgNew", "imgDiff"], 2);
</script>

</body>
</html>
"""





        # Write temporary HTML to file
        html_path = TEMP_SCREENSHOT_DIR / f"compare_{tmp_file.stem}.html"
        html_path.write_text(html, encoding="utf-8")

        # Load it in the same tab
        print(f"\n[COMPARE] Showing {tmp_file.name} in browser...")
        await compare_tab.goto(f"file:///{html_path.resolve()}")
        await asyncio.sleep(1)

        # CLI prompt for user decision
        while True:
            choice = input("\nReplace or Discard this screenshot? (r/d): ").strip().lower()
            if choice == "r":
                tmp_file.replace(main_file)
                print(f"[REPLACED] {tmp_file.name}")
                break
            elif choice == "d":
                tmp_file.unlink()
                print(f"[DISCARDED] {tmp_file.name}")
                break
            else:
                print("Invalid input. Please enter 'r' or 'd'.")

    await compare_tab.close()
    print("\n[INFO] All comparisons completed.")






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
            print("3. Take screenshot of the current page")
            print("4. Exit program")
            print("[INFO] Open the login page if required and log in manually.")
            choice = input("\nChoose: ").strip()

            

            if choice == "1":
                print("\n[SCREENSHOT MODE]")
                print("1. Take all screenshots as per JSON")
                print("2. Take selected screenshots from JSON")
                sub_choice = input("\nChoose: ").strip()
                if sub_choice == "1":
                    await run_screenshots(page)
                elif sub_choice == "2":
                    
                    print("\nSaved Entries: ")
                    ensure_json()
                    data = load_json()
                    for i, entry in enumerate(data):                
                        print(f"{i+1}. {entry.get('png_name','')} -> {entry['url']} -> {len(entry.get('actions',[]))} actions")
                    selection = input("Enter indices of entries to screenshot (example: 1,5,7 or 1-3,6,9-10): ")
                    selected_indices = parse_indices(selection, len(data))
                    if not selected_indices:
                        print("[ERROR] No valid indices selected.")
                        continue
                    else:
                        selected_data = [data[i-1] for i in selected_indices]
                    await run_screenshots(page, entries=selected_data, selection_filter=selection)


                
            elif choice == "2":
                await run_json_editor(context, page, recorded_events_buffer)
            elif choice == "3":
                from datetime import datetime
                SCREENSHOT_DIR.mkdir(exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                png_name = input("Enter PNG name for current page screenshot: ").strip()
                if not png_name.lower().endswith(".png"):
                    png_name += ".png" 
                
                path = SCREENSHOT_DIR / png_name
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await asyncio.sleep(1)                    
                    await page.screenshot(path=path, full_page=True, scale="device")

                    with Image.open(path) as img:
                        bordered = ImageOps.expand(img, border=5, fill="black")
                        bordered.save(path)

                    print(f"[SAVED] Full-page screenshot saved as {png_name}")
                    logging.info(f"Captured full-page screenshot: {png_name}")

                except Exception as e:
                    print(f"[ERROR] Failed to take full-page screenshot: {e}")
                    logging.error(f"Failed full-page capture: {e}")
                
            elif choice == "4":
                break
            else:
                print("[ERROR] Invalid choice")

        await context.close()



if __name__ == "__main__":
    asyncio.run(main())
