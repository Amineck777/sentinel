import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

/**
 * 開発サーバー専用: 手元の VRM を /__avatar/model.vrm で返す。
 * モデルは配布規約上リポジトリに入れられない(ADR 0109)ので、場所だけを
 * app/.env.local の SENTINEL_AVATAR_VRM(またはシェルの環境変数)で教える。
 */
function localAvatarModel(modelPath: string | undefined): Plugin {
  return {
    name: "sentinel-local-avatar-model",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/__avatar/model.vrm", (_req, res) => {
        if (!modelPath || !fs.existsSync(modelPath)) {
          res.statusCode = 404;
          res.end("SENTINEL_AVATAR_VRM is not set or the file does not exist");
          return;
        }
        res.setHeader("Content-Type", "model/gltf-binary");
        res.setHeader("Cache-Control", "no-store");
        fs.createReadStream(modelPath).pipe(res);
      });
    },
  };
}

// Tauri開発時もViteをそのまま使う(実装方針 §1: ブラウザ/Tauri両立)
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL(".", import.meta.url)), "SENTINEL_");
  return {
    plugins: [react(), localAvatarModel(env.SENTINEL_AVATAR_VRM)],
    server: { port: 5173, strictPort: true },
    clearScreen: false,
    build: {
      rollupOptions: {
        // チャット画面とアバター試作ページの2ページ構成
        input: {
          main: fileURLToPath(new URL("index.html", import.meta.url)),
          avatar: fileURLToPath(new URL("avatar.html", import.meta.url)),
        },
      },
    },
  };
});
