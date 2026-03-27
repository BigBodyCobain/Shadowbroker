use reqwest::Method;
use serde_json::Value;

pub async fn call_backend_json(
    base_url: &str,
    admin_key: Option<&str>,
    path: &str,
    method: Method,
    payload: Option<Value>,
) -> Result<Value, String> {
    let client = reqwest::Client::new();
    let mut request = client.request(method, format!("{base_url}{path}"));
    if let Some(key) = admin_key {
        if !key.trim().is_empty() {
            request = request.header("X-Admin-Key", key);
        }
    }
    if let Some(value) = payload {
        request = request.json(&value);
    }
    let response = request
        .send()
        .await
        .map_err(|e| format!("backend_request_failed:{e}"))?;
    let status = response.status();
    let text = response
        .text()
        .await
        .map_err(|e| format!("backend_response_failed:{e}"))?;
    let value: Value = serde_json::from_str(&text).unwrap_or_else(|_| serde_json::json!({}));
    if !status.is_success() || value.get("ok") == Some(&Value::Bool(false)) {
        let detail = value
            .get("detail")
            .and_then(|v| v.as_str())
            .or_else(|| value.get("message").and_then(|v| v.as_str()))
            .unwrap_or("native_control_request_failed");
        return Err(detail.to_string());
    }
    Ok(value)
}
