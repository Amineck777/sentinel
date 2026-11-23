//! SENTINEL Tauriエントリポイント。
//! 責務(仕様 §3.2): 表示・常駐(トレイ)・ホットキー・sidecar管理のみ。
//! ビジネスロジック・LLM呼び出しは一切持たない。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod avatar;
mod settings;
mod sidecar;

use std::sync::Mutex;

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Emitter, Manager, RunEvent, WindowEvent,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

fn toggle_main_window(app: &tauri::AppHandle) {
    toggle_window(app, "main");
}

/// メイン窓を出して、設定画面を開くよう画面側へ知らせる
fn open_settings(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.set_focus();
        let _ = win.emit("settings://open", ());
    }
}

/// 窓の表示・非表示を切り替える。窓は tauri.conf.json の label で指す
fn toggle_window(app: &tauri::AppHandle, label: &str) {
    if let Some(win) = app.get_webview_window(label) {
        if win.is_visible().unwrap_or(false) {
            let _ = win.hide();
        } else {
            let _ = win.show();
            let _ = win.set_focus();
        }
    }
}

/// 既定ホットキーの候補(先頭から順に登録を試す)。
/// Alt+Space はアバター UI の設計どおりチャットパネルを開くキー。登録できている間は Windows の
/// 「ウィンドウメニュー(Alt+Space)」より優先される。PowerToys Run などが使っていて登録できなければ、
/// 次の候補へ。Ctrl+Space は日本語IMEの切替と衝突するため使わない。
/// 環境変数 SENTINEL_HOTKEY で上書きできる。
const HOTKEY_CANDIDATES: &[&str] = &["Alt+Space", "Ctrl+Shift+Space", "Ctrl+Alt+Space"];

/// 実際に登録できたホットキー(設定画面に出す)
#[derive(Default)]
struct HotkeyState(Mutex<Option<String>>);

#[tauri::command]
fn get_hotkey(state: tauri::State<'_, HotkeyState>) -> Option<String> {
    state.0.lock().unwrap().clone()
}

/// ホットキーを登録する。他アプリが使用中などで登録できなくてもアプリは起動を続ける
/// (トレイから操作できるため)。
fn register_hotkey(app: &tauri::AppHandle) {
    let from_env = std::env::var("SENTINEL_HOTKEY").ok();
    let candidates: Vec<&str> = from_env
        .as_deref()
        .into_iter()
        .chain(HOTKEY_CANDIDATES.iter().copied())
        .collect();

    for key in candidates {
        let shortcut: Shortcut = match key.parse() {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[hotkey] '{key}' を解釈できません: {e}");
                continue;
            }
        };
        let handle = app.clone();
        let registered = app
            .global_shortcut()
            .on_shortcut(shortcut, move |_app, _sc, event| {
                // 押下と離上の両方で呼ばれるので、押下だけで切り替える
                // (両方で切り替えると、開いた直後に閉じてしまう)
                if event.state() == ShortcutState::Pressed {
                    avatar::toggle_chat(&handle);
                }
            });
        match registered {
            Ok(()) => {
                eprintln!("[hotkey] {key} を登録しました");
                *app.state::<HotkeyState>().0.lock().unwrap() = Some(key.to_string());
                return;
            }
            Err(e) => eprintln!("[hotkey] {key} を登録できません: {e}"),
        }
    }
    eprintln!("[hotkey] ホットキーなしで起動します(トレイから表示できます)");
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .manage(sidecar::CoreState::default())
        .manage(settings::SettingsState::default())
        .manage(HotkeyState::default())
        .invoke_handler(tauri::generate_handler![
            sidecar::get_core_info,
            settings::get_settings,
            settings::update_settings,
            settings::read_avatar_model,
            avatar::avatar_cursor,
            avatar::show_chat,
            get_hotkey,
        ])
        .setup(|app| {
            // --- sidecar起動(リリースビルドのみ。devは make core-dev に接続) ---
            #[cfg(not(debug_assertions))]
            sidecar::spawn_core(app.handle())?;

            // --- シェル設定の読み込みと反映(アバター窓の表示・最前面) ---
            let loaded = settings::load(app.handle());
            settings::apply(app.handle(), &loaded);
            *app.state::<settings::SettingsState>().0.lock().unwrap() = loaded;

            // --- トレイ常駐(EX-05) ---
            let show = MenuItem::with_id(app, "show", "SENTINELを表示", true, None::<&str>)?;
            let avatar =
                MenuItem::with_id(app, "avatar", "アバターを表示/隠す", true, None::<&str>)?;
            let prefs = MenuItem::with_id(app, "settings", "設定…", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "終了", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &avatar, &prefs, &quit])?;
            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => toggle_main_window(app),
                    "avatar" => settings::toggle_avatar(app),
                    "settings" => open_settings(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            // --- グローバルホットキー(IN-02): パレット(=当面メイン窓)の表示切替 ---
            register_hotkey(app.handle());

            Ok(())
        })
        // 閉じるボタンは「終了」ではなく「トレイへ隠す」(常駐アプリの流儀)
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                if window.label() == settings::AVATAR_WINDOW {
                    // Alt+F4 などで閉じたら「非表示」として設定にも残す(次回起動で勝手に出ないように)
                    let app = window.app_handle();
                    let mut next = app
                        .state::<settings::SettingsState>()
                        .0
                        .lock()
                        .unwrap()
                        .clone();
                    next.avatar_visible = false;
                    let _ = settings::replace(app, next);
                } else {
                    let _ = window.hide();
                }
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
