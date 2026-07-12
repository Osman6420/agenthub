/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The builder ships as static assets Django serves same-origin from
// apps/builder/static/builder/. Fixed (unhashed) filenames let the Django template
// reference them via {% static %} without a manifest step. The Python runtime never
// depends on this output existing; the console page degrades gracefully without it.
export default defineConfig({
  plugins: [react()],
  base: "/static/builder/",
  build: {
    outDir: "../apps/builder/static/builder",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "builder.js",
        assetFileNames: (info) =>
          info.name && info.name.endsWith(".css") ? "builder.css" : "assets/[name][extname]",
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
