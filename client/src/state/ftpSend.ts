import { create } from "zustand";

import { invoke } from "../lib/invokeLogged";
import { jobStatus } from "../api/ps5";
import { useConnectionStore } from "./connection";
import { useConvertPrefs } from "./convertPrefs";

/** A game sent to the PS5 through its own FTP server (etaHEN / ftpsrv), as ps5-lz4 sends
 *  games: for when the PS5Upload payload is not loaded. The engine does the sending as a
 *  job; this follows it. Keyed by the source path, kept for the session. */
export interface FtpSend {
  jobId: string | null;
  /** Where it goes on the PS5. */
  dest: string;
  status: "running" | "done" | "failed";
  bytes: number;
  total: number;
  error?: string;
}

export const useFtpSends = create<Record<string, FtpSend>>(() => ({}));

function put(source: string, patch: Partial<FtpSend>) {
  useFtpSends.setState((s) => ({
    [source]: { ...(s[source] ?? { jobId: null, dest: "", status: "running", bytes: 0, total: 0 }), ...patch },
  }));
}

/** `host:port` → [host, port]; the port is 2121 (etaHEN, ftpsrv) when left out. */
export function parseFtpAddr(addr: string): [string, number] {
  const a = addr.trim();
  const m = /^(.+):(\d{1,5})$/.exec(a);
  return m ? [m[1], Number(m[2])] : [a, 2121];
}

/** The PS5's FTP address: the one set under My games, else the connected console's. */
export function ftpAddr(): string {
  const set = useConvertPrefs.getState().ftpAddr.trim();
  if (set) return set;
  const host = useConnectionStore.getState().host?.trim() ?? "";
  return host ? `${parseFtpAddr(host)[0]}:2121` : "";
}

export async function sendViaFtp(source: string): Promise<void> {
  const addr = ftpAddr();
  const destDir = useConvertPrefs.getState().ftpDest.trim() || "/data/homebrew";
  if (useFtpSends.getState()[source]?.status === "running") return;
  if (!addr) {
    put(source, { status: "failed", error: "Set the PS5's FTP address first (like 192.168.1.20:2121)." });
    return;
  }
  const [host, port] = parseFtpAddr(addr);
  put(source, { jobId: null, dest: destDir, status: "running", bytes: 0, total: 0, error: undefined });
  try {
    const { job_id, dest } = await invoke<{ job_id: string; dest: string }>("ftp_send", {
      source,
      addr: host,
      port,
      destDir,
    });
    put(source, { jobId: job_id, dest });
    await follow(source, job_id);
  } catch (e) {
    put(source, { status: "failed", error: e instanceof Error ? e.message : String(e) });
  }
}

async function follow(source: string, jobId: string) {
  let misses = 0;
  for (;;) {
    await new Promise((r) => setTimeout(r, 1000));
    let s;
    try {
      s = await jobStatus(jobId);
      misses = 0;
    } catch (e) {
      // The send goes on in the engine; only a long silence ends following it.
      if (++misses >= 30) throw e;
      continue;
    }
    if (s.status === "running") {
      put(source, { bytes: s.bytes_sent ?? 0, total: s.total_bytes ?? 0 });
      continue;
    }
    if (s.status === "done") {
      put(source, { status: "done", bytes: s.bytes_sent ?? 0, total: s.bytes_sent ?? 0, dest: s.dest ?? "" });
    } else {
      put(source, { status: "failed", error: s.error ?? "the send failed" });
    }
    return;
  }
}
