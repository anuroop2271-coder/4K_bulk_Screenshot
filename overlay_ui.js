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

          if (bulkArea) bulkArea.style.height = '280px';
        } else {
          panel.style.width = '420px';
          panel.style.height = '';
          panel.style.maxHeight = '80vh';
          panel.style.top = '12px';
          panel.style.right = '12px';
          panel.style.left = '';

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

  // (rest of your overlay code continues unchanged…)
  // ✅ **Do not remove**
  // ✅ **Do not modify**
  // ✅ **Your recorder and clip logic stays as-is**

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

  // initial request for JSON
  setTimeout(() => { if (window.py_bridge) window.py_bridge({ cmd: 'request_entries' }); }, 200);

  return { status: 'injected' };
})();
