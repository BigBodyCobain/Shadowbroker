use reqwest::Method;
use serde_json::Value;

use crate::http_client::call_backend_json;

pub async fn dispatch_control_command(
    backend_base_url: &str,
    admin_key: Option<&str>,
    command: &str,
    payload: Option<Value>,
) -> Result<Value, String> {
    match command {
        "wormhole.status" => {
            call_backend_json(backend_base_url, admin_key, "/api/wormhole/status", Method::GET, None).await
        }
        "wormhole.connect" => {
            call_backend_json(backend_base_url, admin_key, "/api/wormhole/connect", Method::POST, None).await
        }
        "wormhole.disconnect" => {
            call_backend_json(backend_base_url, admin_key, "/api/wormhole/disconnect", Method::POST, None).await
        }
        "wormhole.restart" => {
            call_backend_json(backend_base_url, admin_key, "/api/wormhole/restart", Method::POST, None).await
        }
        "settings.wormhole.get" => {
            call_backend_json(backend_base_url, admin_key, "/api/settings/wormhole", Method::GET, None).await
        }
        "settings.wormhole.set" => {
            call_backend_json(backend_base_url, admin_key, "/api/settings/wormhole", Method::PUT, payload).await
        }
        "settings.privacy.get" => {
            call_backend_json(backend_base_url, admin_key, "/api/settings/privacy-profile", Method::GET, None).await
        }
        "settings.privacy.set" => {
            call_backend_json(backend_base_url, admin_key, "/api/settings/privacy-profile", Method::PUT, payload).await
        }
        "settings.api_keys.get" => {
            call_backend_json(backend_base_url, admin_key, "/api/settings/api-keys", Method::GET, None).await
        }
        "settings.api_keys.set" => {
            call_backend_json(backend_base_url, admin_key, "/api/settings/api-keys", Method::PUT, payload).await
        }
        "settings.news.get" => {
            call_backend_json(backend_base_url, admin_key, "/api/settings/news-feeds", Method::GET, None).await
        }
        "settings.news.set" => {
            call_backend_json(backend_base_url, admin_key, "/api/settings/news-feeds", Method::PUT, payload).await
        }
        "settings.news.reset" => {
            call_backend_json(backend_base_url, admin_key, "/api/settings/news-feeds/reset", Method::POST, None).await
        }
        "system.update" => {
            call_backend_json(backend_base_url, admin_key, "/api/system/update", Method::POST, None).await
        }
        _ => Err(format!("unsupported_control_command:{command}")),
    }
}
