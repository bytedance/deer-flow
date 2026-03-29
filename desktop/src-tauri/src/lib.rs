mod desktop_integration;
mod tray;
mod window;

use std::{fs, path::Path};

use tauri::{App, Wry};

const DEFAULT_UPDATER_BASE_URL: &str = "https://updates.example.invalid/deerflow";
const DEFAULT_UPDATER_CHANNEL: &str = "stable";
const UPDATER_PUBLIC_KEY_ENV: &str = "DEERFLOW_UPDATER_PUBLIC_KEY";
const UPDATER_SIGNING_PRIVATE_KEY_ENV: &str = "TAURI_SIGNING_PRIVATE_KEY";

#[derive(serde::Serialize)]
struct DroppedFilePayload {
    bytes: Vec<u8>,
    name: String,
    path: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DesktopUpdaterConfig {
    channel: String,
    endpoint: String,
    public_key_env: &'static str,
}

fn read_dropped_file(path: &Path) -> Result<Option<DroppedFilePayload>, String> {
    if !path.is_file() {
        return Ok(None);
    }

    let bytes = fs::read(path).map_err(|error| error.to_string())?;
    let name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| format!("Failed to resolve dropped file name for {}", path.display()))?
        .to_string();

    Ok(Some(DroppedFilePayload {
        bytes,
        name,
        path: path.to_string_lossy().into_owned(),
    }))
}

#[tauri::command]
async fn read_dropped_files(paths: Vec<String>) -> Result<Vec<DroppedFilePayload>, String> {
    let mut dropped_files = Vec::new();

    for path in paths {
        let trimmed = path.trim();
        if trimmed.is_empty() {
            continue;
        }

        if let Some(file) = read_dropped_file(Path::new(trimmed))? {
            dropped_files.push(file);
        }
    }

    Ok(dropped_files)
}

fn desktop_updater_config() -> Result<DesktopUpdaterConfig, String> {
    let channel = DEFAULT_UPDATER_CHANNEL.to_string();
    let base_url = DEFAULT_UPDATER_BASE_URL.trim_end_matches('/');
    let endpoint =
        format!("{base_url}/{channel}/{{{{target}}}}/{{{{arch}}}}/{{{{current_version}}}}");

    validate_updater_endpoint(&endpoint)?;

    Ok(DesktopUpdaterConfig {
        channel,
        endpoint,
        public_key_env: UPDATER_PUBLIC_KEY_ENV,
    })
}

fn validate_updater_endpoint(endpoint: &str) -> Result<(), String> {
    if !endpoint.starts_with("https://") {
        return Err("Updater endpoint must use HTTPS.".into());
    }

    let missing_placeholders = ["{{target}}", "{{arch}}", "{{current_version}}"]
        .into_iter()
        .filter(|placeholder| !endpoint.contains(*placeholder))
        .collect::<Vec<_>>();

    if !missing_placeholders.is_empty() {
        return Err(format!(
            "Updater endpoint must include {} so the release feed stays platform-aware.",
            missing_placeholders.join(", ")
        ));
    }

    Ok(())
}

fn missing_development_signing_key_message(signing_key: Option<&str>) -> Option<String> {
    signing_key
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(|_| None)
        .unwrap_or_else(|| {
            Some(format!(
                "Updater signing is not configured for this development shell. Set {UPDATER_SIGNING_PRIVATE_KEY_ENV} before running `pnpm tauri build` when you are ready to generate signed updater artifacts."
            ))
        })
}

fn setup_updater(app: &mut App<Wry>) -> tauri::Result<()> {
    let signing_key = std::env::var(UPDATER_SIGNING_PRIVATE_KEY_ENV).ok();
    let public_key = std::env::var(UPDATER_PUBLIC_KEY_ENV)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());

    let config = match desktop_updater_config() {
        Ok(config) => config,
        Err(error) => {
            eprintln!("Updater plugin disabled: {error}");
            return Ok(());
        }
    };

    if let Some(message) = missing_development_signing_key_message(signing_key.as_deref()) {
        eprintln!("{message}");
    }

    let Some(public_key) = public_key else {
        eprintln!(
            "Updater plugin is wired but idle until {UPDATER_PUBLIC_KEY_ENV} is set. Expected feed template: {}",
            config.endpoint
        );
        return Ok(());
    };

    app.handle().plugin(
        tauri_plugin_updater::Builder::new()
            .pubkey(public_key)
            .build(),
    )?;

    eprintln!(
        "Updater plugin enabled for `{}` releases via {}.",
        config.channel, config.endpoint
    );

    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .manage(tray::TrayState::default())
        .plugin(desktop_integration::autostart_plugin())
        .plugin(desktop_integration::global_shortcut_plugin())
        .setup(|app| {
            setup_updater(app)?;
            tray::setup_tray(app)?;
            desktop_integration::setup(app)?;
            Ok(())
        })
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_store::Builder::default().build())
        .invoke_handler(tauri::generate_handler![
            read_dropped_files,
            window::open_new_chat_window,
            window::open_thread_window
        ])
        .run(tauri::generate_context!())
        .expect("error while running DeerFlow desktop shell");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exposes_default_updater_configuration() {
        let config = desktop_updater_config().expect("default updater config");

        assert_eq!(config.channel, "stable");
        assert_eq!(
            config.endpoint,
            "https://updates.example.invalid/deerflow/stable/{{target}}/{{arch}}/{{current_version}}"
        );
        assert_eq!(config.public_key_env, "DEERFLOW_UPDATER_PUBLIC_KEY");
    }

    #[test]
    fn rejects_updater_endpoints_without_required_placeholders() {
        let error = validate_updater_endpoint("https://updates.example.invalid/deerflow/stable")
            .expect_err("endpoint without placeholders should fail");

        assert!(error.contains("{{target}}"));
        assert!(error.contains("{{arch}}"));
        assert!(error.contains("{{current_version}}"));
    }

    #[test]
    fn explains_missing_signing_key_for_development_builds() {
        let message = missing_development_signing_key_message(None)
            .expect("development warning should be emitted");

        assert!(message.contains("TAURI_SIGNING_PRIVATE_KEY"));
        assert!(message.contains("pnpm tauri build"));
    }
}
