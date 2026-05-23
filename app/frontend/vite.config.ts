import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite dev server must run on the port the sidecar's CORS allow-list expects
// (see app/sidecar/sidecar/main.py). 1420 is the Tauri-recommended dev port.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
  },
  build: {
    target: "esnext",
    sourcemap: true,
    outDir: "dist",
  },
});
