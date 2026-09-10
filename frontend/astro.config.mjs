// @ts-check
import { defineConfig } from "astro/config";
import react from "@astrojs/react";

// Static output on purpose. The Python service owns the data and the agent; Astro only
// builds the interface, and the built files are served by that same Python server. One
// process at demo time instead of two is worth more than server-side rendering here.
export default defineConfig({
  integrations: [react()],
  output: "static",
  outDir: "./dist",
  build: { assets: "assets" },
  server: { port: 4321 },
  vite: {
    server: {
      // During development Astro serves the UI and forwards data calls to Python, so
      // there is no CORS setup and no second origin to configure.
      proxy: {
        "/api": { target: "http://127.0.0.1:8765", changeOrigin: true },
        "/data": { target: "http://127.0.0.1:8765", changeOrigin: true },
      },
    },
  },
});
