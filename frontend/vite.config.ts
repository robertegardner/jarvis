import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets are served by FastAPI from /; use relative base so paths resolve
// regardless of where the app is mounted. In dev, proxy the API + WebSocket to
// the Python backend (default 0.0.0.0:8765) so the SPA and backend share an origin.
const backend = process.env.JARVIS_BACKEND || "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend, ws: true, changeOrigin: true },
    },
  },
});
