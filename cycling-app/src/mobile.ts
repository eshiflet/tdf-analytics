// Mobile layout, everything behind a single 767px breakpoint.
//
// THE DESKTOP GUARANTEE. Every rule this adds lives inside one
// `@media (max-width: 767px)` block, and everything this module does is gated
// on `MOBILE.matches`. Above the breakpoint nothing here runs and no rule here
// applies, so the desktop rendering is unchanged by construction rather than
// by careful avoidance.
//
// WHY NOT DETECT THE DEVICE. There is no server — this is a static site on
// GitHub Pages — so user-agent branching is not available even in principle.
// It would also be wrong: an iPad reports desktop Safari, and a narrow desktop
// window has the same layout problem a phone does. The viewport is the thing
// that actually breaks, so the viewport is what we test.
//
// WHY THE SIDEBAR IS REUSED RATHER THAN REBUILT. The rider panel holds a
// search box, team and nation filter dropdowns, four quick-select buttons and
// a legend of up to ~200 rows, all wired to selection state. A separate mobile
// widget would need its own copy of every one of those and would drift the
// first time somebody changed one and forgot the other. So the same DOM is
// moved into a sheet: no duplicated logic, and a fix to the filters fixes both.

// matchMedia is not universal: the pre-push smoke tests load this bundle in
// Node against a DOM shim that does not implement it, and calling it at module
// scope took the whole app down at import — caught by the hook rather than in
// review. Where it is missing, "is this a phone?" has no answer, and the right
// answer is no: the desktop layout is the one that works without JS help.
const MOBILE: MediaQueryList | null =
  typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(max-width: 767px)")
    : null;

function isMobile(): boolean {
  return MOBILE?.matches ?? false;
}

let toggleBtn: HTMLButtonElement | null = null;
let backdrop: HTMLDivElement | null = null;

function sidebar(): HTMLElement | null {
  return document.getElementById("sidebar");
}

/** Is the rider panel meaningful right now? main.ts already hides it outside
 *  the stage view and in table mode, and the sheet must not offer a button
 *  that opens an empty panel. */
function sidebarAvailable(): boolean {
  const el = sidebar();
  return !!el && !el.classList.contains("hidden");
}

function closeSheet(): void {
  document.body.classList.remove("sheet-open");
  toggleBtn?.setAttribute("aria-expanded", "false");
}

function openSheet(): void {
  document.body.classList.add("sheet-open");
  toggleBtn?.setAttribute("aria-expanded", "true");
  // Focus the search box: on a phone the reason for opening this is almost
  // always to find one rider.
  (document.getElementById("search") as HTMLInputElement | null)?.focus();
}

function ensureChrome(): void {
  if (toggleBtn) return;

  toggleBtn = document.createElement("button");
  toggleBtn.id = "sheet-toggle";
  toggleBtn.type = "button";
  toggleBtn.textContent = "Riders";
  toggleBtn.setAttribute("aria-controls", "sidebar");
  toggleBtn.setAttribute("aria-expanded", "false");
  toggleBtn.addEventListener("click", () =>
    document.body.classList.contains("sheet-open") ? closeSheet() : openSheet());

  backdrop = document.createElement("div");
  backdrop.id = "sheet-backdrop";
  backdrop.addEventListener("click", closeSheet);

  document.body.append(backdrop, toggleBtn);

  // Escape closes it, which costs nothing and is what a sheet should do.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("sheet-open")) closeSheet();
  });
}

/** Call after any view change: the button must disappear when the rider panel
 *  is not the thing on screen, and the sheet must not stay open across a
 *  navigation. */
export function syncMobileChrome(): void {
  if (!isMobile()) {
    closeSheet();
    document.body.classList.remove("is-mobile");
    return;
  }
  ensureChrome();
  document.body.classList.add("is-mobile");
  const show = sidebarAvailable();
  if (toggleBtn) toggleBtn.hidden = !show;
  if (!show) closeSheet();
}

export function initMobile(): void {
  syncMobileChrome();
  // Rotation and desktop-window resizing both cross the breakpoint.
  MOBILE?.addEventListener("change", syncMobileChrome);
}
