//! Cross-platform tray / menu-bar background lifecycle.
//!
//! Provides:
//! - System tray icon with Show / Hide / Quit menu
//! - Window close interception (hide to background instead of quit)
//! - Restore from tray on menu action or tray icon click
//!
//! **Close behavior is conditional on tray availability:**
//! - If tray setup succeeds: close hides to background (tray can restore/quit)
//! - If tray setup fails: close behaves normally (app exits)
//! - The user is never stranded with a hidden app and no restore path.
//!
//! Platform behavior:
//! - **Windows**: Tray icon in system notification area. Left-click opens
//!   the menu; "Show ShadowBroker" restores the window. "Quit" exits fully.
//! - **macOS**: Menu bar icon. Click opens menu (macOS convention).
//! - **Linux**: Appindicator tray icon (requires libayatana-appindicator3).
//!   Click opens menu. Behavior depends on the desktop environment —
//!   not all DEs render appindicator icons identically.

use std::sync::atomic::{AtomicBool, Ordering};
use tauri::image::Image;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, TrayIcon, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, CloseRequestApi, Manager};

// ---------------------------------------------------------------------------
// Tray menu item IDs
// ---------------------------------------------------------------------------

pub const MENU_ID_SHOW: &str = "sb_tray_show";
pub const MENU_ID_HIDE: &str = "sb_tray_hide";
pub const MENU_ID_QUIT: &str = "sb_tray_quit";

// ---------------------------------------------------------------------------
// Tray icon generation
// ---------------------------------------------------------------------------

const ICON_SIZE: u32 = 32;

/// Generate a minimal 32x32 RGBA tray icon: a filled teal circle on a
/// transparent background. Avoids requiring external asset files.
pub fn generate_tray_icon_rgba() -> (Vec<u8>, u32, u32) {
    let size = ICON_SIZE;
    let mut rgba = vec![0u8; (size * size * 4) as usize];
    let center = size as f32 / 2.0;
    let radius = center - 2.0;

    for y in 0..size {
        for x in 0..size {
            let dx = x as f32 - center;
            let dy = y as f32 - center;
            let dist = (dx * dx + dy * dy).sqrt();
            let idx = ((y * size + x) * 4) as usize;

            if dist <= radius {
                // Teal/green brand accent
                rgba[idx] = 0x1B; // R
                rgba[idx + 1] = 0xC4; // G
                rgba[idx + 2] = 0x9D; // B
                rgba[idx + 3] = 0xFF; // A
            }
            // Transparent otherwise (already zeroed)
        }
    }
    (rgba, size, size)
}

// ---------------------------------------------------------------------------
// Tray readiness state
// ---------------------------------------------------------------------------

/// Shared atomic flag indicating whether the tray icon was successfully set up.
/// Used by `should_hide_on_close()` to decide whether close should hide to
/// background (tray alive → restore path exists) or quit normally (no tray →
/// hiding would strand the user).
pub static TRAY_READY: AtomicBool = AtomicBool::new(false);

/// Returns `true` if the tray icon is live and the app should hide on close
/// instead of quitting.
pub fn should_hide_on_close() -> bool {
    TRAY_READY.load(Ordering::Relaxed)
}

// ---------------------------------------------------------------------------
// Tray setup
// ---------------------------------------------------------------------------

/// Set up the system tray icon with a Show / Hide / Quit menu.
/// On success, returns the `TrayIcon` handle — the caller **must** retain it
/// for the lifetime of the app (dropping it may unregister the tray icon).
/// Also sets `TRAY_READY` to `true`.
///
/// On failure (e.g. missing appindicator on Linux), returns an error string
/// and `TRAY_READY` remains `false`.
pub fn setup_tray(app: &AppHandle) -> Result<TrayIcon, String> {
    let show_item = MenuItem::with_id(app, MENU_ID_SHOW, "Show ShadowBroker", true, None::<&str>)
        .map_err(|e| format!("tray_menu_show:{e}"))?;
    let hide_item = MenuItem::with_id(app, MENU_ID_HIDE, "Hide to Background", true, None::<&str>)
        .map_err(|e| format!("tray_menu_hide:{e}"))?;
    let separator =
        PredefinedMenuItem::separator(app).map_err(|e| format!("tray_menu_separator:{e}"))?;
    let quit_item = MenuItem::with_id(app, MENU_ID_QUIT, "Quit ShadowBroker", true, None::<&str>)
        .map_err(|e| format!("tray_menu_quit:{e}"))?;

    let menu = Menu::with_items(app, &[&show_item, &hide_item, &separator, &quit_item])
        .map_err(|e| format!("tray_menu_build:{e}"))?;

    let (rgba, width, height) = generate_tray_icon_rgba();
    let icon = Image::new_owned(rgba, width, height);

    let tray = TrayIconBuilder::new()
        .icon(icon)
        .tooltip("ShadowBroker")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| {
            handle_tray_menu_event(app, event.id.as_ref());
        })
        .on_tray_icon_event(|tray, event| {
            // Double-click left button: show window (cross-platform convenience)
            if let TrayIconEvent::DoubleClick {
                button: MouseButton::Left,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        })
        .build(app)
        .map_err(|e| format!("tray_build:{e}"))?;

    TRAY_READY.store(true, Ordering::Relaxed);
    Ok(tray)
}

// ---------------------------------------------------------------------------
// Menu event handling
// ---------------------------------------------------------------------------

fn handle_tray_menu_event(app: &AppHandle, id: &str) {
    match id {
        MENU_ID_SHOW => show_main_window(app),
        MENU_ID_HIDE => hide_main_window(app),
        MENU_ID_QUIT => app.exit(0),
        _ => {}
    }
}

// ---------------------------------------------------------------------------
// Window lifecycle
// ---------------------------------------------------------------------------

/// Show, unminimize, and focus the main window.
pub fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

/// Hide the main window to the background.
pub fn hide_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
}

/// Handle a window close request. Behavior depends on tray availability:
/// - **Tray alive** (`should_hide_on_close()` = true): prevent close, hide to
///   background. The user can restore via tray menu or quit via "Quit ShadowBroker".
/// - **No tray** (`should_hide_on_close()` = false): allow the close to proceed
///   normally so the app exits. Never strand the user with a hidden window and
///   no visible restore path.
pub fn handle_close_requested(window: &tauri::Window, api: &CloseRequestApi) {
    if window.label() == "main" && should_hide_on_close() {
        api.prevent_close();
        let _ = window.hide();
    }
    // If tray is not ready or window is not "main", close proceeds normally.
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn icon_rgba_has_correct_dimensions() {
        let (rgba, w, h) = generate_tray_icon_rgba();
        assert_eq!(w, ICON_SIZE);
        assert_eq!(h, ICON_SIZE);
        assert_eq!(rgba.len(), (w * h * 4) as usize);
    }

    #[test]
    fn icon_center_pixel_is_opaque_teal() {
        let (rgba, w, _h) = generate_tray_icon_rgba();
        let center = w / 2;
        let idx = ((center * w + center) * 4) as usize;
        // R=0x1B, G=0xC4, B=0x9D, A=0xFF
        assert_eq!(rgba[idx], 0x1B);
        assert_eq!(rgba[idx + 1], 0xC4);
        assert_eq!(rgba[idx + 2], 0x9D);
        assert_eq!(rgba[idx + 3], 0xFF);
    }

    #[test]
    fn icon_corner_pixel_is_transparent() {
        let (rgba, _w, _h) = generate_tray_icon_rgba();
        // Top-left corner (0,0) should be transparent
        assert_eq!(rgba[0], 0); // R
        assert_eq!(rgba[1], 0); // G
        assert_eq!(rgba[2], 0); // B
        assert_eq!(rgba[3], 0); // A
    }

    #[test]
    fn menu_ids_are_distinct() {
        assert_ne!(MENU_ID_SHOW, MENU_ID_HIDE);
        assert_ne!(MENU_ID_SHOW, MENU_ID_QUIT);
        assert_ne!(MENU_ID_HIDE, MENU_ID_QUIT);
    }

    #[test]
    fn menu_ids_are_namespaced() {
        // All IDs should be prefixed to avoid collisions
        assert!(MENU_ID_SHOW.starts_with("sb_tray_"));
        assert!(MENU_ID_HIDE.starts_with("sb_tray_"));
        assert!(MENU_ID_QUIT.starts_with("sb_tray_"));
    }

    #[test]
    fn should_hide_reflects_tray_ready_state() {
        // Reset to known state
        TRAY_READY.store(false, Ordering::Relaxed);
        assert!(
            !should_hide_on_close(),
            "should not hide when tray is not ready"
        );

        TRAY_READY.store(true, Ordering::Relaxed);
        assert!(should_hide_on_close(), "should hide when tray is ready");

        // Clean up for other tests
        TRAY_READY.store(false, Ordering::Relaxed);
    }

    #[test]
    fn tray_ready_default_is_false() {
        // TRAY_READY is initialized to false — if no tray setup runs,
        // close should behave normally (no stranding).
        // Note: other tests may have mutated TRAY_READY, so we verify
        // the semantic contract via should_hide_on_close after explicit reset.
        TRAY_READY.store(false, Ordering::Relaxed);
        assert!(!should_hide_on_close());
    }
}
