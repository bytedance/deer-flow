use std::sync::Mutex;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent},
    App, AppHandle, Error, Manager, Wry,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum TrayAction {
    Show,
    Hide,
    Quit,
}

const MAIN_WINDOW_LABEL: &str = "main";
const TRAY_ID: &str = "main-tray";

#[derive(Default)]
pub struct TrayState(pub Mutex<Option<TrayIcon<Wry>>>);

fn show_menu_item_id() -> &'static str {
    "tray-show"
}

fn hide_menu_item_id() -> &'static str {
    "tray-hide"
}

fn quit_menu_item_id() -> &'static str {
    "tray-quit"
}

fn tray_action_for_menu_item(id: &str) -> Option<TrayAction> {
    match id {
        id if id == show_menu_item_id() => Some(TrayAction::Show),
        id if id == hide_menu_item_id() => Some(TrayAction::Hide),
        id if id == quit_menu_item_id() => Some(TrayAction::Quit),
        _ => None,
    }
}

fn toggle_main_window_visibility_action(is_visible: bool) -> TrayAction {
    if is_visible {
        TrayAction::Hide
    } else {
        TrayAction::Show
    }
}

pub(crate) fn setup_tray(app: &mut App<Wry>) -> tauri::Result<()> {
    let tray = build_tray(&app.handle().clone())?;
    let tray_state = app.state::<TrayState>();
    *tray_state.0.lock().expect("tray state poisoned") = Some(tray);
    Ok(())
}

fn build_tray(app: &AppHandle<Wry>) -> tauri::Result<TrayIcon<Wry>> {
    let show_item = MenuItem::with_id(
        app,
        show_menu_item_id(),
        "Show DeerFlow",
        true,
        None::<&str>,
    )?;
    let hide_item = MenuItem::with_id(
        app,
        hide_menu_item_id(),
        "Hide DeerFlow",
        true,
        None::<&str>,
    )?;
    let quit_item = MenuItem::with_id(app, quit_menu_item_id(), "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &hide_item, &quit_item])?;
    let icon = app
        .default_window_icon()
        .cloned()
        .ok_or_else(|| Error::AssetNotFound("default window icon".into()))?;

    TrayIconBuilder::with_id(TRAY_ID)
        .icon(icon)
        .tooltip("DeerFlow")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| {
            if let Some(action) = tray_action_for_menu_item(event.id().as_ref()) {
                let _ = apply_tray_action(app, action);
            }
        })
        .on_tray_icon_event(|tray, event| {
            let _ = handle_tray_icon_event(tray.app_handle(), &event);
        })
        .build(app)
}

fn handle_tray_icon_event(app: &AppHandle<Wry>, event: &TrayIconEvent) -> tauri::Result<()> {
    match event {
        TrayIconEvent::Click {
            button: MouseButton::Left,
            button_state: MouseButtonState::Up,
            ..
        } => {
            let main_window = main_window(app)?;
            let action = toggle_main_window_visibility_action(main_window.is_visible()?);
            apply_tray_action(app, action)
        }
        _ => Ok(()),
    }
}

fn apply_tray_action(app: &AppHandle<Wry>, action: TrayAction) -> tauri::Result<()> {
    match action {
        TrayAction::Show => {
            let main_window = main_window(app)?;
            main_window.show()?;
            main_window.set_focus()
        }
        TrayAction::Hide => main_window(app)?.hide(),
        TrayAction::Quit => {
            app.exit(0);
            Ok(())
        }
    }
}

fn main_window(app: &AppHandle<Wry>) -> tauri::Result<tauri::WebviewWindow<Wry>> {
    app.get_webview_window(MAIN_WINDOW_LABEL)
        .ok_or(Error::WebviewNotFound)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exposes_stable_tray_menu_item_ids() {
        assert_eq!(show_menu_item_id(), "tray-show");
        assert_eq!(hide_menu_item_id(), "tray-hide");
        assert_eq!(quit_menu_item_id(), "tray-quit");
    }

    #[test]
    fn maps_tray_menu_item_ids_to_actions() {
        assert_eq!(
            tray_action_for_menu_item(show_menu_item_id()),
            Some(TrayAction::Show)
        );
        assert_eq!(
            tray_action_for_menu_item(hide_menu_item_id()),
            Some(TrayAction::Hide)
        );
        assert_eq!(
            tray_action_for_menu_item(quit_menu_item_id()),
            Some(TrayAction::Quit)
        );
        assert_eq!(tray_action_for_menu_item("unknown"), None);
    }

    #[test]
    fn toggles_main_window_action_from_current_visibility() {
        assert_eq!(toggle_main_window_visibility_action(true), TrayAction::Hide);
        assert_eq!(toggle_main_window_visibility_action(false), TrayAction::Show);
    }
}
