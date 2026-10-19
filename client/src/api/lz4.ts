import { invoke } from "../lib/invokeLogged";

/** Whether a game is packed with AMPR LZ4 asset packs, can be, or cannot (engine
 *  /api/lz4/status, the converter's own check). */
export type Lz4State =
  /** Already LZ4: `ampr_assets.index` at the game's root. */
  | "packed"
  /** Can be LZ4: it reads through AMPR and its ampr_emu serves packs. */
  | "ok"
  /** Can be LZ4 once ampr_emu 0.4.2.1 goes into it, which Convert does. */
  | "runtime"
  /** It does not read through AMPR, so nothing could serve packs. */
  | "no_ampr"
  /** It could not be read. */
  | "error";

export interface Lz4Status {
  path: string;
  status: Lz4State;
  reason?: string;
  runtime_version?: string;
}


export const lz4 = {
  status: (paths: string[]) =>
    invoke<{ results: Lz4Status[] }>("lz4_status", { paths }).then(
      (r) => r.results,
    ),
};

/** The community's .ffpfsc compatibility list (a Google Sheet, read by the engine), with the
 *  sheet's own column names. */
export interface FfpfscSheet {
  /** The sheet as people open it; empty when the list is turned off. */
  url: string;
  headers: string[];
  rows: Record<string, string>[];
}

export const ffpfscSheet = (refresh = false) =>
  invoke<FfpfscSheet>("lz4_ffpfsc", { refresh });

/** The sheet's rows for one game: by Title ID in any cell, else by name. */
export function ffpfscRowsFor(
  sheet: FfpfscSheet,
  titleId: string,
  name: string,
): Record<string, string>[] {
  const tid = titleId.toUpperCase();
  const byId = sheet.rows.filter(
    (r) => tid && Object.values(r).some((c) => c.toUpperCase().includes(tid)),
  );
  if (byId.length) return byId.slice(0, 5);
  const norm = (s: string) =>
    s
      .toLowerCase()
      .replace(/&/g, "and")
      .replace(/[^a-z0-9]+/g, "");
  const n = norm(name.replace(/\[[^\]]*\]|\([^)]*\)/g, ""));
  if (n.length < 4) return [];
  return sheet.rows
    .filter((r) => Object.values(r).some((c) => norm(c) === n))
    .slice(0, 5);
}

/** A row's filled cells in the sheet's own column order. */
export function ffpfscCells(
  headers: string[],
  row: Record<string, string>,
): [string, string][] {
  return headers.filter((h) => row[h]).map((h) => [h, row[h]]);
}

/** How a sheet cell reads: works, does not, or neither. */
export function ffpfscTone(cell: string): "good" | "bad" | null {
  if (/\b(yes|works?|working|ok|playable|good|fine)\b|✅|✔/i.test(cell))
    return "good";
  if (
    /\b(no|not|crash(es)?|broken|fails?|black screen|doesn'?t|won'?t)\b|❌|✖/i.test(
      cell,
    )
  )
    return "bad";
  return null;
}

export function canBeLz4(s: Lz4State | undefined): boolean {
  return s === "ok" || s === "runtime";
}

/** Game reports players file as "[Game report]" issues on the LZ4 Compression project's own
 *  site (it left GitHub on 2026-10-17), counted per game by the engine, as ps5-lz4 does. */
export const COMPAT_REPO = "theghostonline/PS5-LZ4-Compression";
export const COMPAT_SITE = `https://theghostonline.dev/${COMPAT_REPO}`;

export type CompatStatus = "works" | "issues" | "noStart" | "crash";

export interface CompatReport {
  status: CompatStatus;
  game?: string;
  gameVersion?: string;
  level?: string;
  source?: string;
  firmware?: string;
  appVersion?: string;
  date?: string;
  /** The GitHub issue number. */
  issue?: number;
}

export interface CompatEntry {
  name?: string;
  works: number;
  issues: number;
  noStart: number;
  crash: number;
  reports: number;
  lastReport?: CompatReport;
}

export interface CompatData {
  updated?: string;
  /** `live` (the site's issues) or `mirror` (ps5-lz4-nas's copy). */
  source?: string;
  /** The project's page on its site. */
  site?: string;
  games: Record<string, CompatEntry>;
}

/** The reports, read by the engine at most once a day (now, with `refresh`). */
export async function fetchCompat(refresh = false): Promise<CompatData> {
  const data = await invoke<Partial<CompatData>>("lz4_compat", { refresh });
  return {
    updated: data.updated,
    source: data.source,
    site: data.site,
    games: data.games ?? {},
  };
}

/** How the reports for one game come out overall: everyone can play it, some can, or nobody
 *  can (it does not start or it crashes). */
export function compatVerdict(e: CompatEntry): "good" | "mixed" | "bad" {
  const playing = e.works + e.issues;
  const broken = e.noStart + e.crash;
  if (playing && !broken) return "good";
  if (!playing) return "bad";
  return broken > playing ? "bad" : "mixed";
}

export function compatIssueUrl(issue: number, site = COMPAT_SITE): string {
  return `${site}/issues/${issue}`;
}

/** A new "[Game report]" issue for one game, filled in with the report form's sections (the
 *  same "### Field" headings the engine counts), as ps5-lz4 opens it. */
export function compatReportUrl(
  titleId: string,
  name: string,
  site = COMPAT_SITE,
): string {
  const rows: [string, string][] = [
    ["Title ID", titleId],
    ["Game", name.slice(0, 80)],
    ["How does it run?", ""],
    ["Game version", ""],
    ["LZ4 level", ""],
    ["Packed from", ""],
    ["Firmware", ""],
    ["LZ4 Compression version", ""],
    ["Notes", ""],
  ];
  const body = rows
    .map(([k, v]) => `### ${k}\n\n${v || "_No response_"}`)
    .join("\n\n");
  const params = new URLSearchParams({
    title: `[Game report] ${name || titleId}`,
    body,
  });
  return `${site}/issues/new?${params.toString()}`;
}
