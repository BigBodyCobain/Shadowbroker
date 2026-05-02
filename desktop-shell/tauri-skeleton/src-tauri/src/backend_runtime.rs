use std::fmt::Write as _;
use std::fs;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

const RESOURCE_DIR_NAME: &str = "backend-runtime";
const INSTALL_DIR_NAME: &str = "managed-backend";
const BUNDLE_VERSION_FILE: &str = ".bundle-version";
const PERSISTENT_NAMES: &[&str] = &[".env", "data"];
const RELEASE_ATTESTATION_RELATIVE_PATH: &[&str] = &["data", "release_attestation.json"];
const GENERATED_SECRET_BYTES: usize = 32;

struct ManagedBackendSecrets {
    admin_key: String,
}

struct ManagedSecretSpec {
    key: &'static str,
    min_len: usize,
}

struct ManagedBoolDefaultSpec {
    key: &'static str,
    default_value: bool,
    preserve_non_default: bool,
}

pub struct ManagedBackendHandle {
    child: Option<Child>,
    base_url: String,
    admin_key: String,
}

impl ManagedBackendHandle {
    pub fn base_url(&self) -> &str {
        &self.base_url
    }

    pub fn admin_key(&self) -> Option<&str> {
        if self.admin_key.is_empty() {
            None
        } else {
            Some(self.admin_key.as_str())
        }
    }
}

impl Drop for ManagedBackendHandle {
    fn drop(&mut self) {
        if let Some(child) = self.child.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

pub fn bundled_backend_root(resource_dir: &Path) -> Option<PathBuf> {
    let candidate = resource_dir.join(RESOURCE_DIR_NAME);
    if candidate.join("main.py").exists() {
        Some(candidate)
    } else {
        None
    }
}

pub async fn ensure_and_start_managed_backend(
    bundled_root: PathBuf,
    app_local_data_dir: PathBuf,
    desired_admin_key: Option<String>,
) -> Result<ManagedBackendHandle, String> {
    let runtime_root = install_bundled_backend(&bundled_root, &app_local_data_dir)?;
    let python_bin = resolve_python_bin(&runtime_root)?;
    let port = reserve_loopback_port()?;
    let base_url = format!("http://127.0.0.1:{port}");
    let data_dir = runtime_root.join("data");
    fs::create_dir_all(&data_dir).map_err(|e| format!("managed_backend_data_dir_failed:{e}"))?;
    let secrets = ensure_env_file(&runtime_root, desired_admin_key)?;

    let stdout_log = data_dir.join("backend_stdout.log");
    let stderr_log = data_dir.join("backend_stderr.log");
    let stdout = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&stdout_log)
        .map_err(|e| format!("managed_backend_stdout_log_failed:{e}"))?;
    let stderr = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&stderr_log)
        .map_err(|e| format!("managed_backend_stderr_log_failed:{e}"))?;

    let mut child = Command::new(&python_bin)
        .current_dir(&runtime_root)
        .arg("-m")
        .arg("uvicorn")
        .arg("main:app")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .arg("--timeout-keep-alive")
        .arg("120")
        .env("PYTHONUNBUFFERED", "1")
        .env("SB_DATA_DIR", data_dir.as_os_str())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(stderr))
        .spawn()
        .map_err(|e| format!("managed_backend_spawn_failed:{e}"))?;

    wait_for_backend_ready(&base_url, &mut child).await?;

    Ok(ManagedBackendHandle {
        child: Some(child),
        base_url,
        admin_key: secrets.admin_key,
    })
}

fn install_bundled_backend(
    bundled_root: &Path,
    app_local_data_dir: &Path,
) -> Result<PathBuf, String> {
    let install_root = app_local_data_dir.join(INSTALL_DIR_NAME);
    let bundled_version = read_trimmed_file(&bundled_root.join(BUNDLE_VERSION_FILE))?;
    let installed_version = read_trimmed_file_optional(&install_root.join(BUNDLE_VERSION_FILE));
    let should_sync = !install_root.join("main.py").exists()
        || installed_version.as_deref() != Some(bundled_version.as_str());

    if should_sync {
        fs::create_dir_all(&install_root)
            .map_err(|e| format!("managed_backend_install_dir_failed:{e}"))?;
        sync_runtime_tree(bundled_root, &install_root)?;
        fs::write(
            install_root.join(BUNDLE_VERSION_FILE),
            format!("{bundled_version}\n"),
        )
        .map_err(|e| format!("managed_backend_version_write_failed:{e}"))?;
    }

    fs::create_dir_all(install_root.join("data"))
        .map_err(|e| format!("managed_backend_data_preserve_dir_failed:{e}"))?;
    sync_release_attestation(bundled_root, &install_root)?;
    Ok(install_root)
}

fn sync_runtime_tree(src: &Path, dst: &Path) -> Result<(), String> {
    for entry in fs::read_dir(src).map_err(|e| format!("managed_backend_read_dir_failed:{e}"))? {
        let entry = entry.map_err(|e| format!("managed_backend_dir_entry_failed:{e}"))?;
        let file_name = entry.file_name();
        let file_name_str = file_name.to_string_lossy();
        if PERSISTENT_NAMES.contains(&file_name_str.as_ref()) {
            continue;
        }

        let src_path = entry.path();
        let dst_path = dst.join(&file_name);
        let file_type = entry
            .file_type()
            .map_err(|e| format!("managed_backend_file_type_failed:{e}"))?;

        if file_type.is_dir() {
            fs::create_dir_all(&dst_path)
                .map_err(|e| format!("managed_backend_mkdir_failed:{e}"))?;
            sync_runtime_tree(&src_path, &dst_path)?;
        } else {
            if let Some(parent) = dst_path.parent() {
                fs::create_dir_all(parent)
                    .map_err(|e| format!("managed_backend_parent_dir_failed:{e}"))?;
            }
            fs::copy(&src_path, &dst_path)
                .map_err(|e| format!("managed_backend_copy_failed:{e}"))?;
        }
    }
    Ok(())
}

fn sync_release_attestation(bundled_root: &Path, install_root: &Path) -> Result<(), String> {
    let bundled_path = release_attestation_path(bundled_root);
    let installed_path = release_attestation_path(install_root);
    if !bundled_path.exists() {
        return Ok(());
    }
    if let Some(parent) = installed_path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("managed_backend_attestation_dir_failed:{e}"))?;
    }
    fs::copy(&bundled_path, &installed_path)
        .map_err(|e| format!("managed_backend_attestation_copy_failed:{e}"))?;
    Ok(())
}

fn release_attestation_path(root: &Path) -> PathBuf {
    RELEASE_ATTESTATION_RELATIVE_PATH
        .iter()
        .fold(root.to_path_buf(), |acc, part| acc.join(part))
}

fn ensure_env_file(
    runtime_root: &Path,
    desired_admin_key: Option<String>,
) -> Result<ManagedBackendSecrets, String> {
    let env_path = runtime_root.join(".env");
    if env_path.exists() {
        return seed_managed_env(&env_path, desired_admin_key);
    }
    let example_path = runtime_root.join(".env.example");
    if example_path.exists() {
        fs::copy(&example_path, &env_path)
            .map_err(|e| format!("managed_backend_env_copy_failed:{e}"))?;
    } else {
        fs::write(&env_path, b"").map_err(|e| format!("managed_backend_env_create_failed:{e}"))?;
    }
    seed_managed_env(&env_path, desired_admin_key)
}

fn seed_managed_env(
    env_path: &Path,
    desired_admin_key: Option<String>,
) -> Result<ManagedBackendSecrets, String> {
    let mut lines: Vec<String> = fs::read_to_string(env_path)
        .unwrap_or_default()
        .lines()
        .map(str::to_owned)
        .collect();
    let mut modified = false;
    let mut resolved_admin_key = String::new();

    for spec in managed_secret_specs() {
        let override_value = if spec.key == "ADMIN_KEY" {
            desired_admin_key.as_deref()
        } else {
            None
        };
        let mut found = false;

        for line in &mut lines {
            if let Some(current) = parse_env_value(line, spec.key) {
                found = true;
                if let Some(forced) = override_value {
                    if current != forced {
                        *line = format!("{}={}", spec.key, forced);
                        modified = true;
                    }
                    if spec.key == "ADMIN_KEY" {
                        resolved_admin_key = forced.to_string();
                    }
                } else if is_invalid_secret_value(current, spec.min_len) {
                    let generated = generate_secret()?;
                    *line = format!("{}={}", spec.key, generated);
                    modified = true;
                    if spec.key == "ADMIN_KEY" {
                        resolved_admin_key = generated;
                    }
                } else if spec.key == "ADMIN_KEY" {
                    resolved_admin_key = current.to_string();
                }
                break;
            }
        }

        if !found {
            let value = if let Some(forced) = override_value {
                forced.to_string()
            } else {
                generate_secret()?
            };
            if !lines.is_empty() && !lines.last().is_some_and(|line| line.is_empty()) {
                lines.push(String::new());
            }
            lines.push(format!("{}={}", spec.key, value));
            modified = true;
            if spec.key == "ADMIN_KEY" {
                resolved_admin_key = value;
            }
        }
    }

    for spec in managed_bool_default_specs() {
        let mut found = false;

        for line in &mut lines {
            if let Some(current) = parse_env_value(line, spec.key) {
                found = true;
                match parse_env_boolish(current) {
                    Some(parsed) if spec.preserve_non_default || parsed == spec.default_value => {}
                    _ => {
                        *line = format!("{}={}", spec.key, render_env_bool(spec.default_value));
                        modified = true;
                    }
                }
                break;
            }
        }

        if !found {
            if !lines.is_empty() && !lines.last().is_some_and(|line| line.is_empty()) {
                lines.push(String::new());
            }
            lines.push(format!(
                "{}={}",
                spec.key,
                render_env_bool(spec.default_value)
            ));
            modified = true;
        }
    }

    if modified {
        let mut rendered = lines.join("\n");
        if !rendered.ends_with('\n') {
            rendered.push('\n');
        }
        fs::write(env_path, rendered)
            .map_err(|e| format!("managed_backend_env_seed_failed:{e}"))?;
    }

    Ok(ManagedBackendSecrets {
        admin_key: resolved_admin_key,
    })
}

fn managed_secret_specs() -> Vec<ManagedSecretSpec> {
    let mut specs = vec![
        ManagedSecretSpec {
            key: "ADMIN_KEY",
            min_len: 32,
        },
        ManagedSecretSpec {
            key: "MESH_PEER_PUSH_SECRET",
            min_len: 16,
        },
        ManagedSecretSpec {
            key: "MESH_DM_TOKEN_PEPPER",
            min_len: 16,
        },
    ];

    if !cfg!(target_os = "windows") {
        specs.push(ManagedSecretSpec {
            key: "MESH_SECURE_STORAGE_SECRET",
            min_len: 16,
        });
    }

    specs
}

fn managed_bool_default_specs() -> Vec<ManagedBoolDefaultSpec> {
    vec![
        ManagedBoolDefaultSpec {
            key: "MESH_BLOCK_LEGACY_NODE_ID_COMPAT",
            default_value: true,
            preserve_non_default: false,
        },
        ManagedBoolDefaultSpec {
            key: "MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP",
            default_value: true,
            preserve_non_default: true,
        },
    ]
}

fn parse_env_value<'a>(line: &'a str, key: &str) -> Option<&'a str> {
    let trimmed = line.trim_start();
    if trimmed.is_empty() || trimmed.starts_with('#') {
        return None;
    }
    let normalized = trimmed.strip_prefix("export ").unwrap_or(trimmed);
    let (line_key, raw_value) = normalized.split_once('=')?;
    if line_key.trim() != key {
        return None;
    }
    Some(raw_value.trim().trim_matches('"').trim_matches('\'').trim())
}

fn parse_env_boolish(value: &str) -> Option<bool> {
    match value.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Some(true),
        "0" | "false" | "no" | "off" => Some(false),
        _ => None,
    }
}

fn render_env_bool(value: bool) -> &'static str {
    if value {
        "true"
    } else {
        "false"
    }
}

fn is_invalid_secret_value(value: &str, min_len: usize) -> bool {
    let raw = value.trim();
    let lowered = raw.to_ascii_lowercase();
    raw.is_empty() || lowered == "change-me" || lowered == "changeme" || raw.len() < min_len
}

fn generate_secret() -> Result<String, String> {
    let mut bytes = [0u8; GENERATED_SECRET_BYTES];
    getrandom::getrandom(&mut bytes)
        .map_err(|e| format!("managed_backend_secret_rng_failed:{e}"))?;
    let mut out = String::with_capacity(GENERATED_SECRET_BYTES * 2);
    for byte in bytes {
        let _ = write!(&mut out, "{byte:02x}");
    }
    Ok(out)
}

fn reserve_loopback_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|e| format!("managed_backend_port_bind_failed:{e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("managed_backend_port_addr_failed:{e}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn resolve_python_bin(runtime_root: &Path) -> Result<PathBuf, String> {
    let selected_venv = read_trimmed_file_optional(&runtime_root.join(".venv-dir"))
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "venv".to_string());

    let mut candidate_roots = vec![runtime_root.join(&selected_venv)];
    if selected_venv != "venv" {
        candidate_roots.push(runtime_root.join("venv"));
    }

    let candidates = if cfg!(target_os = "windows") {
        candidate_roots
            .into_iter()
            .map(|root| root.join("Scripts").join("python.exe"))
            .collect::<Vec<_>>()
    } else {
        candidate_roots
            .into_iter()
            .flat_map(|root| {
                [
                    root.join("bin").join("python3"),
                    root.join("bin").join("python"),
                ]
            })
            .collect::<Vec<_>>()
    };

    for candidate in candidates {
        if candidate.exists() {
            return Ok(candidate);
        }
    }
    Err("managed_backend_python_missing".to_string())
}

async fn wait_for_backend_ready(base_url: &str, child: &mut Child) -> Result<(), String> {
    let client = reqwest::Client::new();
    let deadline = Instant::now() + Duration::from_secs(45);
    let health_url = format!("{base_url}/api/health");

    while Instant::now() < deadline {
        if let Some(status) = child
            .try_wait()
            .map_err(|e| format!("managed_backend_wait_failed:{e}"))?
        {
            return Err(format!("managed_backend_exited_early:{status}"));
        }

        if let Ok(response) = client.get(&health_url).send().await {
            if response.status().is_success() {
                return Ok(());
            }
        }

        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    let _ = child.kill();
    let _ = child.wait();
    Err("managed_backend_health_timeout".to_string())
}

fn read_trimmed_file(path: &Path) -> Result<String, String> {
    fs::read_to_string(path)
        .map(|s| s.trim().to_string())
        .map_err(|e| format!("managed_backend_version_read_failed:{e}"))
}

fn read_trimmed_file_optional(path: &Path) -> Option<String> {
    fs::read_to_string(path).ok().map(|s| s.trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundled_backend_root_requires_main_py() {
        let temp = std::env::temp_dir().join(format!(
            "sb_backend_root_test_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let resource_dir = temp.join("resources");
        let backend_dir = resource_dir.join(RESOURCE_DIR_NAME);
        fs::create_dir_all(&backend_dir).unwrap();

        assert!(bundled_backend_root(&resource_dir).is_none());

        fs::write(backend_dir.join("main.py"), "print('ok')").unwrap();
        assert_eq!(
            bundled_backend_root(&resource_dir),
            Some(backend_dir.clone())
        );

        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn sync_runtime_tree_preserves_env_and_data() {
        let temp = std::env::temp_dir().join(format!(
            "sb_backend_sync_test_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let src = temp.join("src");
        let dst = temp.join("dst");
        fs::create_dir_all(src.join("config")).unwrap();
        fs::create_dir_all(dst.join("data")).unwrap();
        fs::write(src.join("main.py"), "print('new')").unwrap();
        fs::write(src.join(".env.example"), "ADMIN_KEY=").unwrap();
        fs::write(dst.join(".env"), "preserve_me").unwrap();
        fs::write(dst.join("data").join("keep.txt"), "keep").unwrap();

        sync_runtime_tree(&src, &dst).unwrap();

        assert_eq!(fs::read_to_string(dst.join(".env")).unwrap(), "preserve_me");
        assert_eq!(
            fs::read_to_string(dst.join("data").join("keep.txt")).unwrap(),
            "keep"
        );
        assert_eq!(
            fs::read_to_string(dst.join("main.py")).unwrap(),
            "print('new')"
        );

        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn sync_release_attestation_updates_only_attestation_file() {
        let temp = std::env::temp_dir().join(format!(
            "sb_backend_attestation_sync_test_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let src = temp.join("src");
        let dst = temp.join("dst");
        fs::create_dir_all(src.join("data")).unwrap();
        fs::create_dir_all(dst.join("data")).unwrap();
        fs::write(release_attestation_path(&src), "{\"commit\":\"new\"}\n").unwrap();
        fs::write(release_attestation_path(&dst), "{\"commit\":\"old\"}\n").unwrap();
        fs::write(dst.join("data").join("keep.txt"), "keep").unwrap();

        sync_release_attestation(&src, &dst).unwrap();

        assert_eq!(
            fs::read_to_string(release_attestation_path(&dst)).unwrap(),
            "{\"commit\":\"new\"}\n"
        );
        assert_eq!(
            fs::read_to_string(dst.join("data").join("keep.txt")).unwrap(),
            "keep"
        );

        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn ensure_env_file_generates_required_managed_secrets() {
        let temp = std::env::temp_dir().join(format!(
            "sb_backend_env_seed_test_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&temp).unwrap();
        fs::write(temp.join(".env.example"), "AIS_API_KEY=\n").unwrap();

        let secrets = ensure_env_file(&temp, None).unwrap();
        let env_text = fs::read_to_string(temp.join(".env")).unwrap();
        let env_lines: Vec<&str> = env_text.lines().collect();

        assert!(secrets.admin_key.len() >= 32);
        assert!(
            env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "ADMIN_KEY"))
                .unwrap()
                .len()
                >= 32
        );
        assert!(
            env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "MESH_PEER_PUSH_SECRET"))
                .unwrap()
                .len()
                >= 16
        );
        assert!(
            env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "MESH_DM_TOKEN_PEPPER"))
                .unwrap()
                .len()
                >= 16
        );
        assert_eq!(
            env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "MESH_BLOCK_LEGACY_NODE_ID_COMPAT"))
                .unwrap(),
            "true"
        );
        assert_eq!(
            env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP"))
                .unwrap(),
            "true"
        );
        if cfg!(target_os = "windows") {
            assert!(env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "MESH_SECURE_STORAGE_SECRET"))
                .is_none());
        } else {
            assert!(
                env_lines
                    .iter()
                    .find_map(|line| parse_env_value(line, "MESH_SECURE_STORAGE_SECRET"))
                    .unwrap()
                    .len()
                    >= 16
            );
        }

        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn ensure_env_file_replaces_invalid_values_and_preserves_valid_ones() {
        let temp = std::env::temp_dir().join(format!(
            "sb_backend_env_backfill_test_{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&temp).unwrap();
        fs::write(
            temp.join(".env"),
            "ADMIN_KEY=short\nMESH_PEER_PUSH_SECRET=change-me\nMESH_DM_TOKEN_PEPPER=valid-pepper-value-1234\nMESH_BLOCK_LEGACY_NODE_ID_COMPAT=false\nMESH_BLOCK_LEGACY_AGENT_ID_LOOKUP=\n",
        )
        .unwrap();

        let secrets = ensure_env_file(
            &temp,
            Some("desktop-admin-key-0123456789abcdef".to_string()),
        )
        .unwrap();
        let env_text = fs::read_to_string(temp.join(".env")).unwrap();
        let env_lines: Vec<&str> = env_text.lines().collect();

        assert_eq!(secrets.admin_key, "desktop-admin-key-0123456789abcdef");
        assert_eq!(
            env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "ADMIN_KEY"))
                .unwrap(),
            "desktop-admin-key-0123456789abcdef"
        );
        assert_ne!(
            env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "MESH_PEER_PUSH_SECRET"))
                .unwrap(),
            "change-me"
        );
        assert_eq!(
            env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "MESH_DM_TOKEN_PEPPER"))
                .unwrap(),
            "valid-pepper-value-1234"
        );
        assert_eq!(
            env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "MESH_BLOCK_LEGACY_NODE_ID_COMPAT"))
                .unwrap(),
            "true"
        );
        assert_eq!(
            env_lines
                .iter()
                .find_map(|line| parse_env_value(line, "MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP"))
                .unwrap(),
            "true"
        );

        let _ = fs::remove_dir_all(temp);
    }
}
