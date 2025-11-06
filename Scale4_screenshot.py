# browser_screenshots_ui.py
"""
Browser-based screenshot manager using Playwright page injection.

Features:
- Browser overlay UI injected into single.mcns.io
- Record mouse/keyboard/scroll/drag actions
- Select clip rectangle by dragging
- Add / edit / delete entries in-browser
- Bulk add / bulk delete
- Take screenshots (replay actions, wait for networkidle)
- Compare by hash, replace only when changed
- Save entries to screenshots.json
- Log to screenshot_log.txt
"""

import asyncio
import json
import hashlib
import logging
import time
import getpass
from pathlib import Path
from typing import List, Dict, Any
from playwright.async_api import async_playwright, Page

# ---------- settings ----------
JSON_FILE = Path("screenshots.json")
SCREENSHOT_DIR = Path("screenshots")
USERDATA_DIR = Path("./userdata")
LOG_FILE = Path("screenshot_log.txt")
HIGH_RESOLUTION_SCALE = 4  # deviceScaleFactor for Chromium context
TARGET_URL = "https://single.mcns.io/"  # constant URL as requested
TARGET_HOST = "single.mcns.io"  # overlay will be active on any sub-URL of this host
# -------------------------------

# logging
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

username_filter = UsernameFilter()
logger = logging.getLogger()
# attach the filter to all handlers that exist now
for handler in logger.handlers:
    handler.addFilter(username_filter)



def ensure_json():
    if not JSON_FILE.exists():
        JSON_FILE.write_text("[]")
        logging.info("Created baseline JSON file %s", JSON_FILE)


def load_json() -> List[Dict[str, Any]]:
    ensure_json()
    try:
        return json.loads(JSON_FILE.read_text())
    except Exception as e:
        logging.error("Failed to load JSON: %s", e)
        return []


def save_json(data: List[Dict[str, Any]]):
    JSON_FILE.write_text(json.dumps(data, indent=4))
    logging.info("Saved JSON file %s (entries=%d)", JSON_FILE, len(data))
    # On every save also attempt to update UI by returning the data (handled by caller)


# helper for hashing files
def file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


async def take_screenshot_and_compare(page: Page, path: Path, clip: Dict[str, int]):
    """
    Take a screenshot (to a temp file), compare hash with existing file, replace only if changed.
    clip is expected as {x,y,width,height} in CSS pixels relative to full document.
    We scroll to the clip top-left before capture and then use a viewport-relative clip.
    """
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # scroll to top-left of clip for stable capture (clip x,y are document coords)
    try:
        await page.evaluate("window.scrollTo(arguments[0], arguments[1])", clip.get("x", 0), clip.get("y", 0))
    except Exception:
        pass
    await asyncio.sleep(0.25)

    # create a viewport-relative clip after scrolling: x=0,y=0,width,height
    clip_for_viewport = {
        "x": 0,
        "y": 0,
        "width": int(clip.get("width", 0)),
        "height": int(clip.get("height", 0)),
    }

    tmp_path = path.with_suffix(".tmp.png")
    # Playwright expects path to exist as string and clip as ints
    await page.screenshot(path=str(tmp_path), clip=clip_for_viewport, scale="device")
    logging.info("Captured temp screenshot %s", tmp_path.name)

    prev_hash = file_sha256(path) if path.exists() else ""
    new_hash = file_sha256(tmp_path)

    logging.info("Compare prev=%s new=%s for %s", prev_hash, new_hash, path.name)

    if prev_hash and prev_hash == new_hash:
        tmp_path.unlink(missing_ok=True)
        logging.info("No visual change for %s", path.name)
        return False, new_hash, prev_hash
    else:
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
        tmp_path.rename(path)
        logging.info("Saved screenshot %s", path.name)
        return True, new_hash, prev_hash



# ---------- JS overlay for UI & recorder ----------
# The overlay exposes functions for:
# - show UI panel with list, add, edit, record actions, select clip, take screenshot commands.
# - it uses window.__sendToPython(payload) to send messages back which are handled by page.expose_binding.
# We define the UI code as a single string and inject it.
OVERLAY_JS = r"""
(() => {
  if (window._screenshotUIInjected) return { status: 'already' };
  window._screenshotUIInjected = true;

  // helper to create elements quickly
  function el(tag, attrs = {}, children = []) {
    const e = document.createElement(tag);
    for (const k in attrs) {
      if (k === 'style') Object.assign(e.style, attrs[k]);
      else e.setAttribute(k, attrs[k]);
    }
    for (const c of children) {
      if (typeof c === 'string') e.appendChild(document.createTextNode(c));
      else e.appendChild(c);
    }
    return e;
  }

// ----- PANEL WITH DRAG + MIN/MAX/CLOSE -----
const panel = el('div',{
  id: 'overlay-root',
  style: {
    position: 'fixed',
    top: '12px',
    right: '12px',
    width: '420px',
    maxHeight: '80vh',
    overflow: 'auto',
    zIndex: 2147483647,
    background: 'rgba(32,34,37,0.95)',
    color: '#e6edf3',
    borderRadius: '8px',
    padding: '10px',
    fontFamily: 'Arial, sans-serif',
    boxShadow: '0 6px 18px rgba(0,0,0,0.4)',
    userSelect: 'none',
    cursor: 'move'
  }});

// Title + window controls row
const titleBar = el('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems:'center', marginBottom:'6px' }});

const title = el('div', { style: { fontWeight: '700', fontSize: '14px', cursor:'grab' }}, ['Screenshot Manager']);

const controlButtons = el('div', { style:{ display:'flex', gap:'6px' }}, [
  (function(){
    const b = el('button', {}, ['_']);
    b.title = 'Minimize';
    b.onclick = () => {
    panel.style.display = 'none';
    restoreBtn.style.display = '';
    window._overlayMinimized = true;
    window.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && e.key === 'S') {
    panel.style.display = '';
    window._overlayMinimized = false;
    }
    }, { once: true });
    };

    return b;
  })(),
  (function(){
    const b = el('button', {}, ['□']);
    let maximized = false;
    b.onclick = () => {
    maximized = !maximized;
    const bulkArea = document.getElementById('bulk-json-area');
    
    if(maximized){
    panel.style.top = '0px';
    panel.style.left = '0px';
    panel.style.right = '0px';
    panel.style.width = '100vw';
    panel.style.height = '100vh';
    panel.style.maxHeight = '100vh';

    // Increase bulk JSON text box height
    if (bulkArea) bulkArea.style.height = '280px';
    } else {
    panel.style.width = '420px';
    panel.style.height = '';
    panel.style.maxHeight = '80vh';
    panel.style.top = '12px';
    panel.style.right = '12px';
    panel.style.left = '';
    
    // Restore original height
    if (bulkArea) bulkArea.style.height = '80px';
    }
    };

    return b;
  })(),
  (function(){
    const b = el('button', {}, ['X']);
    b.title = 'Close Overlay';
    b.onclick = () => { panel.remove(); window._screenshotUIInjected = false; };
    return b;
  })()
]);

titleBar.appendChild(title);
titleBar.appendChild(controlButtons);
panel.appendChild(titleBar);

// DRAG MOVE LOGIC
let isDragging = false, offsetX = 0, offsetY = 0;

titleBar.onmousedown = (e) => {
  isDragging = true;
  offsetX = e.clientX - panel.offsetLeft;
  offsetY = e.clientY - panel.offsetTop;
  titleBar.style.cursor = 'grabbing';
};

document.onmouseup = () => { isDragging = false; titleBar.style.cursor = 'grab'; };

document.onmousemove = (e) => {
  if (!isDragging) return;
  panel.style.left = (e.clientX - offsetX) + 'px';
  panel.style.top = (e.clientY - offsetY) + 'px';
  panel.style.right = 'auto';
};



  // control row
  const controls = el('div', { style: { display: 'flex', gap: '6px', marginBottom: '8px' }});
  const btnTakeAll = el('button', { style: { flex: '1' }}, ['Take all screenshots']);
  const btnExport = el('button', { style: { flex: '1' }}, ['Export JSON']);
  controls.appendChild(btnTakeAll);
  controls.appendChild(btnExport);
  panel.appendChild(controls);

  // add / bulk area
  const addRow = el('div', { style: { marginBottom: '8px', display: 'flex', gap: '6px' }});
  const txtName = el('input', { type: 'text', placeholder: 'screenshot name (no .png)', style: { flex: '1', padding: '6px' }});
  const btnAdd = el('button', {}, ['Add new']);
  addRow.appendChild(txtName);
  addRow.appendChild(btnAdd);
  panel.appendChild(addRow);

  const bulkLabel = el('div', { style: { fontSize: '12px', opacity: '0.8', marginBottom: '4px' }}, ['Bulk JSON (paste array):']);
  const bulkArea = el('textarea', { id: 'bulk-json-area', style: { width: '100%', height: '80px', padding: '6px', fontSize: '12px' }});
  const bulkRow = el('div', { style: { display: 'flex', gap: '6px', marginTop: '6px' }});
  const btnBulkAdd = el('button', {}, ['Bulk add']);
  const btnBulkDelete = el('button', {}, ['Bulk delete']);
  bulkRow.appendChild(btnBulkAdd); bulkRow.appendChild(btnBulkDelete);
  panel.appendChild(bulkLabel); panel.appendChild(bulkArea); panel.appendChild(bulkRow);

  // entries list container
  const list = el('div', { style: { marginTop: '10px' }});
  panel.appendChild(list);

  // status / log area
  const status = el('div', { style: { marginTop: '8px', fontSize: '12px', opacity: '0.9' }}, ['Status: ready']);
  panel.appendChild(status);

  // helper to send message to Python
  async function send(msg) {
    try {
      if (window.py_bridge) {
        // call the python binding injected by playwright
        window.py_bridge(msg);
      } else {
        console.warn('py_bridge not available', msg);
      }
    } catch (err) {
      console.error('send error', err, msg);
    }
  }

  // render entries (called when Python pushes current JSON)
  window.__renderEntries = function(entries) {
    list.innerHTML = '';
    if (!entries || !entries.length) {
      list.appendChild(el('div', { style: { color: '#bbb', fontSize: '13px' } }, ['No entries']));
      return;
    }
    for (let i = 0; i < entries.length; ++i) {
      const e = entries[i];
      const row = el('div', { style: { padding: '6px', borderBottom: '1px solid rgba(255,255,255,0.03)', display: 'flex', gap: '8px', alignItems: 'center' }});
      const info = el('div', { style: { flex: '1' }});
      const titleLine = el('div', {}, [ `${i+1}. ${e.png_name}.png` ]);
      const urlLine = el('div', { style: { fontSize: '12px', color: '#cbd5e1' }}, [ e.url ]);
      info.appendChild(titleLine); info.appendChild(urlLine);
      const btns = el('div', { style: { display: 'flex', gap: '6px' }});
      const btnRecord = el('button', {}, ['Record']);
      const btnReclip = el('button', {}, ['Re-clip']);
      const btnEdit = el('button', {}, ['Edit']);
      const btnDelete = el('button', {}, ['Delete']);
      const btnTake = el('button', {}, ['Take']);
      btns.appendChild(btnTake); btns.appendChild(btnRecord); btns.appendChild(btnReclip); btns.appendChild(btnEdit); btns.appendChild(btnDelete);
      row.appendChild(info); row.appendChild(btns);
      list.appendChild(row);

      // click handlers
      btnRecord.onclick = async () => {
        status.textContent = `Status: recording actions for ${e.png_name}. Click Start in overlay then interact.`;
        // notify Python to show in-page recorder overlay and capture; python will send back events then update UI
        await send({ cmd: 'record_actions_for_index', index: i });
      };
      btnReclip.onclick = async () => {
        status.textContent = `Status: re-clip for ${e.png_name}`;
        await send({ cmd: 'reclip_index', index: i });
      };
      btnEdit.onclick = async () => {
        status.textContent = `Status: edit entry ${e.png_name}`;
        await send({ cmd: 'edit_index', index: i });
      };
      btnDelete.onclick = async () => {
        if (!confirm('Delete this entry?')) return;
        await send({ cmd: 'delete_index', index: i });
      };
      btnTake.onclick = async () => {
        status.textContent = `Status: taking screenshot for ${e.png_name}`;
        await send({ cmd: 'take_index', index: i });
      };
    }
  };

  // top controls callbacks
  btnAdd.onclick = async () => {
    const name = txtName.value.trim();
    if (!name) {
      alert('Enter screenshot name (no .png)');
      return;
    }
    status.textContent = 'Status: creating new entry and starting record...';
    await send({ cmd: 'add_new', png_name: name });
  };

  btnExport.onclick = async () => {
    // ask python to send the JSON string back to UI; python will call window.__receiveJSONExport(text)
    await send({ cmd: 'export_json' });
    status.textContent = 'Status: exported JSON to clipboard (or displayed)';
  };

  btnTakeAll.onclick = async () => {
    status.textContent = 'Status: taking screenshots for all entries...';
    await send({ cmd: 'take_all' });
  };

  btnBulkAdd.onclick = async () => {
    const text = bulkArea.value.trim();
    if (!text) { alert('Paste JSON array into the textarea'); return; }
    let parsed;
    try { parsed = JSON.parse(text); }
    catch (err) { alert('Invalid JSON'); return; }
    await send({ cmd: 'bulk_add', items: parsed });
  };

  btnBulkDelete.onclick = async () => {
    if (!confirm('Delete all entries from JSON? This cannot be undone')) return;
    await send({ cmd: 'bulk_delete' });
  };

  // helper to create a small recording overlay inside the page for user interaction
  window.__showInlineRecorder = async function() {
    // If there is already a recorder, return a handle
    if (window._inlineRecorderActive) return { status: 'already' };

    return new Promise((resolve) => {
      window._inlineRecorderActive = true;
      const recorderBar = el('div', { style: {
        position: 'fixed', left: '50%', transform: 'translateX(-50%)', top: '10px',
        zIndex: 2147483647, background: 'rgba(0,0,0,0.85)', color: '#fff',
        padding: '8px 12px', borderRadius: '8px', fontFamily: 'sans-serif', display: 'flex', gap: '8px', alignItems: 'center'
      }});
      const startBtn = el('button', {}, ['Start']);
      const stopBtn = el('button', {}, ['Stop']);
      const hint = el('span', { style: { fontSize: '13px', opacity: '0.9' }}, ['Idle']);
      recorderBar.appendChild(startBtn); recorderBar.appendChild(stopBtn); recorderBar.appendChild(hint);
      document.body.appendChild(recorderBar);

      const events = [];
      let recording = false;
      let lastScroll = { x: window.scrollX, y: window.scrollY, t: Date.now() };

      function clickHandler(e) {
        // ignore clicks on the recorder itself
        if (recorderBar.contains(e.target)) return;
        events.push({ type: 'click', x: e.clientX, y: e.clientY, t: Date.now() });
      }
      function scrollHandler() {
        const now = Date.now(), x = window.scrollX, y = window.scrollY;
        if ((x !== lastScroll.x || y !== lastScroll.y) && (now - lastScroll.t) > 80) {
          events.push({ type: 'scroll', x: x, y: y, t: now });
          lastScroll = { x, y, t: now };
        }
      }
      // mousemove for drag events (we also capture mousedown/mouseup)
      function mouseDownHandler(e) {
        if (recorderBar.contains(e.target)) return;
        events.push({ type: 'mousedown', x: e.clientX, y: e.clientY, t: Date.now() });
      }
      function mouseUpHandler(e) {
        if (recorderBar.contains(e.target)) return;
        events.push({ type: 'mouseup', x: e.clientX, y: e.clientY, t: Date.now() });
      }
      function keyHandler(e) {
        // do not capture modifier-only keys excessively, only capture key presses
        events.push({ type: 'keyboard', key: e.key, t: Date.now() });
      }

      startBtn.onclick = () => {
        if (recording) return;
        recording = true; hint.textContent = 'Recording...';
        window.addEventListener('click', clickHandler, true);
        window.addEventListener('scroll', scrollHandler, true);
        window.addEventListener('mousedown', mouseDownHandler, true);
        window.addEventListener('mouseup', mouseUpHandler, true);
        window.addEventListener('keydown', keyHandler, true);
      };

      stopBtn.onclick = () => {
        if (!recording) return;
        recording = false; hint.textContent = 'Stopping...';
        window.removeEventListener('click', clickHandler, true);
        window.removeEventListener('scroll', scrollHandler, true);
        window.removeEventListener('mousedown', mouseDownHandler, true);
        window.removeEventListener('mouseup', mouseUpHandler, true);
        window.removeEventListener('keydown', keyHandler, true);
        setTimeout(() => {
          recorderBar.remove();
          window._inlineRecorderActive = false;
          // send events to Python by calling py_bridge
          window.py_bridge({ cmd: 'record_finished', events: events });
          resolve({ status: 'ok', events: events });
        }, 120);
      };

      // keyboard shortcuts
      window.addEventListener('keydown', (ev) => {
        if (ev.ctrlKey && ev.shiftKey && ev.key === 'S') startBtn.click();
        if (ev.ctrlKey && ev.shiftKey && ev.key === 'E') stopBtn.click();
      });
    });
  };

  // clip selector (drag overlay) - returns clip rect {x,y,width,height}
  window.__selectClip = async function() {
    return new Promise((resolve) => {
      const overlayPanel = document.getElementById('overlay-root');
      if (overlayPanel) overlayPanel.style.display = 'none';

      const overlay = el('div', {
        style: {
          position: 'fixed',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          cursor: 'crosshair',
          zIndex: 2147483646,
          backgroundColor: 'rgba(0,0,0,0.06)',
        }
      });
      document.body.appendChild(overlay);

      let startX = 0, startY = 0, box = null;

      function down(ev) {
        startX = ev.clientX;
        startY = ev.clientY;
        box = el('div', {
          style: {
            position: 'absolute',
            border: '2px dashed #ff5c5c',
            background: 'rgba(255,92,92,0.12)',
            left: startX + 'px',
            top: startY + 'px',
            zIndex: 2147483647,
          }
        });
        overlay.appendChild(box);
        window.addEventListener('mousemove', move);
      }

      function move(ev) {
        const x = Math.min(startX, ev.clientX);
        const y = Math.min(startY, ev.clientY);
        const w = Math.abs(ev.clientX - startX);
        const h = Math.abs(ev.clientY - startY);
        Object.assign(box.style, {
          left: x + 'px',
          top: y + 'px',
          width: w + 'px',
          height: h + 'px'
        });
      }

      
      function cleanup() {
      window.removeEventListener('mousemove', move);
  window.removeEventListener('mouseup', up);
  overlay.remove();
  const panel = document.getElementById('overlay-root');
  if (panel) {
  panel.style.display = '';     // show overlay again
  panel.style.visibility = '';  // ensure visible
  panel.style.opacity = '1';    // ensure visible
  }
  }

      function up(ev) {
        cleanup();
        const scrollX = window.scrollX, scrollY = window.scrollY;
        const x = Math.min(startX, ev.clientX) + scrollX;
        const y = Math.min(startY, ev.clientY) + scrollY;
        const width = Math.max(1, Math.abs(ev.clientX - startX));
        const height = Math.max(1, Math.abs(ev.clientY - startY));
        resolve({ x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) });
      }

      window.addEventListener('mousedown', down);
      window.addEventListener('mouseup', up);

      // Cancel with Escape
      window.addEventListener('keydown', function onEsc(e) {
        if (e.key === 'Escape') {
          window.removeEventListener('keydown', onEsc);
          cleanup();
          resolve(null);
        }
      });
    });
  };




  // receives commands from Python to update UI status or show JSON export
  window.__receiveFromPython = function(payload) {
    if (!payload) return;
    if (payload.type === 'entries') {
      window.__renderEntries(payload.entries || []);
      status.textContent = `Status: ${payload.info || 'ready'}`;
    } else if (payload.type === 'export') {
      // show export in popup
      const w = window.open('', '_blank', 'width=700,height=500');
      w.document.write('<pre style="white-space:pre-wrap;font-family:monospace;">' + (payload.text || '') + '</pre>');
      status.textContent = 'Status: exported JSON in new tab';
    } else if (payload.type === 'status') {
      status.textContent = `Status: ${payload.text}`;
    }
  };

  document.body.appendChild(panel);

  // create restore button (hidden by default)
const restoreBtn = el('div', {
  id: 'overlay-restore',
  style: {
    position: 'fixed',
    bottom: '12px',
    right: '12px',
    padding: '6px 10px',
    background: 'rgba(32,34,37,0.9)',
    color: '#e6edf3',
    borderRadius: '6px',
    fontFamily: 'Arial, sans-serif',
    cursor: 'pointer',
    zIndex: 2147483647,
    display: 'none'
  }
}, ['Screenshot panel']);

document.body.appendChild(restoreBtn);

restoreBtn.onclick = () => {
  panel.style.display = '';
  restoreBtn.style.display = 'none';
  window._overlayMinimized = false;
};





  window.__hideOverlayTemporarily = async function(ms = 2000) {
    const overlayPanel = document.getElementById('overlay-root');
    if (!overlayPanel) return;
    overlayPanel.style.display = 'none';
    setTimeout(() => { overlayPanel.style.display = ''; }, ms);
  };


  // initial request to Python to send entries
  setTimeout(() => { if (window.py_bridge) window.py_bridge({ cmd: 'request_entries' }); }, 200);

  return { status: 'injected' };
})();
"""


async def inject_overlay_if_target(page: Page):
    from urllib.parse import urlparse
    try:
        url = page.url or ""
        hostname = (urlparse(url).hostname or "").lower()

        if hostname.endswith(TARGET_HOST):
            # Load overlay BEFORE CSP blocks it
            try:
                await page.add_init_script(OVERLAY_JS)
            except Exception:
                pass

            # Now run overlay (safe because code already exists in page context)
            try:
                await page.evaluate(
                    "(() => { if(!window._screenshotUIInjected){ " + OVERLAY_JS + " } })()"
                )
            except Exception:
                pass

            await push_entries_to_ui(page, info="Overlay active")

            logging.info(f"[Overlay] Active on {hostname}")

    except Exception as e:
        logging.warning(f"[Overlay] Inject failed: {e}")



# ---------- Python-side handlers for messages from UI ----------
# We'll expose a binding 'py_bridge' that JS calls as window.py_bridge(payload)
# The handler will receive payloads like:
# { cmd: 'request_entries' }
# { cmd: 'add_new', png_name: 'name' }
# { cmd: 'record_actions_for_index', index: 0 }
# { cmd: 'reclip_index', index: 0 }
# { cmd: 'edit_index', index: 0 }  -> we will do record + clip + allow name change
# { cmd: 'delete_index', index: 0 }
# { cmd: 'take_index', index: 0 }
# { cmd: 'take_all' }
# { cmd: 'export_json' }
# { cmd: 'bulk_add', items: [...] }
# { cmd: 'bulk_delete' }
# { cmd: 'record_finished', events: [...] }  -> from inline recorder with payload including events
#
# The handler will perform actions and then push updated entries back to the UI via page.evaluate("window.__receiveFromPython(...)").

# utilities to send entries to page UI
async def push_entries_to_ui(page: Page, info: str = "ready"):
    data = load_json()
    payload = {"type": "entries", "entries": data, "info": info}
    try:
        # call the in-page function with the payload as argument
        await page.evaluate("window.__receiveFromPython && window.__receiveFromPython(arguments[0])", payload)
    except Exception as e:
        logging.warning("Failed to push entries to UI: %s", e)

async def export_json_to_ui(page: Page):
    data = load_json()
    text = json.dumps(data, indent=2)
    payload = {"type": "export", "text": text}
    try:
        await page.evaluate("window.__receiveFromPython && window.__receiveFromPython(arguments[0])", payload)
    except Exception as e:
        logging.warning("Failed to export JSON to UI: %s", e)


# replay events recorded by the inline recorder
def convert_recorded_events_to_actions(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert raw events captured in the page to a concise action list.
    Raw events contain: click (x,y), scroll (x,y), mousedown, mouseup, keyboard, t timestamp.
    We convert to sequence of wait / click / scrollTo / keyboard.
    """
    if not events:
        return []
    # sort by timestamp
    events_sorted = sorted(events, key=lambda e: e.get("t", 0))
    actions = []
    last_t = events_sorted[0].get("t", int(time.time() * 1000))
    for ev in events_sorted:
        t = ev.get("t", last_t)
        delta = int(t - last_t)
        if delta > 40:
            actions.append({"type": "wait", "ms": delta})
        typ = ev.get("type")
        if typ == "click":
            actions.append({"type": "click", "x": int(ev.get("x", 0)), "y": int(ev.get("y", 0))})
        elif typ == "scroll":
            actions.append({"type": "scrollTo", "x": int(ev.get("x", 0)), "y": int(ev.get("y", 0))})
        elif typ == "mousedown":
            # mousedown + mouseup often combine into drag; we record them as clicks at positions
            actions.append({"type": "mousedown", "x": int(ev.get("x", 0)), "y": int(ev.get("y", 0))})
        elif typ == "mouseup":
            actions.append({"type": "mouseup", "x": int(ev.get("x", 0)), "y": int(ev.get("y", 0))})
        elif typ == "keyboard":
            actions.append({"type": "keyboard", "key": ev.get("key")})
        last_t = t
    return actions


async def replay_actions_on_page(page: Page, actions: List[Dict[str, Any]]):
    """
    Replay actions on page using Playwright mouse/keyboard.
    Coordinates recorded are CSS pixels relative to viewport; we need to adjust for DPR when clicking via page.mouse.
    We'll query devicePixelRatio and scale coordinates by DPR when calling page.mouse.
    """
    if not actions:
        return
    dpr = await page.evaluate("window.devicePixelRatio")
    for act in actions:
        typ = act.get("type")
        if typ == "wait":
            await asyncio.sleep(act.get("ms", 0) / 1000.0)
        elif typ == "click":
            x = int(act.get("x", 0)); y = int(act.get("y", 0))
            # click uses viewport coordinates; first ensure scroll position is accounted for
            # recorded coordinates are clientX/Y; page.mouse.click expects coordinates relative to viewport
            try:
                await page.mouse.click(x, y)
            except Exception:
                # fallback: evaluate JS to click element at point
                await page.evaluate(f"""
                    (x,y) => {{
                        const evt = new MouseEvent('click', {{ clientX: x, clientY: y, bubbles:true }});
                        const el = document.elementFromPoint(x, y);
                        if (el) el.dispatchEvent(evt);
                    }}
                """, x, y)
        elif typ == "scrollTo":
            x = int(act.get("x", 0)); y = int(act.get("y", 0))
            try:
                await page.evaluate(f'window.scrollTo({x},{y})')
            except Exception:
                pass
            await asyncio.sleep(0.25)
        elif typ == "mousedown":
            x = int(act.get("x", 0)); y = int(act.get("y", 0))
            try:
                await page.mouse.move(x, y)
                await page.mouse.down()
            except Exception:
                pass
        elif typ == "mouseup":
            x = int(act.get("x", 0)); y = int(act.get("y", 0))
            try:
                await page.mouse.move(x, y)
                await page.mouse.up()
            except Exception:
                pass
        elif typ == "keyboard":
            key = act.get("key")
            # For simple key presses use page.keyboard.press
            try:
                await page.keyboard.press(key)
            except Exception:
                # as fallback, type the key as text when suitable
                try:
                    await page.keyboard.insertText(key)
                except Exception:
                    pass
        else:
            # unknown action
            await asyncio.sleep(0.05)


# ---------- binding handler ----------
async def setup_bindings(page: Page):
    """
    Expose Python function `py_bridge` to the page. JS overlay calls window.py_bridge({...}).
    """
    async def _handle_binding(source, payload):
        # payload is expected to be a dict with 'cmd' and other fields
        cmd = payload.get("cmd")
        logging.info("UI command from page: %s", cmd)
        # We respond to many commands; many operations will update JSON and push entries back to UI
        if cmd == "request_entries":
            # send entries back
            await push_entries_to_ui(page)
            return {"status": "ok"}
        elif cmd == "export_json":
            await export_json_to_ui(page)
            return {"status": "ok"}
        elif cmd == "add_new":
            page._pending_new_name = payload.get("png_name")
            await page.goto(TARGET_URL, wait_until="networkidle")
            await page.evaluate("window.__showInlineRecorder && window.__showInlineRecorder()")
            await page.evaluate("window.__receiveFromPython && window.__receiveFromPython({type:'status', text:'Recording... Click Stop when done'})")
            return {"status": "record_started"}

        elif cmd == "record_finished":
            # raw events come here after inline recorder stops
            events = payload.get("events", [])
            logging.info("Recorded %d raw events", len(events))
            # convert events to actions
            actions = convert_recorded_events_to_actions(events)
            # store actions temporarily on the page object in a variable for subsequent clip selection or entry creation
            # we cannot store on python page across calls conveniently; but we can write to a file or in-memory map.
            # For simplicity, create a temp file with timestamp to hold actions
            stamp = int(time.time() * 1000)
            tmpname = f".last_record_{stamp}.json"
            Path(tmpname).write_text(json.dumps(actions))
            logging.info("Saved temporary recorded actions %s", tmpname)
            # Ask UI to start clip selection
            await page.evaluate("window.__receiveFromPython", {"type": "status", "text": "Recording finished. Please select clip area now."})
            # call clip selector
            clip = await page.evaluate("window.__selectClip && window.__selectClip()")
            if not isinstance(clip, dict):
                clip = {"x": 0, "y": 0, "width": 0, "height": 0}
            # load actions from tmp file
            try:
                actions_loaded = json.loads(Path(tmpname).read_text())
            except Exception:
                actions_loaded = actions
            # create an entry with placeholder name; the UI will ask for a name on next step - but since UI triggered recording,
            # we need to create an entry skeleton and then push to UI so user may edit the name, or we can ask the UI to prompt.
            # Simpler path: ask user (via prompt window) for name now.
            name = getattr(page, "_pending_new_name", None)

            if not name:
                name = await page.evaluate("(t,d)=>prompt(t,d)", "Enter screenshot name (no .png):", f"screenshot_{stamp}")
                page._pending_new_name = None                
            entry = {"url": TARGET_URL, "png_name": name, "clip": clip, "actions": actions_loaded}
            data = load_json()
            data.append(entry)
            save_json(data)
            logging.info("Added entry %s with recorded actions and clip", name)
            await push_entries_to_ui(page, info=f"Added {name}")
            # remove tmp
            try:
                Path(tmpname).unlink()
            except Exception:
                pass
            return {"status": "entry_added", "name": name}
        elif cmd == "reclip_index":
            idx = int(payload.get("index", -1))
            data = load_json()
            if 0 <= idx < len(data):
                # go to page, replay actions to set state, then select clip
                entry = data[idx]
                await page.goto(entry.get("url", TARGET_URL), wait_until="networkidle")
                # replay actions if present
                await replay_actions_on_page(page, entry.get("actions", []))
                # wait for network idle and small settle
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                await page.evaluate("window.__receiveFromPython", {"type": "status", "text": f"Select clip for {entry.get('png_name')}"})
                # call clip selector
                clip = await page.evaluate("window.__selectClip && window.__selectClip()")
                # force overlay to reappear after clip
                await page.evaluate("""(() => {const p = document.getElementById('overlay-root');
                                    if (p) {
                                    p.style.display = '';
                                    p.style.visibility = 'visible';
                                    p.style.opacity = '1';
                                    p.style.pointerEvents = 'auto';
                                    }
                                    })();
                                    """)


                if isinstance(clip, dict):
                    entry["clip"] = clip
                    data[idx] = entry
                    save_json(data)
                    await push_entries_to_ui(page, info=f"Updated clip for {entry.get('png_name')}")
                    return {"status": "reclip_ok"}
            return {"status": "reclip_failed"}
        elif cmd == "record_actions_for_index":
            idx = int(payload.get("index", -1))
            data = load_json()
            if 0 <= idx < len(data):
                entry = data[idx]
                await page.goto(entry.get("url", TARGET_URL), wait_until="networkidle")
                # show inline recorder and capture events (record_finished will handle creation)
                await page.evaluate("window.__showInlineRecorder && window.__showInlineRecorder()")
                # we expect record_finished to be called automatically by the inline recorder which triggers this binding
                return {"status": "recording_started_for_index", "index": idx}
            return {"status": "invalid_index"}
        elif cmd == "edit_index":
            idx = int(payload.get("index", -1))
            data = load_json()
            if 0 <= idx < len(data):
                entry = data[idx]
                # navigate and prefill with entry state, then re-record actions and optionally re-clip and change name
                await page.goto(entry.get("url", TARGET_URL), wait_until="networkidle")
                # ask user for new name via prompt
                new_name = await page.evaluate("(text, defaultVal) => prompt(text, defaultVal)",
                                               "Edit screenshot name (leave blank to keep):",
                                               entry.get("png_name", ""))

                if new_name and new_name.strip():
                    entry["png_name"] = new_name.strip()
                # record actions
                await page.evaluate("window.__showInlineRecorder && window.__showInlineRecorder()")
                # wait for record_finished; when that fires we will create tmp file and then continue
                # But easier: after record finish, we expectname = await page.evaluate("() => prompt('Enter screenshot name (no .png) for the recorded entry:','screenshot')") record_finished handler to add new temp file; we check for that.
                # For deterministic flow, indicate to user to re-clip after recording
                await page.evaluate("window.__receiveFromPython", {'type': 'status', 'text': 'After recording, you will be prompted to pick new clip.'})
                # We rely on record_finished to create entry; to keep this simple we will pause here and let record_finished handler create a new entry
                # but we want to update the current entry rather than create new: simplest approach: after record_finished, user can manually delete old entry and rename new.
                # A more advanced in-place update flow could be added later.
                return {"status": "edit_started", "index": idx}
            return {"status": "invalid_index"}
        elif cmd == "delete_index":
            idx = int(payload.get("index", -1))
            data = load_json()
            if 0 <= idx < len(data):
                removed = data.pop(idx)
                save_json(data)
                await push_entries_to_ui(page, info=f"Removed {removed.get('png_name')}")
                logging.info("Removed entry: %s", removed.get("png_name"))
                return {"status": "deleted"}
            return {"status": "invalid_index"}
        elif cmd == "take_index":
            idx = int(payload.get("index", -1))
            data = load_json()
            if 0 <= idx < len(data):
                entry = data[idx]
                # navigate, replay actions, wait for networkidle, then take screenshot and compare
                await page.goto(entry.get("url", TARGET_URL), wait_until="networkidle")
                await asyncio.sleep(0.5)
                await replay_actions_on_page(page, entry.get("actions", []))
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                await asyncio.sleep(0.3)
                clip = entry.get("clip")
                if not clip or clip.get("width", 0) == 0 or clip.get("height", 0) == 0:
                    # fallback to full page
                    path = SCREENSHOT_DIR / f"{entry.get('png_name')}.png"
                    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(path), full_page=True, scale="device")
                    logging.info("Saved full-page screenshot for %s", entry.get("png_name"))
                    await push_entries_to_ui(page, info=f"Saved full-page {entry.get('png_name')}")
                    return {"status": "taken_full"}
                else:
                    path = SCREENSHOT_DIR / f"{entry.get('png_name')}.png"
                    await page.evaluate("window.__hideOverlayTemporarily && window.__hideOverlayTemporarily(2000)")
                    changed, new_hash, prev_hash = await take_screenshot_and_compare(page, path, clip)
                    if changed:
                        await push_entries_to_ui(page, info=f"Updated {entry.get('png_name')}")
                    else:
                        await push_entries_to_ui(page, info=f"No change for {entry.get('png_name')}")
                    return {"status": "taken", "changed": changed}
            return {"status": "invalid_index"}
        elif cmd == "take_all":
            data = load_json()
            updated = []
            for i, entry in enumerate(data):
                # reuse take_index logic
                await page.goto(entry.get("url", TARGET_URL), wait_until="networkidle")
                await asyncio.sleep(0.3)

                try:
                    await page.add_script_tag(content=OVERLAY_JS)
                    await page.evaluate("() => window.__initOverlay && window.__initOverlay()")
                except Exception as e:
                    logging.warning("Failed to reinject overlay after navigation: %s", e)

                await replay_actions_on_page(page, entry.get("actions", []))
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                await asyncio.sleep(0.2)
                clip = entry.get("clip")
                path = SCREENSHOT_DIR / f"{entry.get('png_name')}.png"
                if not clip or clip.get("width", 0) == 0 or clip.get("height", 0) == 0:
                    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(path), full_page=True, scale="device")
                    updated.append(path.name)
                    logging.info("Saved full-page for %s", entry.get("png_name"))
                else:
                    await page.evaluate("window.__hideOverlayTemporarily && window.__hideOverlayTemporarily(1000)")
                    changed, new_hash, prev_hash = await take_screenshot_and_compare(page, path, clip)
                    if changed:
                        updated.append(path.name)
            await push_entries_to_ui(page, info=f"Take all done. updated={len(updated)}")
            return {"status": "take_all_done", "updated": updated}
        elif cmd == "bulk_add":
            items = payload.get("items", [])
            data = load_json()
            appended = 0
            for it in items:
                if isinstance(it, dict) and it.get("png_name"):
                    # normalize required fields
                    entry = {
                        "url": it.get("url", TARGET_URL),
                        "png_name": it.get("png_name"),
                        "clip": it.get("clip", {"x": 0, "y": 0, "width": 0, "height": 0}),
                        "actions": it.get("actions", []),
                    }
                    data.append(entry)
                    appended += 1
            save_json(data)
            await push_entries_to_ui(page, info=f"Bulk added {appended} entries")
            return {"status": "bulk_added", "count": appended}
        elif cmd == "bulk_delete":
            save_json([])
            await push_entries_to_ui(page, info="All entries deleted")
            return {"status": "bulk_deleted"}
        else:
            logging.warning("Unknown command from UI: %s", cmd)
            return {"status": "unknown"}
    # expose binding
    await page.expose_binding("py_bridge", _handle_binding)


#main function
async def main():
    ensure_json()
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USERDATA_DIR),
            headless=False,
            viewport=None,
            device_scale_factor=HIGH_RESOLUTION_SCALE,
            args=["--start-maximized"],
        )

        # ensure we attach handlers for new pages/popups so overlay is injected there too
        async def on_new_page(new_page):
            # small delay for the page to have a URL in some cases
            await asyncio.sleep(0.15)
            await inject_overlay_if_target(new_page)

            # setup bindings on the new page as well
            try:
                await setup_bindings(new_page)
            except Exception as e:
                logging.warning("Failed to setup bindings on new page: %s", e)

            # listen for navigation/frame changes on this page to re-inject overlay if needed
            def _frame_nav_handler(frame):
                # schedule injection asynchronously
                asyncio.create_task(inject_overlay_if_target(new_page))

            new_page.on("framenavigated", _frame_nav_handler)
            new_page.on("load", lambda: asyncio.create_task(inject_overlay_if_target(new_page)))

        # attach to existing pages
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        # ensure bindings on the initial page
        try:
            await setup_bindings(page)
        except Exception as e:
            logging.warning("Failed to setup bindings on initial page: %s", e)

        # inject overlay on initial page if it matches target host
        try:
            await inject_overlay_if_target(page)
        except Exception as e:
            logging.warning("Initial injection attempt failed: %s", e)

        # listen for newly opened pages/popups and inject overlay there
        context.on("page", lambda new_page: asyncio.create_task(on_new_page(new_page)))

        # also watch for navigations on the initial page to re-inject if navigation goes to a sub-URL
        page.on("framenavigated", lambda frame: asyncio.create_task(inject_overlay_if_target(page)))
        page.on("load", lambda: asyncio.create_task(inject_overlay_if_target(page)))

        # push entries to UI (if overlay already available it will render)
        try:
            await push_entries_to_ui(page)
        except Exception:
            pass

        print("Navigate to single.mcns.io to see the Screenshot Manager.")
        # keep process open until user closes
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
