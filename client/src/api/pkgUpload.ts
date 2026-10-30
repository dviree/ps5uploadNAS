import { getEngineUrl } from "../state/engine";

export interface BrowserPkgUpload {
  uploadId: string;
  path: string;
  filename: string;
  size: number;
}

async function responseError(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as {
    error?: unknown;
  } | null;
  return body?.error ? String(body.error) : `engine HTTP ${response.status}`;
}

/**
 * Put a browser-selected package on the engine host. Browsers cannot hand the
 * engine a local filesystem path, while the desktop shell can. The returned
 * path is therefore temporary and must be paired with `deleteBrowserPkgUpload`
 * after both the direct Stream attempt and any staged fallback have finished.
 */
export async function stageBrowserPkg(file: File): Promise<BrowserPkgUpload> {
  return stageBrowserFileAt(file, "/api/pkg/upload");
}

/** Stage any browser-selected file for the normal Upload review. `onProgress`: bytes of this
 *  file the engine has received so far, out of its size (a phone's file can take minutes). */
export async function stageBrowserFile(
  file: File,
  onProgress?: (sent: number, total: number) => void,
): Promise<BrowserPkgUpload> {
  return stageBrowserFileAt(file, "/api/files/upload", onProgress);
}

/** POST a form, reporting upload progress (fetch cannot), answered like fetch's Response. */
function postWithProgress(
  url: string,
  form: FormData,
  onProgress: (sent: number, total: number) => void,
): Promise<Response> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total);
    };
    xhr.onload = () =>
      resolve(new Response(xhr.responseText, { status: xhr.status }));
    xhr.onerror = () => reject(new Error("upload to the engine failed (connection lost)"));
    xhr.onabort = () => reject(new Error("upload to the engine was cancelled"));
    xhr.send(form);
  });
}

async function stageBrowserFileAt(
  file: File,
  endpoint: string,
  onProgress?: (sent: number, total: number) => void,
): Promise<BrowserPkgUpload> {
  const form = new FormData();
  form.append(endpoint === "/api/pkg/upload" ? "pkg" : "file", file, file.name);
  const url = `${getEngineUrl()}${endpoint}`;
  const response = onProgress
    ? await postWithProgress(url, form, onProgress)
    : await fetch(url, { method: "POST", body: form });
  if (!response.ok) throw new Error(await responseError(response));
  const body = (await response.json()) as {
    upload_id?: unknown;
    path?: unknown;
    filename?: unknown;
    size?: unknown;
  };
  if (typeof body.upload_id !== "string" || typeof body.path !== "string") {
    throw new Error("engine returned an invalid package-upload response");
  }
  return {
    uploadId: body.upload_id,
    path: body.path,
    filename:
      typeof body.filename === "string" ? body.filename : file.name,
    size: typeof body.size === "number" ? body.size : file.size,
  };
}

/** Idempotent cleanup for temporary browser staging. */
export async function deleteBrowserPkgUpload(uploadId: string): Promise<void> {
  const response = await fetch(
    `${getEngineUrl()}/api/pkg/upload/${encodeURIComponent(uploadId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) throw new Error(await responseError(response));
}
