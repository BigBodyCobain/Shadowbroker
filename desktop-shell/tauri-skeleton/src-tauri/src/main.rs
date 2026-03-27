mod bridge;
mod handlers;
mod http_client;

use bridge::invoke_local_control;

pub struct DesktopAppState {
    pub backend_base_url: String,
    pub admin_key: Option<String>,
}

fn main() {
    let backend_base_url =
        std::env::var("SHADOWBROKER_BACKEND_URL").unwrap_or_else(|_| "http://127.0.0.1:8000".to_string());
    let admin_key = std::env::var("SHADOWBROKER_ADMIN_KEY").ok();

    tauri::Builder::default()
        .manage(DesktopAppState {
            backend_base_url,
            admin_key,
        })
        .invoke_handler(tauri::generate_handler![invoke_local_control])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                let script = r#"
                    window.__SHADOWBROKER_DESKTOP__ = {
                      invokeLocalControl: (command, payload) =>
                        window.__TAURI__.core.invoke('invoke_local_control', { command, payload })
                    };
                "#;
                let _ = window.eval(script);
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("failed to run shadowbroker tauri shell");
}
