import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target:
          loadEnv(mode, ".", "VOXLUSH_").VOXLUSH_API_PROXY ??
          (mode === "e2e" ? "http://127.0.0.1:8067" : "http://127.0.0.1:8740"),
        changeOrigin: false,
      },
    },
  },
  build: { sourcemap: false },
}));
