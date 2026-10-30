import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

test("Files uploads device files into the open PS5 folder", async ({ page }) => {
  const transfers: Record<string, unknown>[] = [];
  let staged = 0;
  await page.addInitScript(() => localStorage.setItem("ps5upload.host", "192.168.0.5"));
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const p = url.pathname;
    let body: unknown = {};
    if (p === "/api/version") body = { version: "8.1.0", caps: {} };
    if (p === "/api/ps5/status")
      body = {
        instance_id: 1,
        prior_instance: "clean",
        ps5_kernel: "r229358/releases/13.60 Jul 17 2026 02:16:29",
        ucred_elevated: true,
        version: "8.1.0",
      };
    if (p === "/api/ps5/volumes") body = { volumes: [] };
    if (p === "/api/ps5/list-dir") body = { path: url.searchParams.get("path"), entries: [], truncated: false };
    if (p === "/api/local/path-kind") body = { kind: "file" };
    if (p === "/api/files/upload") {
      const name = staged++ === 0 ? "notes.txt" : "archive.zip";
      expect(request.postDataBuffer()?.toString()).toContain(name);
      body = { upload_id: `upload-${staged}`, path: `/tmp/upload-${staged}/${name}`, filename: name, size: 5 };
    }
    if (p === "/api/transfer/file-list") {
      transfers.push(request.postDataJSON());
      body = { job_id: "device-job" };
    }
    if (p === "/api/jobs/device-job") body = { status: "running", bytes_sent: 1, total_bytes: 10 };
    if (p === "/api/jobs") body = [];
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/files?path=%2Fdata%2Fhomebrew", { waitUntil: "domcontentloaded" });
  const picker = page.getByRole("button", { name: "From this device…", exact: true });
  await expect(picker).toBeEnabled({ timeout: 20_000 });
  const chooser = page.waitForEvent("filechooser");
  await picker.click();
  await (await chooser).setFiles([
    { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") },
    { name: "archive.zip", mimeType: "application/zip", buffer: Buffer.from("bytes") },
  ]);
  await expect.poll(() => transfers.length).toBe(1);
  expect(staged).toBe(2);
  expect(transfers[0]).toMatchObject({
    addr: "192.168.0.5", dest_root: "/data/homebrew",
    files: [
      { src: "/tmp/upload-1/notes.txt", dest: "/data/homebrew/notes.txt" },
      { src: "/tmp/upload-2/archive.zip", dest: "/data/homebrew/archive.zip" },
    ],
  });
  await expect(page.getByTestId("fs-upload-progress")).toBeVisible();
});

test("the engine's copies of the phone's files are deleted once they are on the PS5", async ({ page }) => {
  const deleted: string[] = [];
  let staged = 0;
  await page.addInitScript(() => localStorage.setItem("ps5upload.host", "192.168.0.5"));
  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const p = url.pathname;
    let body: unknown = {};
    if (p === "/api/version") body = { version: "8.1.0", caps: {} };
    if (p === "/api/ps5/status")
      body = {
        instance_id: 1,
        prior_instance: "clean",
        ps5_kernel: "r229358/releases/13.60 Jul 17 2026 02:16:29",
        ucred_elevated: true,
        version: "8.1.0",
      };
    if (p === "/api/ps5/volumes") body = { volumes: [] };
    if (p === "/api/ps5/list-dir") body = { path: url.searchParams.get("path"), entries: [], truncated: false };
    if (p === "/api/local/path-kind") body = { kind: "file" };
    if (p === "/api/files/upload") {
      staged++;
      body = { upload_id: `upload-${staged}`, path: `/tmp/upload-${staged}/photo-${staged}.jpg`, filename: `photo-${staged}.jpg`, size: 5 };
    }
    if (p.startsWith("/api/files/upload/") || p.startsWith("/api/pkg/upload/")) {
      if (request.method() === "DELETE") deleted.push(p.split("/").pop() ?? "");
      body = { removed: true };
    }
    if (p === "/api/transfer/file-list") body = { job_id: "device-job" };
    if (p === "/api/jobs/device-job")
      body = { status: "done", bytes_sent: 10, total_bytes: 10, files_sent: 2 };
    if (p === "/api/jobs") body = [];
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/files?path=%2Fdata%2Fhomebrew", { waitUntil: "domcontentloaded" });
  const picker = page.getByRole("button", { name: "From this device…", exact: true });
  await expect(picker).toBeEnabled({ timeout: 20_000 });
  const chooser = page.waitForEvent("filechooser");
  await picker.click();
  await (await chooser).setFiles([
    { name: "photo-1.jpg", mimeType: "image/jpeg", buffer: Buffer.from("hello") },
    { name: "photo-2.jpg", mimeType: "image/jpeg", buffer: Buffer.from("world") },
  ]);
  await expect.poll(() => [...deleted].sort(), { timeout: 20_000 }).toEqual(["upload-1", "upload-2"]);
});
