import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

test("More › PKG Installer lists the server's packages and Install hands one to Upload & Install", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("ps5upload.host", "192.168.0.5"));
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    let body: unknown = {};
    if (p === "/api/version") body = { version: "10.7.6", caps: {} };
    if (p === "/api/ps5/status")
      body = { instance_id: 1, prior_instance: "clean", ps5_kernel: "r229358/releases/13.60", ucred_elevated: true, version: "10.7.6" };
    if (p === "/api/ps5/volumes") body = { volumes: [] };
    if (p === "/api/jobs") body = [];
    if (p === "/api/local/storage-roots") body = ["/pkgs", "/backport-updates-dlc"];
    if (p === "/api/local/list-dir") {
      const dir = url.searchParams.get("path");
      body =
        dir === "/backport-updates-dlc"
          ? [{ name: "Ghost [PPSA26344] [DLC].pkg", path: "/backport-updates-dlc/Ghost [PPSA26344] [DLC].pkg", is_dir: false, size: 1300000 }]
          : [];
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/more", { waitUntil: "domcontentloaded" });
  await page.getByRole("link", { name: /PKG Installer/ }).first().click({ timeout: 20_000 });
  await expect(page).toHaveURL(/\/pkg-installer$/);
  await expect(page.getByText("Ghost [PPSA26344] [DLC].pkg")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("/backport-updates-dlc", { exact: false }).first()).toBeVisible();
  const install = page.getByRole("button", { name: "Install", exact: true });
  await expect(install).toBeEnabled({ timeout: 20_000 });
  await install.click();
  await expect(page).toHaveURL(/\/send$/);
});
