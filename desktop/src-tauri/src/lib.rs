mod window;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_store::Builder::default().build())
        .invoke_handler(tauri::generate_handler![
            window::open_new_chat_window,
            window::open_thread_window
        ])
        .run(tauri::generate_context!())
        .expect("error while running DeerFlow desktop shell");
}
