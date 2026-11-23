//! アバター窓まわり(ADR 0114)。
//!
//! - クリック透過: 透明な窓は既定では「見えない部分」もクリックを吸ってしまう。
//!   アバター窓はカーソルの位置をここで聞き(`avatar_cursor`)、体や吹き出しの上なら
//!   クリックを受け、それ以外なら `setIgnoreCursorEvents(true)` で下のアプリへ通す。
//!   透過中の窓にはマウスのイベントが一切届かないので、位置は OS から直接聞く必要がある
//! - チャットパネル: ホットキー(Alt+Space)でメイン窓をアバターの横へ出す

use serde::Serialize;
use tauri::{AppHandle, Manager, PhysicalPosition, WebviewWindow};

use crate::settings::{SettingsState, AVATAR_WINDOW};

pub const MAIN_WINDOW: &str = "main";
/// アバターとチャットの間のすき間(物理ピクセル)
const GAP: i32 = 12;

/// アバター窓から見たカーソルの位置(CSS ピクセル。窓の外ならマイナスや幅超えになる)
#[derive(Serialize)]
pub struct CursorInWindow {
    x: f64,
    y: f64,
}

#[tauri::command]
pub fn avatar_cursor(window: WebviewWindow) -> Result<CursorInWindow, String> {
    let cursor = window.cursor_position().map_err(|e| e.to_string())?;
    let origin = window.inner_position().map_err(|e| e.to_string())?;
    let scale = window.scale_factor().map_err(|e| e.to_string())?;
    Ok(CursorInWindow {
        x: (cursor.x - origin.x as f64) / scale,
        y: (cursor.y - origin.y as f64) / scale,
    })
}

/// アバター窓の「チャットを開く」ボタンなど。開いていても前に出すだけ
#[tauri::command]
pub fn show_chat(app: AppHandle) {
    open_chat(&app);
}

/// ホットキー: チャットが前に出ていれば隠し、そうでなければアバターの横に出す
pub fn toggle_chat(app: &AppHandle) {
    let Some(main) = app.get_webview_window(MAIN_WINDOW) else {
        return;
    };
    let visible = main.is_visible().unwrap_or(false);
    let focused = main.is_focused().unwrap_or(false);
    if visible && focused {
        let _ = main.hide();
    } else {
        open_chat(app);
    }
}

fn open_chat(app: &AppHandle) {
    let Some(main) = app.get_webview_window(MAIN_WINDOW) else {
        return;
    };
    let beside = app
        .state::<SettingsState>()
        .0
        .lock()
        .unwrap()
        .chat_beside_avatar;
    if beside {
        place_beside_avatar(app, &main);
    }
    let _ = main.show();
    let _ = main.unminimize();
    let _ = main.set_focus();
}

/// メイン窓をアバター窓の左(入らなければ右)に、下端をそろえて置く。画面からはみ出さないよう収める
fn place_beside_avatar(app: &AppHandle, main: &WebviewWindow) {
    let Some(avatar) = app.get_webview_window(AVATAR_WINDOW) else {
        return;
    };
    if !avatar.is_visible().unwrap_or(false) {
        return; // アバターが出ていなければ、いつもの場所に出す
    }
    let (Ok(a_pos), Ok(a_size), Ok(m_size)) = (
        avatar.outer_position(),
        avatar.outer_size(),
        main.outer_size(),
    ) else {
        return;
    };
    let Ok(Some(monitor)) = avatar.current_monitor() else {
        return;
    };
    let area = monitor.work_area();
    let (left, top) = (area.position.x, area.position.y);
    let right = left + area.size.width as i32;
    let bottom = top + area.size.height as i32;
    let (mw, mh) = (m_size.width as i32, m_size.height as i32);

    let mut x = a_pos.x - mw - GAP;
    if x < left {
        x = a_pos.x + a_size.width as i32 + GAP;
    }
    x = x.clamp(left, (right - mw).max(left));
    let y = (a_pos.y + a_size.height as i32 - mh).clamp(top, (bottom - mh).max(top));
    let _ = main.set_position(PhysicalPosition::new(x, y));
}
