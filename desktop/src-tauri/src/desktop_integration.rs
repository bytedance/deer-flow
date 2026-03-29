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

#[derive(Debug, Clone, PartialEq, Eq)]
struct AutostartSyncReport {
    desired_mode: AutostartMode,
    observed_os_enabled: Option<bool>,
    warnings: Vec<String>,
}

impl AutostartSyncReport {
    fn new(desired_mode: AutostartMode) -> Self {
        Self {
            desired_mode,
            observed_os_enabled: None,
            warnings: Vec::new(),
        }
    }
}

trait AutostartSyncBackend {
    fn load_persisted_mode(&self) -> Result<AutostartMode, String>;
    fn is_enabled(&self) -> Result<bool, String>;
    fn enable(&self) -> Result<(), String>;
    fn disable(&self) -> Result<(), String>;
    fn persist_mode(&self, mode: AutostartMode) -> Result<(), String>;
}

struct AppAutostartBackend<'app, R: Runtime> {
    app: &'app AppHandle<R>,
}

impl<'app, R: Runtime> AppAutostartBackend<'app, R> {
    fn new(app: &'app AppHandle<R>) -> Self {
        Self { app }
    }
}

impl<R: Runtime> AutostartSyncBackend for AppAutostartBackend<'_, R> {
    fn load_persisted_mode(&self) -> Result<AutostartMode, String> {
        let store = self
            .app
            .store(AUTOSTART_STORE_PATH)
            .map_err(|error| {
                format!("autostart store() failed while loading desktop preference: {error}")
            })?;
        let persisted_enabled = store
            .get(AUTOSTART_STORE_KEY)
            .and_then(|value| value.as_bool());

        Ok(resolve_autostart_mode(persisted_enabled))
    }

    fn is_enabled(&self) -> Result<bool, String> {
        self.app
            .autolaunch()
            .is_enabled()
            .map_err(|error| format!("autostart is_enabled() failed: {error}"))
    }

    fn enable(&self) -> Result<(), String> {
        self.app
            .autolaunch()
            .enable()
            .map_err(|error| format!("autostart enable() failed: {error}"))
    }

    fn disable(&self) -> Result<(), String> {
        self.app
            .autolaunch()
            .disable()
            .map_err(|error| format!("autostart disable() failed: {error}"))
    }

    fn persist_mode(&self, mode: AutostartMode) -> Result<(), String> {
        let store = self
            .app
            .store(AUTOSTART_STORE_PATH)
            .map_err(|error| {
                format!("autostart store() failed while persisting desktop preference: {error}")
            })?;
        store.set(AUTOSTART_STORE_KEY, matches!(mode, AutostartMode::Enabled));
        store.save().map_err(|error| {
            format!("autostart save() failed while persisting desktop preference: {error}")
        })
    }
}

fn phase2_global_shortcut_accelerator() -> &'static str {
    "CommandOrControl+Shift+Alt+D"
}

fn phase2_global_shortcut() -> Shortcut {
    #[cfg(target_os = "macos")]
    let modifiers = Modifiers::SUPER | Modifiers::SHIFT | Modifiers::ALT;

    #[cfg(not(target_os = "macos"))]
    let modifiers = Modifiers::CONTROL | Modifiers::SHIFT | Modifiers::ALT;

    Shortcut::new(Some(modifiers), Code::KeyD)
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

fn sync_autostart_state_with(backend: &impl AutostartSyncBackend) -> AutostartSyncReport {
    let desired_mode = match backend.load_persisted_mode() {
        Ok(mode) => mode,
        Err(error) => {
            let mut report = AutostartSyncReport::new(resolve_autostart_mode(None));
            report.warnings.push(error);
            return report;
        }
    };

    let mut report = AutostartSyncReport::new(desired_mode);

    match backend.is_enabled() {
        Ok(is_enabled) => {
            report.observed_os_enabled = Some(is_enabled);

            let sync_result = match (desired_mode, is_enabled) {
                (AutostartMode::Enabled, false) => backend.enable(),
                (AutostartMode::Disabled, true) => backend.disable(),
                _ => Ok(()),
            };

            if let Err(error) = sync_result {
                report.warnings.push(error);
            }
        }
        Err(error) => report.warnings.push(error),
    }

    if let Err(error) = backend.persist_mode(desired_mode) {
        report.warnings.push(error);
    }

    report
}

fn sync_autostart_state<R: Runtime>(app: &AppHandle<R>) -> AutostartSyncReport {
    sync_autostart_state_with(&AppAutostartBackend::new(app))
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
    let autostart_report = sync_autostart_state(&app.handle());

    for warning in &autostart_report.warnings {
        eprintln!("desktop integration warning: {warning}");
    }

    println!(
        "desktop integration: autostart desired_mode={:?} observed_os_enabled={:?} warnings={}",
        autostart_report.desired_mode,
        autostart_report.observed_os_enabled,
        autostart_report.warnings.len()
    );

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

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

    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum AutostartFailureStep {
        LoadStore,
        IsEnabled,
        Enable,
        Disable,
        PersistStore,
        Save,
    }

    impl AutostartFailureStep {
        fn expected_fragment(self) -> &'static str {
            match self {
                Self::LoadStore | Self::PersistStore => "store()",
                Self::IsEnabled => "is_enabled()",
                Self::Enable => "enable()",
                Self::Disable => "disable()",
                Self::Save => "save()",
            }
        }
    }

    struct FakeAutostartBackend {
        desired_mode: AutostartMode,
        os_enabled: bool,
        failure_step: Option<AutostartFailureStep>,
        enable_calls: Cell<usize>,
        disable_calls: Cell<usize>,
    }

    impl FakeAutostartBackend {
        fn with_failure(
            desired_mode: AutostartMode,
            os_enabled: bool,
            failure_step: AutostartFailureStep,
        ) -> Self {
            Self {
                desired_mode,
                os_enabled,
                failure_step: Some(failure_step),
                enable_calls: Cell::new(0),
                disable_calls: Cell::new(0),
            }
        }

        fn error_for(&self, step: AutostartFailureStep) -> Result<(), String> {
            if self.failure_step == Some(step) {
                return Err(format!("{} failed in test backend", step.expected_fragment()));
            }

            Ok(())
        }
    }

    impl AutostartSyncBackend for FakeAutostartBackend {
        fn load_persisted_mode(&self) -> Result<AutostartMode, String> {
            self.error_for(AutostartFailureStep::LoadStore)?;
            Ok(self.desired_mode)
        }

        fn is_enabled(&self) -> Result<bool, String> {
            self.error_for(AutostartFailureStep::IsEnabled)?;
            Ok(self.os_enabled)
        }

        fn enable(&self) -> Result<(), String> {
            self.enable_calls.set(self.enable_calls.get() + 1);
            self.error_for(AutostartFailureStep::Enable)
        }

        fn disable(&self) -> Result<(), String> {
            self.disable_calls.set(self.disable_calls.get() + 1);
            self.error_for(AutostartFailureStep::Disable)
        }

        fn persist_mode(&self, _mode: AutostartMode) -> Result<(), String> {
            self.error_for(AutostartFailureStep::PersistStore)?;
            self.error_for(AutostartFailureStep::Save)
        }
    }

    #[test]
    fn autostart_failures_only_emit_warnings_and_do_not_block_startup() {
        let failure_cases = [
            (
                AutostartFailureStep::LoadStore,
                AutostartMode::Enabled,
                false,
                AutostartMode::Disabled,
                0,
                0,
            ),
            (
                AutostartFailureStep::IsEnabled,
                AutostartMode::Enabled,
                false,
                AutostartMode::Enabled,
                0,
                0,
            ),
            (
                AutostartFailureStep::Enable,
                AutostartMode::Enabled,
                false,
                AutostartMode::Enabled,
                1,
                0,
            ),
            (
                AutostartFailureStep::Disable,
                AutostartMode::Disabled,
                true,
                AutostartMode::Disabled,
                0,
                1,
            ),
            (
                AutostartFailureStep::PersistStore,
                AutostartMode::Enabled,
                true,
                AutostartMode::Enabled,
                0,
                0,
            ),
            (
                AutostartFailureStep::Save,
                AutostartMode::Enabled,
                true,
                AutostartMode::Enabled,
                0,
                0,
            ),
        ];

        for (
            failure_step,
            desired_mode,
            os_enabled,
            expected_mode,
            expected_enable_calls,
            expected_disable_calls,
        ) in failure_cases
        {
            let backend =
                FakeAutostartBackend::with_failure(desired_mode, os_enabled, failure_step);

            let report = sync_autostart_state_with(&backend);

            assert_eq!(report.desired_mode, expected_mode, "{failure_step:?}");
            assert_eq!(report.warnings.len(), 1, "{failure_step:?}");
            assert!(
                report.warnings[0].contains(failure_step.expected_fragment()),
                "{failure_step:?}: {:?}",
                report.warnings
            );
            assert_eq!(backend.enable_calls.get(), expected_enable_calls, "{failure_step:?}");
            assert_eq!(
                backend.disable_calls.get(),
                expected_disable_calls,
                "{failure_step:?}"
            );
        }
    }
}
