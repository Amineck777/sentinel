//! sidecar管理(実装方針 §2/§3)。
//!
//! - リリースビルド時のみ `sentinel-core` sidecar を spawn する
//!   (devビルドでは `make core-dev` の固定ポートへフロントが直接接続)
//! - stdout の `SENTINEL_HANDSHAKE {json}` 行を待ち、port/token を状態へ保存
//! - アプリ終了時: 子の stdin が drop で閉じる → コア側が EOF 検知で自死。
//!   保険として kill も送る(二重化)。

use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

const HANDSHAKE_PREFIX: &str = "SENTINEL_HANDSHAKE ";

#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct CoreInfo {
    pub port: u16,
    pub token: String,
}

#[derive(Default)]
pub struct CoreState {
    pub info: Mutex<Option<CoreInfo>>,
    pub child: Mutex<Option<CommandChild>>,
}

/// フロントエンドが接続先を取得するコマンド(app/src/api/client.ts が呼ぶ)
#[tauri::command]
pub fn get_core_info(state: tauri::State<'_, CoreState>) -> Option<CoreInfo> {
    state.info.lock().unwrap().clone()
}

pub fn spawn_core(app: &AppHandle) -> tauri::Result<()> {
    let sidecar = app
        .shell()
        .sidecar("sentinel-core")
        .expect("sidecar 'sentinel-core' not bundled")
        .args(["--port", "0"]); // managedモード: 動的ポート・ランダムトークン

    let (mut rx, child) = sidecar.spawn()?;

    let state = app.state::<CoreState>();
    *state.child.lock().unwrap() = Some(child);

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    let text = String::from_utf8_lossy(&line);
                    if let Some(json) = text.trim().strip_prefix(HANDSHAKE_PREFIX) {
                        if let Ok(info) = serde_json::from_str::<CoreInfo>(json) {
                            let state = app_handle.state::<CoreState>();
                            *state.info.lock().unwrap() = Some(info.clone());
                            let _ = app_handle.emit("core-ready", info);
                        }
                    }
                    // handshake以外のstdout行はログ扱い(トークンを含む行は上で消費済み)
                }
                CommandEvent::Stderr(line) => {
                    eprintln!("[core] {}", String::from_utf8_lossy(&line));
                }
                CommandEvent::Terminated(status) => {
                    eprintln!("[core] terminated: {:?}", status.code);
                    let state = app_handle.state::<CoreState>();
                    *state.info.lock().unwrap() = None; // UIのステータスレールがOFFLINE表示に
                    break;
                }
                _ => {}
            }
        }
    });
    Ok(())
}

/// 終了時の後始末: kill(stdin EOF自死との二重化)
pub fn shutdown_core(app: &AppHandle) {
    let state = app.state::<CoreState>();
    if let Some(child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
    }
}
