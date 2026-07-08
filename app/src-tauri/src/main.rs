//! SENTINEL Tauriエントリポイント。
//! 責務(仕様 §3.2): 表示・常駐(トレイ)・ホットキー・sidecar管理のみ。
//! ビジネスロジック・LLM呼び出しは一切持たない。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod sidecar;

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager, RunEvent, WindowEvent,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut};

fn toggle_main_window(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        if win.is_visible().unwrap_or(false) {
            let _ = win.hide();
        } else {
            let _ = win.show();
            let _ = win.set_focus();
        }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(sidecar::CoreState::default())
        .invoke_handler(tauri::generate_handler![sidecar::get_core_info])
        .setup(|app| {
            // --- sidecar起動(リリースビルドのみ。devは make core-dev に接続) ---
            #[cfg(not(debug_assertions))]
            sidecar::spawn_core(&app.handle())?;

            // --- トレイ常駐(EX-05) ---
            let show = MenuItem::with_id(app, "show", "SENTINELを表示", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "終了", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => toggle_main_window(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            // --- グローバルホットキー(IN-02): Alt+Space でパレット(=当面メイン窓)を出す ---
            let shortcut: Shortcut = "Alt+Space".parse().unwrap();
            let handle = app.handle().clone();
            app.global_shortcut().on_shortcut(shortcut, move |_app, _sc, _ev| {
                toggle_main_window(&handle);
            })?;

            Ok(())
        })
        // 閉じるボタンは「終了」ではなく「トレイへ隠す」(常駐アプリの流儀)
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                sidecar::shutdown_core(app); // stdin EOF自死との二重化(実装方針 §3)
            }
        });
}
