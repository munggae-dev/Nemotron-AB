#!/usr/bin/env node
/**
 * 정적 데모 빌드 (GitHub Pages 등).
 * Route Handler(/nemotron-mock-api)는 static export와 양립하지 않아 빌드 중 임시 제거합니다.
 */
import { rename, rm, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const mockApiDir = path.join(frontendRoot, "app", "nemotron-mock-api");
/** app/ 밖으로 옮겨야 Next가 라우트로 인식하지 않음 */
const mockApiBak = path.join(frontendRoot, ".nemotron-mock-api.off");

async function hideMockRoute() {
  try {
    await rename(mockApiDir, mockApiBak);
    return true;
  } catch (e) {
    if (e && typeof e === "object" && "code" in e && e.code === "ENOENT") return false;
    throw e;
  }
}

async function restoreMockRoute() {
  try {
    await rename(mockApiBak, mockApiDir);
  } catch (e) {
    if (e && typeof e === "object" && "code" in e && e.code === "ENOENT") return;
    throw e;
  }
}

function runBuild() {
  return new Promise((resolve, reject) => {
    const child = spawn("npm", ["run", "build"], {
      cwd: frontendRoot,
      stdio: "inherit",
      env: {
        ...process.env,
        NEXT_PUBLIC_DEMO_MODE: "1",
        NEXT_PUBLIC_DEMO_STATIC: "1",
      },
    });
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`build exited ${code}`))));
  });
}

async function main() {
  await rm(path.join(frontendRoot, ".next"), { recursive: true, force: true });
  const hidden = await hideMockRoute();
  try {
    await runBuild();
    const outDir = path.join(frontendRoot, "out");
    await writeFile(path.join(outDir, ".nojekyll"), "\n");
    console.log("\n✓ Static demo built → frontend/out/");
    if (process.env.NEXT_PUBLIC_BASE_PATH) {
      console.log(`  basePath: ${process.env.NEXT_PUBLIC_BASE_PATH}`);
    } else {
      console.log("  GitHub Pages 프로젝트 사이트면: NEXT_PUBLIC_BASE_PATH=/저장소이름 npm run build:demo:static");
    }
  } finally {
    if (hidden) await restoreMockRoute();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
