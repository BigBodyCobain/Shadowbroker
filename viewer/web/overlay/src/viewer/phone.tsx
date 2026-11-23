'use client';

/**
 * Phone layout for the public viewer.
 *
 * The app's panels are built for a wide screen. On a phone the map takes the
 * whole screen and the two side columns become sheets, one at a time.
 *   - Upright: four buttons along the bottom; a sheet slides up over the lower
 *     part of the map.
 *   - On its side: the screen is wide but short, so the buttons run down the
 *     left edge and a sheet opens beside them at full height.
 */

import React, { useEffect, useState } from 'react';
import { Info, Layers, MessagesSquare, Radar } from 'lucide-react';

/** A phone held upright (narrow) or on its side (short). */
export const PHONE_QUERY = '(max-width: 820px), (max-height: 520px)';
/** A phone on its side: wide but very short. */
export const PHONE_LANDSCAPE_QUERY = '(max-height: 520px) and (min-width: 560px)';

/** True on a phone-sized screen. False during the first render, so the server and browser agree. */
export function usePhone(): boolean {
  const [phone, setPhone] = useState(false);
  useEffect(() => {
    const query = window.matchMedia(PHONE_QUERY);
    const update = () => setPhone(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return phone;
}

export type PhoneSheet = 'layers' | 'intel' | null;

/**
 * Scroll a sheet to a marker. A marker with no box of its own stands for the element after it.
 * Only the sheet's own scroll position is changed: scrollIntoView would also move the page behind it.
 */
export function scrollToMarker(id: string): void {
  const marker = document.getElementById(id);
  if (!marker) return;
  const target = getComputedStyle(marker).display === 'contents' ? marker.nextElementSibling : marker;
  const sheet = target?.closest<HTMLElement>('.sb-left-col, .sb-right-col');
  if (!target || !sheet) return;
  sheet.scrollTop += target.getBoundingClientRect().top - sheet.getBoundingClientRect().top - 10;
}

export function PhoneNav({
  open,
  onLayers,
  onIntel,
  onChat,
  onAbout,
}: {
  open: PhoneSheet;
  onLayers: () => void;
  onIntel: () => void;
  onChat: () => void;
  onAbout: () => void;
}) {
  const items: { id: string; label: string; icon: React.ReactNode; active: boolean; onClick: () => void }[] = [
    { id: 'layers', label: 'Layers', icon: <Layers size={19} aria-hidden="true" />, active: open === 'layers', onClick: onLayers },
    { id: 'intel', label: 'Intel', icon: <Radar size={19} aria-hidden="true" />, active: open === 'intel', onClick: onIntel },
    { id: 'chat', label: 'Chat', icon: <MessagesSquare size={19} aria-hidden="true" />, active: false, onClick: onChat },
    { id: 'about', label: 'About', icon: <Info size={19} aria-hidden="true" />, active: false, onClick: onAbout },
  ];
  return (
    <nav className="sb-phone-nav hud-zone" aria-label="Map panels">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          onClick={item.onClick}
          aria-pressed={item.active}
          className={`sb-phone-nav-btn ${item.active ? 'is-active' : ''}`}
        >
          {item.icon}
          <span>{item.label}</span>
        </button>
      ))}
    </nav>
  );
}

/** Phone-only rules. They sit in one place so the desktop layout is untouched. */
export function PhoneStyles() {
  return (
    <style>{`
      .sb-phone-nav { display: none; }
      @media ${PHONE_QUERY} {
        /* brand: one small line at the top */
        .sb-brandbar { top: calc(10px + env(safe-area-inset-top, 0px)) !important; left: 12px !important; gap: 8px !important; }
        .sb-brandbar .sb-brand-mark { width: 26px !important; height: auto !important; }
        .sb-brandbar .sb-wordmark { font-size: 15px !important; letter-spacing: 0.2em !important; line-height: 1.1 !important; }
        .sb-brandbar .sb-wordmark-sub { display: none !important; }

        /* desktop-only furniture */
        .sb-edge, .sb-dock, .sb-scalebar, .sb-alert { display: none !important; }

        /* the two columns become bottom sheets */
        html .sb-left-col, html .sb-right-col {
          left: 0 !important; right: 0 !important; width: auto !important;
          top: 36dvh !important; bottom: calc(58px + env(safe-area-inset-bottom, 0px)) !important;
          padding: 12px 10px 14px !important; gap: 10px !important;
          background: linear-gradient(180deg, rgba(8, 18, 32, 0.97), rgba(4, 10, 20, 0.985));
          border-top: 1px solid rgba(69, 216, 255, 0.34);
          border-radius: 16px 16px 0 0;
          box-shadow: 0 -18px 50px -10px rgba(0, 0, 0, 0.85);
          direction: ltr !important;
          overscroll-behavior: contain;
        }
        html .sb-left-col[data-open='false'], html .sb-right-col[data-open='false'] { pointer-events: none !important; visibility: hidden; }
        .sb-left-col .sb-panel, .sb-right-col .sb-panel { backdrop-filter: none !important; }
        .sb-col-fade { display: none !important; }
        /* inside a sheet the panels take their natural height and the sheet itself scrolls */
        html .sb-left-col [class*='flex-[3.4'] { flex: 0 0 auto !important; min-height: 0 !important; }
        html .sb-left-col [class*='flex-[3.4'] .sb-scroll-fade {
          overflow: visible !important; flex: 0 0 auto !important; max-height: none !important;
          -webkit-mask-image: none !important; mask-image: none !important;
        }
        html .sb-left-col [class*='flex-[2.4'] { flex: 0 0 auto !important; height: 340px; min-height: 0 !important; }

        /* bottom bar */
        .sb-phone-nav {
          display: grid; grid-template-columns: repeat(4, 1fr);
          position: fixed; left: 0; right: 0; bottom: 0; z-index: 320;
          padding: 6px 6px calc(6px + env(safe-area-inset-bottom, 0px));
          background: linear-gradient(180deg, rgba(8, 18, 32, 0.96), rgba(3, 8, 16, 0.99));
          border-top: 1px solid rgba(69, 216, 255, 0.26);
          pointer-events: auto;
        }
        .sb-phone-nav-btn {
          display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
          min-height: 46px; border-radius: 10px; border: 1px solid transparent; background: transparent;
          color: var(--text-muted); font-family: var(--font-mono, monospace); font-size: 10px; font-weight: 700;
          letter-spacing: 0.14em; text-transform: uppercase; -webkit-tap-highlight-color: transparent;
        }
        .sb-phone-nav-btn.is-active { color: #7fdcff; border-color: rgba(69, 216, 255, 0.4); background: rgba(30, 155, 255, 0.14); }

        /* touch: the map owns pinch and drag; sheets only scroll up and down; nothing zooms the page itself */
        .sb-left-col, .sb-right-col { touch-action: pan-y; -webkit-overflow-scrolling: touch; }
        .sb-phone-nav, .sb-brandbar { touch-action: manipulation; }
        /* iPhones zoom the whole page when a small text box is tapped; 16px stops that */
        input, textarea, select { font-size: 16px !important; }

        /* map pop-ups and modals fit the screen */
        .maplibregl-popup { max-width: calc(100vw - 20px) !important; }
        .maplibregl-popup-content { max-width: calc(100vw - 20px) !important; }
        .maplibregl-ctrl-bottom-left, .maplibregl-ctrl-bottom-right { bottom: calc(60px + env(safe-area-inset-bottom, 0px)) !important; }
      }

      /* phone on its side */
      @media ${PHONE_LANDSCAPE_QUERY} {
        .sb-phone-nav {
          top: 0; bottom: 0; right: auto; left: 0;
          width: calc(60px + env(safe-area-inset-left, 0px));
          grid-template-columns: 1fr; grid-auto-rows: 1fr;
          padding: 6px 5px 6px calc(5px + env(safe-area-inset-left, 0px));
          border-top: 0; border-right: 1px solid rgba(69, 216, 255, 0.26);
          background: linear-gradient(90deg, rgba(3, 8, 16, 0.99), rgba(8, 18, 32, 0.96));
        }
        .sb-phone-nav-btn { min-height: 0; font-size: 9px; letter-spacing: 0.1em; }
        html .sb-left-col, html .sb-right-col {
          top: 0 !important; bottom: 0 !important; right: auto !important;
          left: calc(60px + env(safe-area-inset-left, 0px)) !important;
          width: min(400px, 54vw) !important;
          padding: 10px 10px 12px !important;
          border-top: 0; border-right: 1px solid rgba(69, 216, 255, 0.34);
          border-radius: 0 16px 16px 0;
          box-shadow: 18px 0 50px -10px rgba(0, 0, 0, 0.85);
        }
        .sb-brandbar { left: calc(72px + env(safe-area-inset-left, 0px)) !important; }
        .maplibregl-ctrl-bottom-left { bottom: 0 !important; left: calc(60px + env(safe-area-inset-left, 0px)) !important; }
        .maplibregl-ctrl-bottom-right { bottom: 0 !important; }
      }
    `}</style>
  );
}
