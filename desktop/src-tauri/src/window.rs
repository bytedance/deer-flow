use std::sync::atomic::{AtomicU64, Ordering};

use tauri::{AppHandle, Url, WebviewUrl, WebviewWindowBuilder};

const DEERFLOW_BASE_URL: &str = "http://localhost:2026";
const CHAT_WINDOW_TITLE: &str = "DeerFlow";
const CHAT_WINDOW_WIDTH: f64 = 1280.0;
const CHAT_WINDOW_HEIGHT: f64 = 800.0;

static NEXT_WINDOW_ID: AtomicU64 = AtomicU64::new(1);

fn next_window_id() -> u64 {
    NEXT_WINDOW_ID.fetch_add(1, Ordering::Relaxed)
}

fn new_chat_window_label(window_id: u64) -> String {
    format!("chat-new-{window_id}")
}

fn thread_window_label(thread_id: &str, window_id: u64) -> String {
    format!("chat-thread-{thread_id}-{window_id}")
}

fn new_chat_window_url() -> String {
    format!("{DEERFLOW_BASE_URL}/workspace/chats/new")
}

fn thread_window_url(thread_id: &str) -> String {
    format!("{DEERFLOW_BASE_URL}/workspace/chats/{thread_id}")
}

fn build_chat_window(app: &AppHandle, label: String, url: String) -> Result<String, String> {
    let parsed_url = Url::parse(&url).map_err(|error| error.to_string())?;

    WebviewWindowBuilder::new(app, label.clone(), WebviewUrl::External(parsed_url))
        .title(CHAT_WINDOW_TITLE)
        .inner_size(CHAT_WINDOW_WIDTH, CHAT_WINDOW_HEIGHT)
        .decorations(true)
        .build()
        .map(|_| label)
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub(crate) async fn open_new_chat_window(app: AppHandle) -> Result<String, String> {
    let label = new_chat_window_label(next_window_id());
    let url = new_chat_window_url();

    build_chat_window(&app, label, url)
}

#[tauri::command]
pub(crate) async fn open_thread_window(app: AppHandle, thread_id: String) -> Result<String, String> {
    let label = thread_window_label(&thread_id, next_window_id());
    let url = thread_window_url(&thread_id);

    build_chat_window(&app, label, url)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn builds_new_chat_window_label() {
        assert_eq!(new_chat_window_label(7), "chat-new-7");
    }

    #[test]
    fn builds_thread_window_label() {
        assert_eq!(
            thread_window_label("thread-123", 7),
            "chat-thread-thread-123-7"
        );
    }

    #[test]
    fn builds_new_chat_window_url() {
        assert_eq!(
            new_chat_window_url(),
            "http://localhost:2026/workspace/chats/new"
        );
    }

    #[test]
    fn builds_thread_window_url() {
        assert_eq!(
            thread_window_url("thread-123"),
            "http://localhost:2026/workspace/chats/thread-123"
        );
    }
}
