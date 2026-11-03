import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

const pkgs = {
  "/backport-updates-dlc/Game [PPSA00001].pkg": { content_id: "UP0000-PPSA00001_00-GAME000000000001", app_ver: "01.00", category: "gd" },
  "/backport-updates-dlc/Have [PPSA00002].pkg": { content_id: "UP0000-PPSA00002_00-GAME000000000002", app_ver: "01.00", category: "gd" },
} as Record<string, { content_id: string; app_ver: string; category: string }>;

test("More › PKG Installer: what the PS5 has of each package, and Install all sends the rest", async ({ page }) => {
  const parsed: string[] = [];
  await page.addInitScript(() => localStorage.setItem("ps5upload.host", "192.168.0.5"));
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname;
    let body: unknown = {};
    if (p === "/api/version") body = { version: "10.7.6", caps: {} };
    if (p === "/api/ps5/status")
      body = { instance_id: 1, prior_instance: "clean", ps5_kernel: "r229358/releases/13.60", ucred_elevated: true, version: "10.7.6" };
    if (p === "/api/ps5/volumes") body = { volumes: [] };
    if (p === "/api/jobs") body = [];
    if (p === "/api/local/storage-roots") body = ["/pkgs", "/backport-updates-dlc"];
    if (p === "/api/local/list-dir")
      body =
        url.searchParams.get("path") === "/backport-updates-dlc"
          ? Object.keys(pkgs).map((path) => ({ name: path.split("/").pop(), path, is_dir: false, size: 1300000 }))
          : [];
    if (p === "/api/pkg/parse-split") {
      const path = (req.postDataJSON() as { path: string }).path;
      parsed.push(path);
      body = { parts: [path], total_size: 1300000, head: { ...pkgs[path], platform: "ps5" } };
    }
    if (p === "/api/pkg/install/preflight") {
      const installed = url.search.includes("PPSA00002");
      body = installed
        ? { state: "installed", title_id: "PPSA00002", category: "gd", installed_version: "01.00", installed_artifacts: [] }
        : { state: "not_installed", title_id: "PPSA00001", category: "gd", installed_version: null, installed_artifacts: [] };
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/more", { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: /PKG Installer/ }).first().click({ timeout: 20_000 });
  await expect(page).toHaveURL(/\/pkg-installer$/);
  await expect(page.getByText("Game [PPSA00001].pkg")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Not installed")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Installed v01.00")).toBeVisible();
  const all = page.getByRole("button", { name: "Install all (1)" });
  await expect(all).toBeEnabled();
  await all.click();
  await expect(page).toHaveURL(/\/send$/);
  // Upload & Install read the handed-over package's header to queue it.
  await expect.poll(() => parsed.filter((x) => x.includes("PPSA00001")).length).toBeGreaterThan(1);
});
