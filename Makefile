.PHONY: setup core-dev ui-dev tauri-dev test sidecar bundle

setup:            ## 初回セットアップ(Python依存 + Node依存)
	cd core && pip install -e ".[dev]"
	cd app && pnpm install

core-dev:         ## コアをdevモードで起動(http://127.0.0.1:8765 / dev-token)
	python scripts/dev.py

ui-dev:           ## Vite devサーバ(ブラウザでUI開発)
	cd app && pnpm dev

tauri-dev:        ## Tauriウィンドウで統合確認(core-devを別ターミナルで起動しておく)
	cd app && pnpm tauri dev

test:             ## コアのテスト
	cd core && python -m pytest tests/ -q

sidecar:          ## コアをPyInstallerでsidecar化(要: pip install pyinstaller)
	python scripts/build_sidecar.py

bundle: sidecar   ## 配布ビルド(.msi/.dmg/.AppImage)
	cd app && pnpm tauri build
