import { mkdir, copyFile, access, constants } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const root = path.resolve(__dirname, "..");
const dist = path.resolve(root, "dist");

async function main() {
  await mkdir(dist, { recursive: true });

  const srcManifest = path.resolve(root, "manifest.json");
  const dstManifest = path.resolve(dist, "manifest.json");

  await access(srcManifest, constants.R_OK);
  await copyFile(srcManifest, dstManifest);

  // Optional: copy icons if present (not required for load-unpacked).
  const srcIconsDir = path.resolve(root, "icons");
  try {
    await access(srcIconsDir, constants.R_OK);
    // If you add icons later, expand this script to copy the directory.
  } catch {
    // ignore
  }

  // eslint-disable-next-line no-console
  console.log("Copied manifest.json to dist/");
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error(err);
  process.exitCode = 1;
});

