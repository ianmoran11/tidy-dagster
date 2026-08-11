import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";

import { configDefaults, defineConfig } from "vitest/config";

import { VITEST_COVERAGE_CONFIG } from "./scripts/testing/coverage-policy";

const { version } = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf8"),
) as { version: string };

const TEST_EXCLUDES = [...configDefaults.exclude, "tests/e2e/**"];
const ASTRO_BUILD_TEST_FILES = [
  "src/components/ConceptDetail.test.ts",
  "src/components/BenchmarkPages.test.ts",
];

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  resolve: {
    alias: {
      "tidybank-workbook-candidate-triage": fileURLToPath(
        new URL(
          "./src/features/coverage/workbookCandidateTriage.tsx",
          import.meta.url,
        ),
      ),
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    coverage: {
      ...VITEST_COVERAGE_CONFIG,
      reporter: [...VITEST_COVERAGE_CONFIG.reporter],
      include: [...VITEST_COVERAGE_CONFIG.include],
      exclude: [...VITEST_COVERAGE_CONFIG.exclude],
    },
    exclude: TEST_EXCLUDES,
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          exclude: [...TEST_EXCLUDES, ...ASTRO_BUILD_TEST_FILES],
        },
      },
      {
        extends: true,
        test: {
          name: "astro-build-pages",
          include: ASTRO_BUILD_TEST_FILES,
          fileParallelism: false,
        },
      },
    ],
  },
});
