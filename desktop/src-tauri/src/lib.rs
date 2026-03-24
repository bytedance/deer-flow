mod desktop_integration;
mod tray;
mod window;

use std::{fs, path::Path};

#[derive(serde::Serialize)]
struct DroppedFilePayload {
    bytes: Vec<u8>,
    name: String,
    path: String,
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

pub fn run() {
    tauri::Builder::default()
        .manage(tray::TrayState::default())
        .plugin(desktop_integration::autostart_plugin())
        .plugin(desktop_integration::global_shortcut_plugin())
        .setup(|app| {
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
