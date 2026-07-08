.PHONY: setup core-dev ui-dev tauri-dev test lint fmt sidecar bundle

setup:            ## 初回セットアップ(Python依存 + Node依存)
	cd core && pip install -e ".[dev]"
	cd app && npm install

core-dev:         ## コアをdevモードで起動(http://127.0.0.1:8765 / dev-token)
	python scripts/dev.py

ui-dev:           ## Vite devサーバ(ブラウザでUI開発)
	cd app && npm run dev

tauri-dev:        ## Tauriウィンドウで統合確認(core-devを別ターミナルで起動しておく)
	cd app && npm run tauri dev

test:             ## コアのテスト
	cd core && python -m pytest tests/ -q

lint:             ## 静的解析(ruff+mypy / ESLint+Prettier)
	cd core && python -m ruff check sentinel_core tests && python -m ruff format --check sentinel_core tests && python -m mypy
	cd app && npm run lint && npm run format:check

fmt:              ## 自動整形(ruff format / Prettier)
	cd core && python -m ruff check --fix sentinel_core tests && python -m ruff format sentinel_core tests
	cd app && npm run format

sidecar:          ## コアをPyInstallerでsidecar化(要: pip install pyinstaller)
	python scripts/build_sidecar.py

bundle: sidecar   ## 配布ビルド(.msi/.dmg/.AppImage)
	cd app && npm run tauri build
