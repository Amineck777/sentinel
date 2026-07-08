import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Tauri開発時もViteをそのまま使う(実装方針 §1: ブラウザ/Tauri両立)
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  clearScreen: false,
});
