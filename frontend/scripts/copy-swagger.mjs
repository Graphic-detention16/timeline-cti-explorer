import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceDirectory = resolve(projectDirectory, "node_modules/swagger-ui-dist");
const targetDirectory = resolve(projectDirectory, "dist/swagger");

mkdirSync(targetDirectory, { recursive: true });
for (const asset of ["swagger-ui-bundle.js", "swagger-ui.css"]) {
  copyFileSync(resolve(sourceDirectory, asset), resolve(targetDirectory, asset));
}
