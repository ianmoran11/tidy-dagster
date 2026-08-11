import path from "node:path";
import { defineConfig } from "vitest/config";

const requestedRoot = process.env.TIDY_SOURCE_REPLAY_ROOT;
if (!requestedRoot) throw new Error("TIDY_SOURCE_REPLAY_ROOT is required");
const root = path.resolve(requestedRoot);
process.chdir(root);

export default defineConfig({
  root,
  resolve: {
    alias: {
      "@": path.join(root, "src"),
    },
  },
  test: {
    environment: "node",
  },
});
