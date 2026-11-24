//! シェル(デスクトップアプリ)側の設定。設定画面(app/src/features/settings/)から読み書きする。
//!
//! - 保存先: OS のアプリ設定フォルダの `shell-settings.json`
//!   (Windows なら %APPDATA%\dev.yuto.sentinel\shell-settings.json)
//! - コアの設定(config.yaml: LLM など)とは別物。ここは「窓の見せ方」など Tauri が受け持つものだけ
//! - 変更したら全窓へ `settings://changed` を送り、アバター窓はそれを見てモデルを読み直す

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager};

pub const CHANGED_EVENT: &str = "settings://changed";
pub const AVATAR_WINDOW: &str = "avatar";

#[derive(Clone, Serialize, Deserialize, Debug, PartialEq)]
#[serde(default, rename_all = "camelCase")]
pub struct ShellSettings {
    /// アバター窓を表示するか(起動時にも反映する)
    pub avatar_visible: bool,
    /// アバター窓を常に最前面にするか
    pub avatar_always_on_top: bool,
    /// アバターの VRM ファイルの場所。リポジトリには入れず、手元のファイルを指す(ADR 0109)
    pub avatar_model_path: Option<String>,
    /// 体以外の透明な部分のクリックを、下のアプリへ通すか
    pub avatar_click_through: bool,
    /// 頭の上に吹き出しを出すか
    pub avatar_bubble: bool,
    /// 吹き出しが消えるまでの秒数(話し終えてから)
    pub avatar_bubble_seconds: u32,
    /// マウスカーソルを目で追うか
    pub avatar_follow_cursor: bool,
    /// 表情の強さ(0〜1)。落ち着いたキャラは小さめ
    pub avatar_emotion_strength: f32,
    /// 操作が無いまま何分で居眠りするか(0 で居眠りしない)
    pub avatar_sleep_minutes: u32,
    /// ホットキーでチャットを開くとき、アバターの横に出すか
    pub chat_beside_avatar: bool,
}

impl Default for ShellSettings {
    fn default() -> Self {
        Self {
            avatar_visible: false,
            avatar_always_on_top: true,
            avatar_model_path: None,
            avatar_click_through: true,
            avatar_bubble: true,
            avatar_bubble_seconds: 6,
            avatar_follow_cursor: true,
            avatar_emotion_strength: 0.45,
            avatar_sleep_minutes: 10,
            chat_beside_avatar: true,
        }
    }
}

#[derive(Default)]
pub struct SettingsState(pub Mutex<ShellSettings>);

fn settings_path(app: &AppHandle) -> Option<PathBuf> {
    app.path()
        .app_config_dir()
        .ok()
        .map(|d| d.join("shell-settings.json"))
}

/// 起動時に読む。ファイルが無い・壊れているときは既定値で続ける(設定のせいで起動できないのを防ぐ)
pub fn load(app: &AppHandle) -> ShellSettings {
    let Some(path) = settings_path(app) else {
        return ShellSettings::default();
    };
    match std::fs::read_to_string(&path) {
        Ok(text) => serde_json::from_str(&text).unwrap_or_else(|e| {
            eprintln!(
                "[settings] {} を読めません。既定値で起動します: {e}",
                path.display()
            );
            ShellSettings::default()
        }),
        Err(_) => ShellSettings::default(),
    }
}

fn save(app: &AppHandle, s: &ShellSettings) -> Result<(), String> {
    let path = settings_path(app).ok_or("設定フォルダが分かりません")?;
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(s).map_err(|e| e.to_string())?;
    std::fs::write(&path, text).map_err(|e| e.to_string())
}

/// 設定を窓へ反映する(表示・最前面)
pub fn apply(app: &AppHandle, s: &ShellSettings) {
    if let Some(win) = app.get_webview_window(AVATAR_WINDOW) {
        let _ = win.set_always_on_top(s.avatar_always_on_top);
        if s.avatar_visible {
            let _ = win.show();
        } else {
            let _ = win.hide();
        }
    }
}

/// 設定を置き換えて、保存・反映・通知まで行う。トレイからの切り替えもここを通す
pub fn replace(app: &AppHandle, next: ShellSettings) -> Result<ShellSettings, String> {
    let state = app.state::<SettingsState>();
    *state.0.lock().unwrap() = next.clone();
    save(app, &next)?;
    apply(app, &next);
    let _ = app.emit(CHANGED_EVENT, &next);
    Ok(next)
}

/// トレイの「アバターを表示/隠す」
pub fn toggle_avatar(app: &AppHandle) {
    let mut next = app.state::<SettingsState>().0.lock().unwrap().clone();
    next.avatar_visible = !next.avatar_visible;
    if let Err(e) = replace(app, next) {
        eprintln!("[settings] 保存に失敗: {e}");
    }
}

#[tauri::command]
pub fn get_settings(state: tauri::State<'_, SettingsState>) -> ShellSettings {
    state.0.lock().unwrap().clone()
}

#[tauri::command]
pub fn update_settings(
    app: AppHandle,
    mut settings: ShellSettings,
) -> Result<ShellSettings, String> {
    if let Some(p) = &settings.avatar_model_path {
        if !std::path::Path::new(p).is_file() {
            return Err(format!("ファイルが見つかりません: {p}"));
        }
    }
    // 画面から変な値が来ても壊れないよう、範囲に収める
    settings.avatar_emotion_strength = settings.avatar_emotion_strength.clamp(0.0, 1.0);
    settings.avatar_bubble_seconds = settings.avatar_bubble_seconds.clamp(1, 60);
    settings.avatar_sleep_minutes = settings.avatar_sleep_minutes.min(240);
    replace(&app, settings)
}

/// 設定されたモデルファイルの中身を返す。
/// 任意のパスを読めると危ないので、引数でパスを受け取らず「設定済みのパス」だけを読む。
/// 32MB 程度のファイルも JSON にせずそのままのバイト列で渡す(ipc::Response)
#[tauri::command]
pub fn read_avatar_model(
    state: tauri::State<'_, SettingsState>,
) -> Result<tauri::ipc::Response, String> {
    let path = state
        .0
        .lock()
        .unwrap()
        .avatar_model_path
        .clone()
        .ok_or("モデルが設定されていません")?;
    let bytes = std::fs::read(&path).map_err(|e| format!("{path} を読めません: {e}"))?;
    Ok(tauri::ipc::Response::new(bytes))
}
