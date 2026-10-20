use std::sync::atomic::{AtomicBool, Ordering};

use tauri::webview::Color;
use tauri::window::{Effect, EffectState, EffectsBuilder};
use tauri::Manager;
use tauri::{PhysicalPosition, PhysicalRect, Rect, WebviewUrl, WebviewWindowBuilder};

use super::state::{APP_EXIT_REQUESTED, KEEP_ALIVE_FOR_LIGHTWEIGHT_CLOSE};

pub(crate) const MAIN_WINDOW_LABEL: &str = "main";
pub(crate) const TRAY_PREVIEW_WINDOW_LABEL: &str = "tray-preview";
const TRAY_PREVIEW_WIDTH: f64 = 360.0;
const TRAY_PREVIEW_HEIGHT: f64 = 390.0;
const TRAY_PREVIEW_MARGIN: f64 = 8.0;
static SHOW_MAIN_WINDOW_PENDING: AtomicBool = AtomicBool::new(false);

/// 函数 `show_main_window`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - crate: 参数 crate
///
/// # 返回
/// 无
fn show_main_window(app: &tauri::AppHandle) -> bool {
    if APP_EXIT_REQUESTED.load(Ordering::Relaxed) {
        log::info!("show main window skipped because app exit is already requested");
        return false;
    }
    log::info!("show main window requested");
    hide_tray_preview_window(app);
    KEEP_ALIVE_FOR_LIGHTWEIGHT_CLOSE.store(false, Ordering::Relaxed);
    let Some(window) = ensure_main_window(app) else {
        return false;
    };
    if let Err(err) = window.unminimize() {
        log::debug!("unminimize main window before show skipped: {}", err);
    }
    if let Err(err) = window.show() {
        log::warn!("show main window failed: {}", err);
        return false;
    }
    if let Err(err) = window.unminimize() {
        log::warn!("unminimize main window after show failed: {}", err);
    }
    if let Err(err) = window.set_focus() {
        log::warn!("focus main window failed: {}", err);
    }
    log::info!("show main window completed");
    true
}

pub(crate) fn request_show_main_window(app: &tauri::AppHandle) -> Result<(), String> {
    if APP_EXIT_REQUESTED.load(Ordering::Relaxed) {
        return Err("app is exiting; show main window request skipped".to_string());
    }
    if SHOW_MAIN_WINDOW_PENDING.swap(true, Ordering::AcqRel) {
        log::debug!("show main window request coalesced because one is already pending");
        return Ok(());
    }

    let app = app.clone();
    std::thread::spawn(move || {
        if APP_EXIT_REQUESTED.load(Ordering::Relaxed) {
            SHOW_MAIN_WINDOW_PENDING.store(false, Ordering::Release);
            return;
        }
        let app_for_show = app.clone();
        if let Err(err) = app.run_on_main_thread(move || {
            if APP_EXIT_REQUESTED.load(Ordering::Relaxed) {
                log::info!("show main window skipped on main thread because app is exiting");
                SHOW_MAIN_WINDOW_PENDING.store(false, Ordering::Release);
                return;
            }
            let shown = show_main_window(&app_for_show);
            if !shown {
                log::warn!("show main window request completed without showing a window");
            }
            SHOW_MAIN_WINDOW_PENDING.store(false, Ordering::Release);
        }) {
            log::warn!("schedule show main window on main thread failed: {}", err);
            KEEP_ALIVE_FOR_LIGHTWEIGHT_CLOSE.store(false, Ordering::Relaxed);
            SHOW_MAIN_WINDOW_PENDING.store(false, Ordering::Release);
        }
    });
    Ok(())
}

pub(crate) fn hide_tray_preview_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window(TRAY_PREVIEW_WINDOW_LABEL) {
        if let Err(err) = window.hide() {
            log::warn!("hide tray preview window failed: {}", err);
        }
    }
}

pub(crate) fn toggle_tray_preview_window(
    app: &tauri::AppHandle,
    click_position: PhysicalPosition<f64>,
    tray_rect: Rect,
) {
    let Some(window) = ensure_tray_preview_window(app) else {
        return;
    };
    if window.is_visible().unwrap_or(false) {
        if let Err(err) = window.hide() {
            log::warn!("hide tray preview window failed: {}", err);
        }
        return;
    }

    position_tray_preview_window(app, &window, click_position, tray_rect);
    if let Err(err) = window.show() {
        log::warn!("show tray preview window failed: {}", err);
        return;
    }
    let _ = window.set_focus();
}

/// 函数 `ensure_main_window`
///
/// 作者: gaohongshun
///
/// 时间: 2026-04-02
///
/// # 参数
/// - app: 参数 app
///
/// # 返回
/// 返回函数执行结果
fn ensure_main_window(app: &tauri::AppHandle) -> Option<tauri::WebviewWindow> {
    if let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) {
        return Some(window);
    }

    let mut config = app
        .config()
        .app
        .windows
        .iter()
        .find(|window| window.label == MAIN_WINDOW_LABEL)
        .cloned()
        .or_else(|| app.config().app.windows.first().cloned())?;
    config.label = MAIN_WINDOW_LABEL.to_string();

    match WebviewWindowBuilder::from_config(app, &config).and_then(|builder| builder.build()) {
        Ok(window) => Some(window),
        Err(err) => {
            if let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) {
                return Some(window);
            }
            log::warn!("create main window failed: {}", err);
            None
        }
    }
}

fn ensure_tray_preview_window(app: &tauri::AppHandle) -> Option<tauri::WebviewWindow> {
    if let Some(window) = app.get_webview_window(TRAY_PREVIEW_WINDOW_LABEL) {
        return Some(window);
    }

    match WebviewWindowBuilder::new(
        app,
        TRAY_PREVIEW_WINDOW_LABEL,
        WebviewUrl::App("tray-preview/".into()),
    )
    .title("AImanager")
    .inner_size(TRAY_PREVIEW_WIDTH, TRAY_PREVIEW_HEIGHT)
    .min_inner_size(TRAY_PREVIEW_WIDTH, TRAY_PREVIEW_HEIGHT)
    .max_inner_size(TRAY_PREVIEW_WIDTH, TRAY_PREVIEW_HEIGHT)
    .resizable(false)
    .maximizable(false)
    .minimizable(false)
    .decorations(false)
    .transparent(true)
    .background_color(Color(0, 0, 0, 0))
    .effects(
        EffectsBuilder::new()
            .effect(Effect::Popover)
            .state(EffectState::Active)
            .radius(18.0)
            .build(),
    )
    .shadow(false)
    .always_on_top(true)
    .visible_on_all_workspaces(true)
    .skip_taskbar(true)
    .visible(false)
    .focused(false)
    .build()
    {
        Ok(window) => Some(window),
        Err(err) => {
            if let Some(window) = app.get_webview_window(TRAY_PREVIEW_WINDOW_LABEL) {
                return Some(window);
            }
            log::warn!("create tray preview window failed: {}", err);
            None
        }
    }
}

fn position_tray_preview_window(
    app: &tauri::AppHandle,
    window: &tauri::WebviewWindow,
    click_position: PhysicalPosition<f64>,
    tray_rect: Rect,
) {
    let monitor = app
        .monitor_from_point(click_position.x, click_position.y)
        .ok()
        .flatten()
        .or_else(|| app.primary_monitor().ok().flatten());
    let Some(monitor) = monitor else {
        return;
    };
    let position =
        resolve_tray_preview_position(tray_rect, *monitor.work_area(), monitor.scale_factor());
    if let Err(err) = window.set_position(position) {
        log::warn!("position tray preview window failed: {}", err);
    }
}

fn resolve_tray_preview_position(
    tray_rect: Rect,
    work_area: PhysicalRect<i32, u32>,
    scale_factor: f64,
) -> PhysicalPosition<i32> {
    let tray_position = tray_rect.position.to_physical::<f64>(scale_factor);
    let tray_size = tray_rect.size.to_physical::<f64>(scale_factor);
    let margin = TRAY_PREVIEW_MARGIN * scale_factor;
    let preview_width = TRAY_PREVIEW_WIDTH * scale_factor;
    let preview_height = TRAY_PREVIEW_HEIGHT * scale_factor;
    let work_x = f64::from(work_area.position.x);
    let work_y = f64::from(work_area.position.y);
    let work_width = f64::from(work_area.size.width);
    let work_height = f64::from(work_area.size.height);

    let min_x = work_x + margin;
    let max_x = (work_x + work_width - preview_width - margin).max(min_x);
    let center_x = tray_position.x + tray_size.width / 2.0;
    let x = (center_x - preview_width / 2.0).clamp(min_x, max_x);

    let min_y = work_y + margin;
    let max_y = (work_y + work_height - preview_height - margin).max(min_y);
    let below_tray_y = tray_position.y + tray_size.height + margin;
    let above_tray_y = tray_position.y - preview_height - margin;
    let y = if below_tray_y <= max_y {
        below_tray_y
    } else {
        above_tray_y
    }
    .clamp(min_y, max_y);

    PhysicalPosition::new(x.round() as i32, y.round() as i32)
}

#[cfg(test)]
mod tests {
    use super::resolve_tray_preview_position;
    use tauri::{LogicalPosition, LogicalSize, PhysicalPosition, PhysicalRect, PhysicalSize, Rect};

    #[test]
    fn tray_preview_position_stays_inside_work_area() {
        let rect = Rect {
            position: LogicalPosition::new(1410.0, 0.0).into(),
            size: LogicalSize::new(24.0, 24.0).into(),
        };
        let work_area = PhysicalRect {
            position: PhysicalPosition::new(0, 24),
            size: PhysicalSize::new(1440, 876),
        };

        let position = resolve_tray_preview_position(rect, work_area, 1.0);

        assert!(position.x <= 1440 - 360 - 8);
        assert_eq!(position.y, 32);
    }

    #[test]
    fn tray_preview_position_can_flip_above_bottom_tray() {
        let rect = Rect {
            position: LogicalPosition::new(720.0, 870.0).into(),
            size: LogicalSize::new(24.0, 24.0).into(),
        };
        let work_area = PhysicalRect {
            position: PhysicalPosition::new(0, 0),
            size: PhysicalSize::new(1440, 900),
        };

        let position = resolve_tray_preview_position(rect, work_area, 1.0);

        assert!(position.y < 870);
        assert!(position.y >= 8);
    }
}
