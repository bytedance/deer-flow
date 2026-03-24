use tauri::{plugin::TauriPlugin, App, AppHandle, Error, Manager, Runtime, Wry};
use tauri_plugin_autostart::ManagerExt as AutostartExt;
use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut, ShortcutEvent, ShortcutState};
use tauri_plugin_store::StoreExt;

const AUTOSTART_ARGUMENT: &str = "--autostart";
const AUTOSTART_STORE_PATH: &str = "desktop-settings.json";
const AUTOSTART_STORE_KEY: &str = "desktop.autostart.enabled";
const MAIN_WINDOW_LABEL: &str = "main";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum GlobalShortcutTarget {
    ShowMainWindow,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum AutostartMode {
    Disabled,
    Enabled,
}

fn phase2_global_shortcut_accelerator() -> &'static str {
    "CommandOrControl+Shift+Alt+D"
}

fn phase2_global_shortcut() -> Shortcut {
    #[cfg(target_os = "macos")]
    let modifiers = Modifiers::SUPER | Modifiers::SHIFT | Modifiers::ALT;

    #[cfg(not(target_os = "macos"))]
    let modifiers = Modifiers::CONTROL | Modifiers::SHIFT | Modifiers::ALT;

    Shortcut::new(
        Some(modifiers),
        Code::KeyD,
    )
}

fn parse_phase2_global_shortcut(shortcut: &str) -> Option<GlobalShortcutTarget> {
    if shortcut.eq_ignore_ascii_case(phase2_global_shortcut_accelerator()) {
        Some(GlobalShortcutTarget::ShowMainWindow)
    } else {
        None
    }
}

fn shortcut_action(target: GlobalShortcutTarget) -> &'static str {
    match target {
        GlobalShortcutTarget::ShowMainWindow => "show-or-focus-main-window",
    }
}

fn resolve_autostart_mode(persisted_enabled: Option<bool>) -> AutostartMode {
    match persisted_enabled.unwrap_or(false) {
        true => AutostartMode::Enabled,
        false => AutostartMode::Disabled,
    }
}

fn global_shortcut_target(shortcut: &Shortcut) -> Option<GlobalShortcutTarget> {
    if shortcut.id() == phase2_global_shortcut().id() {
        Some(GlobalShortcutTarget::ShowMainWindow)
    } else {
        None
    }
}

fn show_or_focus_main_window<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let main_window = app
        .get_webview_window(MAIN_WINDOW_LABEL)
        .ok_or(Error::WebviewNotFound)?;

    if main_window.is_minimized()? {
        main_window.unminimize()?;
    }

    if !main_window.is_visible()? {
        main_window.show()?;
    }

    main_window.set_focus()
}

fn load_persisted_autostart_mode<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<AutostartMode> {
    let store = app
        .store(AUTOSTART_STORE_PATH)
        .map_err(|error| Error::Io(std::io::Error::other(error.to_string())))?;
    let persisted_enabled = store
        .get(AUTOSTART_STORE_KEY)
        .and_then(|value| value.as_bool());

    Ok(resolve_autostart_mode(persisted_enabled))
}

fn persist_autostart_mode<R: Runtime>(app: &AppHandle<R>, mode: AutostartMode) -> tauri::Result<()> {
    let store = app
        .store(AUTOSTART_STORE_PATH)
        .map_err(|error| Error::Io(std::io::Error::other(error.to_string())))?;
    store.set(AUTOSTART_STORE_KEY, matches!(mode, AutostartMode::Enabled));
    store
        .save()
        .map_err(|error| Error::Io(std::io::Error::other(error.to_string())))
}

fn sync_autostart_state<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let desired_mode = load_persisted_autostart_mode(app)?;
    let autolaunch = app.autolaunch();
    let is_enabled = autolaunch
        .is_enabled()
        .map_err(|error| Error::Io(std::io::Error::other(error.to_string())))?;

    match (desired_mode, is_enabled) {
        (AutostartMode::Enabled, false) => autolaunch
            .enable()
            .map_err(|error| Error::Io(std::io::Error::other(error.to_string())))?,
        (AutostartMode::Disabled, true) => autolaunch
            .disable()
            .map_err(|error| Error::Io(std::io::Error::other(error.to_string())))?,
        _ => {}
    }

    persist_autostart_mode(app, desired_mode)?;
    println!(
        "desktop integration: autostart mode={desired_mode:?} os_enabled={}",
        matches!(desired_mode, AutostartMode::Enabled)
    );

    Ok(())
}

fn handle_global_shortcut<R: Runtime>(
    app: &AppHandle<R>,
    shortcut: &Shortcut,
    event: ShortcutEvent,
) {
    if event.state != ShortcutState::Pressed {
        return;
    }

    if let Some(target) = global_shortcut_target(shortcut) {
        println!(
            "desktop integration: shortcut={} action={}",
            phase2_global_shortcut_accelerator(),
            shortcut_action(target)
        );
        let _ = show_or_focus_main_window(app);
    }
}

pub(crate) fn global_shortcut_plugin<R: Runtime>() -> TauriPlugin<R> {
    let target = parse_phase2_global_shortcut(phase2_global_shortcut_accelerator())
        .expect("Card 2 shortcut accelerator should map to a window action");

    tauri_plugin_global_shortcut::Builder::new()
        .with_shortcut(phase2_global_shortcut())
        .expect("Card 2 global shortcut should be a valid accelerator")
        .with_handler(move |app, shortcut, event| {
            if shortcut_action(target) == "show-or-focus-main-window" {
                handle_global_shortcut(app, shortcut, event);
            }
        })
        .build()
}

pub(crate) fn autostart_plugin<R: Runtime>() -> TauriPlugin<R> {
    tauri_plugin_autostart::Builder::new()
        .args([AUTOSTART_ARGUMENT])
        .build()
}

pub(crate) fn setup(app: &mut App<Wry>) -> tauri::Result<()> {
    println!(
        "desktop integration: global shortcut accelerator={} id={}",
        phase2_global_shortcut_accelerator(),
        phase2_global_shortcut().id()
    );
    sync_autostart_state(&app.handle())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exposes_a_stable_phase2_global_shortcut_accelerator() {
        assert_eq!(
            phase2_global_shortcut_accelerator(),
            "CommandOrControl+Shift+Alt+D"
        );
    }

    #[test]
    fn parses_the_phase2_global_shortcut_identifier() {
        assert_eq!(
            parse_phase2_global_shortcut("CommandOrControl+Shift+Alt+D"),
            Some(GlobalShortcutTarget::ShowMainWindow)
        );
        assert_eq!(parse_phase2_global_shortcut("CommandOrControl+Shift+N"), None);
    }

    #[test]
    fn maps_the_phase2_shortcut_to_show_or_focus_main_window() {
        assert_eq!(
            shortcut_action(GlobalShortcutTarget::ShowMainWindow),
            "show-or-focus-main-window"
        );
    }

    #[test]
    fn defaults_autostart_to_disabled_until_a_user_preference_is_saved() {
        assert_eq!(resolve_autostart_mode(None), AutostartMode::Disabled);
        assert_eq!(resolve_autostart_mode(Some(false)), AutostartMode::Disabled);
        assert_eq!(resolve_autostart_mode(Some(true)), AutostartMode::Enabled);
    }

    #[test]
    fn exposes_a_nonzero_shortcut_registration_id() {
        let shortcut_id = phase2_global_shortcut().id();
        println!("phase2_shortcut_id={shortcut_id}");
        assert_ne!(shortcut_id, 0);
    }
}
