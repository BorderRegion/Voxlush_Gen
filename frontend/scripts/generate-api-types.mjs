import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const project = resolve(frontend, "..");
const directory = mkdtempSync(join(tmpdir(), "voxlush-openapi-"));
try {
  const schema = execFileSync(
    process.env.VOXLUSH_PYTHON ?? join(project, ".venv/bin/python"),
    [
      "-c",
      "import json; from voxlush.api.app import create_app; from voxlush.core.config import Config; print(json.dumps(create_app(Config()).openapi()))",
    ],
    { cwd: project, encoding: "utf8" },
  );
  const path = join(directory, "openapi.json");
  writeFileSync(path, schema);
  execFileSync(
    process.execPath,
    [
      join(frontend, "node_modules/openapi-typescript/bin/cli.js"),
      path,
      "--output",
      join(frontend, "src/generated/api-schema.ts"),
    ],
    { cwd: frontend, stdio: "inherit" },
  );
  execFileSync(
    process.execPath,
    [
      join(frontend, "node_modules/prettier/bin/prettier.cjs"),
      "--write",
      "src/generated/api-schema.ts",
    ],
    { cwd: frontend, stdio: "inherit" },
  );
} finally {
  rmSync(directory, { recursive: true, force: true });
}
