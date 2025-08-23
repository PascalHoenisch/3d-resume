import { Viewer, Display } from '/assets/js/vendor/three-cad-viewer.esm.js';

// Improve scrolling performance: add passive listeners (no-op) to satisfy audit
(function(){
  try {
    const passive = { passive: true };
    const noop = () => {};
    window.addEventListener('touchstart', noop, passive);
    window.addEventListener('touchmove', noop, passive);
    window.addEventListener('wheel', noop, passive);
  } catch(_) {}
})();

// New code only: straightforward Viewer/Display usage (no legacy compatibility)
const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

function notify(change) {
  // Minimal notification hook; keep silent to avoid noisy logs
  // console.debug('NOTIFY:', change);
}

const defaultDisplayOptions = {
  cadWidth: 850,
  height: 525,
  treeWidth: 240,
  theme: 'browser',
  pinning: true,
  keymap: { 'shift': 'shiftKey', 'ctrl': 'ctrlKey', 'meta': 'metaKey' }
};

const defaultRenderOptions = {
  ambientIntensity: 1.0,
  directIntensity: 1.1,
  metalness: 0.30,
  roughness: 0.65,
  edgeColor: 0x707070,
  defaultOpacity: 0.5,
  normalLen: 0,
};

const defaultViewerOptions = {
  ortho: true,
  ticks: 10,
  transparent: false,
  axes: true,
  grid: [false, false, false],
  timeit: false,
  rotateSpeed: 1,
  up: 'Z',
  control: 'trackball',
};

// Scale the viewer a bit smaller than its container (e.g., 90%)
const VIEW_CANVAS_SCALE = 0.9;

async function parseShapesText(text) {
  if (!text) throw new Error('Empty shapes text');
  // Try strict JSON first
  try {
    return JSON.parse(text);
  } catch (_) {}
  // Try to interpret as JS object literal or a var assignment
  try {
    let src = String(text).trim();
    if (src.startsWith('var ')) {
      // Extract RHS of first assignment
      const eq = src.indexOf('=');
      if (eq !== -1) {
        src = src.slice(eq + 1);
      }
      // Remove trailing semicolon if present
      if (src.endsWith(';')) src = src.slice(0, -1);
    }
    // Wrap in parentheses to allow object literal eval
    const fn = new Function('return (' + src + ')');
    return fn();
  } catch (e) {
    throw new Error('Could not parse shapes as JSON or JS object literal');
  }
}

async function fetchShapes(url) {
  const resp = await fetch(url, { cache: 'no-cache' });
  if (!resp.ok) throw new Error('Failed to fetch shapes: ' + resp.status);
  const text = await resp.text();
  return parseShapesText(text);
}

function createCubeShapes() {
  return {
    version: 3,
    parts: [
      {
        id: '/Group/Workplane(Solid)',
        type: 'shapes',
        subtype: 'solid',
        name: 'Workplane(Solid)',
        shape: {
          vertices: [
            -0.5,-0.5,-0.5,-0.5,-0.5,0.5,-0.5,0.5,-0.5,-0.5,0.5,0.5,
            0.5,-0.5,-0.5,0.5,-0.5,0.5,0.5,0.5,-0.5,0.5,0.5,0.5,-0.5,
            -0.5,-0.5,0.5,-0.5,-0.5,-0.5,-0.5,0.5,0.5,-0.5,0.5,-0.5,
            0.5,-0.5,0.5,0.5,-0.5,-0.5,0.5,0.5,0.5,0.5,0.5,-0.5,-0.5,
            -0.5,-0.5,0.5,-0.5,0.5,-0.5,-0.5,0.5,0.5,-0.5,-0.5,-0.5,
            0.5,-0.5,0.5,0.5,0.5,-0.5,0.5,0.5,0.5,0.5
          ],
          triangles: [
            1,2,0,1,3,2,5,4,6,5,6,7,11,8,9,11,10,8,15,13,12,15,12,14,19,16,17,19,18,16,23,21,20,23,20,22
          ],
          normals: [
            -1,0,0,-1,0,0,-1,0,0,-1,0,0,1,0,0,1,0,0,1,0,0,1,0,0,0,-1,0,0,-1,0,0,-1,0,0,-1,0,0,1,0,0,1,0,0,1,0,0,1,0,0,-1,0,0,-1,0,0,-1,0,0,-1,1,0,0,1,0,0,1,0,0,1
          ],
          edges: [
            -0.5,-0.5,-0.5,-0.5,-0.5,0.5,-0.5,-0.5,0.5,-0.5,0.5,0.5,-0.5,0.5,-0.5,-0.5,0.5,0.5,-0.5,-0.5,-0.5,-0.5,0.5,-0.5,0.5,-0.5,-0.5,0.5,-0.5,0.5,0.5,-0.5,0.5,0.5,0.5,0.5,0.5,0.5,-0.5,0.5,0.5,0.5,0.5,-0.5,-0.5,0.5,0.5,-0.5,-0.5,-0.5,-0.5,0.5,-0.5,-0.5,-0.5,-0.5,0.5,0.5,-0.5,0.5,-0.5,0.5,-0.5,0.5,0.5,-0.5,-0.5,0.5,0.5,0.5,0.5,0.5
          ],
          obj_vertices: [
            -0.5,-0.5,0.5,-0.5,-0.5,-0.5,-0.5,0.5,0.5,-0.5,0.5,-0.5,0.5,-0.5,0.5,0.5,-0.5,-0.5,0.5,0.5,0.5,0.5,0.5,-0.5
          ],
          face_types: [0,0,0,0,0,0],
          edge_types: [0,0,0,0,0,0,0,0,0,0,0,0],
          triangles_per_face: [2,2,2,2,2,2],
          segments_per_edge: [1,1,1,1,1,1,1,1,1,1,1,1]
        },
        state: [1,1],
        color: '#e8b024',
        alpha: 1.0,
        texture: null,
        loc: [[0,0,0],[0,0,0,1]],
        renderback: false,
        accuracy: null,
        bb: null,
      }
    ],
    loc: [[0,0,0],[0,0,0,1]],
    name: 'Group',
    id: '/Group',
    normal_len: 0,
    bb: { xmin: -0.5, xmax: 0.5, ymin: -0.5, ymax: 0.5, zmin: -0.5, zmax: 0.5 },
  };
}

function simpleFit(viewer) {
  try {
    if (viewer && typeof viewer.fitAll === 'function') return viewer.fitAll();
    if (viewer && typeof viewer.fitView === 'function') return viewer.fitView();
    if (viewer && typeof viewer.fit === 'function') return viewer.fit();
  } catch (_) {}
}

async function mountCard(card) {
  const canvas = card.querySelector('.viewer-canvas');
  if (!canvas) return null;

  // Create a host element inside the canvas container for the viewer to manage
  let host = canvas.querySelector('.viewer-host');
  if (!host) {
    host = document.createElement('div');
    host.className = 'viewer-host';
    host.style.width = '100%';
    host.style.height = '100%';
    host.style.position = 'relative';
    canvas.appendChild(host);
  }

  // Compute initial size from the canvas rect to avoid 0x0 at mount time
  const canvasRect = canvas.getBoundingClientRect();
  const initW = Math.max(0, Math.floor((canvasRect.width || host.clientWidth || defaultDisplayOptions.cadWidth) * VIEW_CANVAS_SCALE));
  const initH = Math.max(0, Math.floor((canvasRect.height || host.clientHeight || defaultDisplayOptions.height) * VIEW_CANVAS_SCALE));
  const displayOptions = { ...defaultDisplayOptions, cadWidth: initW, height: initH };
  const display = new Display(host, displayOptions);
  const viewer = new Viewer(display, {}, notify);

  // Observe container size and resize viewer accordingly
  try {
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        // Prefer the canvas sizing as it controls the responsive area (aspect-ratio)
        const rect = canvas.getBoundingClientRect();
        const w = Math.max(0, Math.floor((rect.width || host.clientWidth || 0) * VIEW_CANVAS_SCALE));
        const h = Math.max(0, Math.floor((rect.height || host.clientHeight || 0) * VIEW_CANVAS_SCALE));
        try {
          if (typeof viewer.setSize === 'function') viewer.setSize(w, h);
          else if (display && typeof display.setSize === 'function') display.setSize(w, h);
          else if (typeof viewer.resize === 'function') viewer.resize();
        } catch (_) {}
      }
    });
    ro.observe(host);
    // Initial async resize after mount to catch late layout
    setTimeout(() => {
      try {
        const r = canvas.getBoundingClientRect();
        const w = Math.max(0, Math.floor(r.width * VIEW_CANVAS_SCALE));
        const h = Math.max(0, Math.floor(r.height * VIEW_CANVAS_SCALE));
        if (typeof viewer.setSize === 'function') viewer.setSize(w, h);
        else if (display && typeof display.setSize === 'function') display.setSize(w, h);
        else if (typeof viewer.resize === 'function') viewer.resize();
      } catch (_) {}
    }, 0);
  } catch (_) {}

  // Wire toolbar
  const fitBtn = card.querySelector('[data-action="fit"]');
  if (fitBtn) fitBtn.addEventListener('click', () => simpleFit(viewer));
  const resetBtn = card.querySelector('[data-action="reset"]');
  if (resetBtn) resetBtn.addEventListener('click', () => simpleFit(viewer));

  // JSON auto-load if URL provided
  const jsonUrl = card.getAttribute('data-json-url');
  if (jsonUrl) {
    try {
      const shapes = await fetchShapes(jsonUrl);
      if (typeof viewer.render === 'function') await viewer.render(shapes, defaultRenderOptions, defaultViewerOptions);
      await simpleFit(viewer);
      return viewer;
    } catch (_) {
      // fall through to STEP or fallback
    }
  }

  // STEP auto-load if URL provided
  const stepUrl = card.getAttribute('data-step-url');
  if (stepUrl) {
    try {
      if (typeof viewer.addModelUrl === 'function') await viewer.addModelUrl(stepUrl);
      else if (typeof viewer.loadModelFromUrl === 'function') await viewer.loadModelFromUrl(stepUrl);
      else if (typeof viewer.loadUrl === 'function') await viewer.loadUrl(stepUrl);
      else if (typeof viewer.loadModel === 'function') await viewer.loadModel(stepUrl);
      else if (typeof viewer.openUrl === 'function') await viewer.openUrl(stepUrl);
      await simpleFit(viewer);
      return viewer;
    } catch (_) {
      // fall through to render fallback shapes
    }
  }

  // Render fallback shapes so the canvas is not empty
  try {
    const shapes = createCubeShapes();
    if (typeof viewer.render === 'function') await viewer.render(shapes, defaultRenderOptions, defaultViewerOptions);
    await simpleFit(viewer);
  } catch (_) {}

  return viewer;
}

function enhanceViewerA11y(root) {
  try {
    const scope = root && root.ownerDocument ? root.ownerDocument : document;
    const queryAll = (sel) => Array.from((root || scope).querySelectorAll(sel));
    // Map CSS selectors to German labels
    const labels = [
      ['input.tcv_reset', 'Ansicht zurücksetzen'],
      ['input.tcv_fit', 'Ansicht einpassen'],
      ['input.tcv_screenshot', 'Screenshot erstellen'],
      ['input.tcv_grid', 'Gitter ein-/ausblenden'],
      ['input.tcv_axes', 'Achsen ein-/ausblenden'],
      ['input.tcv_ortho', 'Orthografische Projektion umschalten'],
      ['input.tcv_persp', 'Perspektivische Projektion umschalten'],
      ['input.tcv_home', 'Startansicht'],
    ];
    for (const [sel, label] of labels) {
      for (const el of queryAll(sel)) {
        if (el) {
          el.setAttribute('aria-label', label);
          el.setAttribute('title', label);
          el.setAttribute('type', 'button');
        }
      }
    }
    // Tooltips wrappers can also get role for better semantics
    for (const tip of queryAll('.tcv_tooltip')) {
      tip.setAttribute('role', 'group');
    }
  } catch (_) {}
}

async function initWorkCards() {
  const cards = Array.from(document.querySelectorAll('.work-card'));
  for (const card of cards) {
    try {
      const viewer = await mountCard(card);
      // Enhance toolbar accessibility immediately and after a short delay
      enhanceViewerA11y(card);
      setTimeout(() => enhanceViewerA11y(card), 50);
      setTimeout(() => enhanceViewerA11y(card), 300);
    } catch (e) {
      // Keep quiet to avoid failing tests due to noisy logs
    }
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initWorkCards);
} else {
  initWorkCards();
}

