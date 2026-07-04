import { defineConfig } from "vite";

export default defineConfig({
  base: "/tdf-analytics/",
  build: {
    outDir: "build",
    // Clear stale hashed chunks from previous builds; nothing hand-placed
    // lives in build/.
    emptyOutDir: true,
  },
});
