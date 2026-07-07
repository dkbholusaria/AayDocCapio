# TRACES 2.0 Automation Knowledge

Accumulated during Form 168 implementation. Reference this before automating any new TRACES 2.0 form.

---

## Architecture

- URL: `traces.tdscpc.gov.in`
- Auth bridge dashboard: `/auth/authBridge/dashboard?code=...`
- Form 168 screen: `/auth/form26As/form26AsAtsScreen`
- The **form screen is NOT Flutter canvas** — it is a regular HTML page rendered inside a Flutter shell
- The **auth bridge dashboard IS Flutter canvas** (CanvasKit, `flt-renderer="canvaskit"`)
- `flt-glass-pane` has zero bounding rect (`w:0, h:0`) on the form screen
- `elementFromPoint()` returns `FLUTTER-VIEW` for all coordinates on the form screen

---

## Flutter Semantics

- Enable with: `document.querySelector('flt-semantics-placeholder')?.click()`
- Wait 2s after enabling — populates ~67 `flt-semantics` elements
- Only 6 elements have `aria-label` on the Form 168 screen:
  - Logo image
  - Profile icon / Logout
  - Tax Year (group)
  - Dropdown (`'Dropdown Select option , collapsed, opens list'`)
  - Back button
  - Proceed button
- **Radio buttons have NO aria-label** — must use coordinates
- Semantics bounding boxes give accurate pixel positions for clickable elements

---

## Interaction Techniques

### Dashboard card click (Flutter canvas)

Use `page.mouse.move(x, y)` + `page.mouse.click(x, y)`.

Form 168 card position: `x = flutter-view.width × 0.264`, `y = flutter-view.height × 0.405`

Use a retry loop checking URL change (up to 5 attempts, 3s between).

### Dropdown open (Flutter canvas widget)

JS tap on the canvas inside `flt-glass-pane`'s shadow DOM works. `page.mouse.click()` does NOT work for dropdowns.

```js
const gp = document.querySelector('flt-glass-pane');
const target = gp.shadowRoot?.querySelector('canvas') || gp.shadowRoot?.firstElementChild || gp;
const base = { bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, screenX: x, screenY: y };
target.dispatchEvent(new PointerEvent('pointermove', {...base, pointerId:1, pointerType:'touch', isPrimary:true, pressure:0}));
target.dispatchEvent(new PointerEvent('pointerdown', {...base, pointerId:1, pointerType:'touch', isPrimary:true, pressure:1}));
target.dispatchEvent(new MouseEvent('mousedown', {...base, button:0, buttons:1}));
target.dispatchEvent(new PointerEvent('pointerup',  {...base, pointerId:1, pointerType:'touch', isPrimary:true, pressure:0}));
target.dispatchEvent(new MouseEvent('mouseup',  {...base, button:0, buttons:0}));
target.dispatchEvent(new MouseEvent('click',    {...base, button:0, buttons:0}));
```

Get x/y from `flt-semantics[aria-label*='Select option']` bounding box center.

### Dropdown option selection

After opening, a `flt-semantics` element appears with `aria-label` containing `'results available'`. JS-tap the center of its bounding box to select the item.

### Radio buttons

`page.mouse.move(x, y)` + `page.mouse.click(x, y)` — real Playwright mouse events work.  
JS dispatch does **NOT** work for radio buttons.

Confirmed y positions (viewport 1600×900, page not scrolled, x=415):

| Option         | y   |
|----------------|-----|
| View Online    | 430 |
| Download PDF   | 465 |
| Download Excel | 495 |
| Download Text  | 525 |

### Proceed button

JS-tap at the center of `flt-semantics[aria-label*='Proceed']` bounding box (live — reads at runtime so it works even if the form shifts). Fallback: JS tap at (709, 585).

---

## File Downloads

- PDF, Excel, TXT all trigger via `page.expect_download(timeout=60000)`
- Files are **NOT** password-protected and **NOT** zipped (unlike Form 26AS TXT)
- Tax Year selection persists across downloads — select once, then download PDF → Excel → TXT in sequence
- After each download the form returns to the same state — just select a new radio and click Proceed

---

## Viewport

- `screen.width` returns 1600 regardless of `set_viewport_size` calls
- Always call `set_viewport_size(screen.width, screen.height)` before interacting
- All confirmed coordinates above are for 1600×900

---

## Debug Technique: Visual Cursor

To verify click positions visually during development, inject a red dot + coordinate label:

```js
const d = document.createElement('div');
d.id = '_dbg_cursor';
d.style.cssText = 'position:fixed;width:16px;height:16px;background:red;border-radius:50%;pointer-events:none;z-index:999999;transform:translate(-50%,-50%);border:2px solid white;';
const lbl = document.createElement('div');
lbl.id = '_dbg_label';
lbl.style.cssText = 'position:fixed;background:red;color:white;font:bold 13px monospace;padding:2px 5px;pointer-events:none;z-index:999999;border-radius:3px;';
document.body.appendChild(d);
document.body.appendChild(lbl);
window._dbg_move = (x, y) => {
    d.style.left = x + 'px'; d.style.top = y + 'px';
    lbl.style.left = (x + 12) + 'px'; lbl.style.top = (y - 8) + 'px';
    lbl.textContent = x + ',' + y;
};
```

Move with: `window._dbg_move(x, y)` — shows `x,y` label next to the dot on screen.

Use a sweep loop with 3s pauses to find exact coordinates for any unknown element:

```python
for y in range(350, 561, 5):
    await page.evaluate(f"window._dbg_move(415, {y})")
    await asyncio.sleep(3.0)
```
