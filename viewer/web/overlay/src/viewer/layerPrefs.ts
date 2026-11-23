/**
 * Which layer switches the viewer keeps in the visitor's browser.
 *
 * Switches the viewer never shows are forced off on screen. They must not be
 * saved that way: if such a layer is published later, a saved "off" that the
 * visitor never chose would keep it dark for everyone who had visited before.
 *
 * No imports, so the rules can be tested without a browser.
 */

/** Raise when a layer moves from hidden to shown; the list below says which. */
export const VIEWER_LAYER_REV = 2;
export const VIEWER_LAYER_REV_KEY = 'sb_viewer_layer_rev';

/**
 * Layers that were hidden in an earlier viewer build and are shown now.
 * Browsers that saved switches under an older build get the default back for
 * these, once.
 */
export const VIEWER_RESTORED_LAYERS: readonly string[] = ['cctv', 'kiwisdr', 'scanners', 'sigint_aprs'];

type Switches = Record<string, boolean>;

/** The switches as shown: anything the viewer hides is off. */
export function withHiddenOff<T extends object>(layers: T, hidden: ReadonlySet<string>): T {
  const next = { ...layers } as Switches;
  for (const key of hidden) {
    if (key in next) next[key] = false;
  }
  return next as T;
}

/** The switches as saved: hidden ones are left out, so they fall back to the default. */
export function layersToStore<T extends object>(layers: T, hidden: ReadonlySet<string>): T {
  const next = { ...layers } as Switches;
  for (const key of hidden) delete next[key];
  return next as T;
}

/** The switches on page load, from the defaults and whatever this browser saved. */
export function layersOnLoad<T extends object>(
  defaults: T,
  saved: T,
  hidden: ReadonlySet<string>,
  savedRev: number,
  restored: readonly string[] = VIEWER_RESTORED_LAYERS,
): T {
  const next = { ...saved } as Switches;
  if (!(savedRev >= VIEWER_LAYER_REV)) {
    const base = defaults as Switches;
    for (const key of restored) {
      if (key in base) next[key] = base[key];
    }
  }
  return withHiddenOff(next as T, hidden);
}

export function readLayerRev(): number {
  try {
    return Number(localStorage.getItem(VIEWER_LAYER_REV_KEY)) || 0;
  } catch {
    return 0;
  }
}

export function writeLayerRev(): void {
  try {
    localStorage.setItem(VIEWER_LAYER_REV_KEY, String(VIEWER_LAYER_REV));
  } catch {
    /* private mode */
  }
}
