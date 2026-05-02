/**
 * AI Intel pin icons — teardrop SVG data URIs per category.
 *
 * These are registered with MapLibre via `map.addImage()` during init and
 * referenced from the ai-intel-pin-layer via the `icon-image` layout prop.
 */

import { PIN_CATEGORY_COLORS, type PinCategory } from '@/types/aiIntel';

/** Classic teardrop pin shape with a white dot in the head. */
function buildPinSvg(color: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="40" height="54" viewBox="0 0 40 54">
  <defs>
    <filter id="s" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="1" stdDeviation="1.5" flood-color="#000" flood-opacity="0.55"/>
    </filter>
  </defs>
  <path filter="url(#s)" d="M20 2 C10 2 2 10 2 20 C2 32 20 52 20 52 C20 52 38 32 38 20 C38 10 30 2 20 2 Z"
        fill="${color}" stroke="#0a0a14" stroke-width="2"/>
  <circle cx="20" cy="20" r="6.5" fill="#ffffff" stroke="#0a0a14" stroke-width="1.25"/>
</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** Map image-id used in the layer's icon-image expression. */
export const pinIconId = (category: PinCategory): string => `ai-pin-${category}`;

/** Generate every category's pin icon as a [id, dataURI] pair. */
export function getAllPinIcons(): Array<[string, string]> {
  return (Object.keys(PIN_CATEGORY_COLORS) as PinCategory[]).map((cat) => [
    pinIconId(cat),
    buildPinSvg(PIN_CATEGORY_COLORS[cat]),
  ]);
}
