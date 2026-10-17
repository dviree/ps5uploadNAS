// Convert Games' My games: the PS5 games already in your library folders (roms/ps5, added in
// Collection), each with whether it is LZ4 already, can be, or cannot, and what other players
// report. Convert to LZ4 opens the converter on that game with LZ4 asset packs on.

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { FolderPlus, Gamepad2, RefreshCw, Search } from "lucide-react";

import {
  canBeLz4,
  compatReportUrl,
  compatVerdict,
  ffpfscCells,
  ffpfscRowsFor,
  ffpfscTone,
  lz4,
  type CompatEntry,
  type Lz4State,
  type Lz4Status,
} from "../../api/lz4";
import type { CollectionGame, CollectionLocation } from "../../api/collection";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Select,
  Spinner,
} from "../../components";
import { formatCollectionBytes, locationKind } from "../../lib/collectionView";
import { openExternalUrl } from "../../lib/openExternalUrl";
import {
  collectionGames,
  loadCollection,
  startCollectionScan,
  useCollectionStore,
} from "../../state/collection";
import { useConvertPrefs } from "../../state/convertPrefs";
import { useTr } from "../../state/lang";
import {
  loadFfpfscSheet,
  loadLz4Compat,
  useFfpfscSheet,
  useLz4Compat,
} from "../../state/lz4Compat";
import { CollectionCover } from "../Collection/CollectionCover";

/** What the converter can read and write LZ4 packs for: a game folder or a game image. */
const CONVERTIBLE = new Set([
  "folder",
  "mount.exfat",
  "mount.ffpkg",
  "mount.ffpfs",
  "mount.ffpfsc",
]);

type Filter = "all" | "can" | "packed" | "no";

interface Row {
  game: CollectionGame;
  loc: CollectionLocation;
}

/** Statuses by path, kept for the session so switching tabs does not read every game again. */
const known = new Map<string, Lz4Status>();

export function MyGames({
  onConvert,
  onFfpfsc,
}: {
  onConvert: (path: string) => void;
  /** Compress the game into a .ffpfsc instead (`isFolder`: a game folder, not an image). */
  onFfpfsc: (path: string, isFolder: boolean) => void;
}) {
  const tr = useTr();
  const navigate = useNavigate();
  const library = useCollectionStore((s) => s.library);
  const loading = useCollectionStore((s) => s.loading);
  const scanning = useCollectionStore((s) => s.scan?.running ?? false);
  const compat = useLz4Compat((s) => s.data);
  const sheet = useFfpfscSheet((s) => s.sheet);
  const lz4Dir = useConvertPrefs((s) => s.lz4Dir);
  const setLz4Dir = useConvertPrefs((s) => s.setLz4Dir);
  const [statuses, setStatuses] = useState<Record<string, Lz4Status>>(() =>
    Object.fromEntries(known),
  );
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [root, setRoot] = useState("");

  useEffect(() => {
    if (!useCollectionStore.getState().library) void loadCollection();
    void loadLz4Compat();
    void loadFfpfscSheet();
  }, []);

  const rows: Row[] = useMemo(
    () =>
      collectionGames(library)
        .filter((g) => g.platform.toUpperCase() === "PS5")
        .flatMap((game) =>
          game.locations
            .filter((loc) => CONVERTIBLE.has(loc.type) && loc.absolute_path)
            .map((loc) => ({ game, loc })),
        )
        .sort((a, b) => a.game.title.localeCompare(b.game.title)),
    [library],
  );
  const roots = useMemo(
    () => [...new Set(rows.map((r) => r.loc.root))].sort(),
    [rows],
  );

  // Read each game's LZ4 status one at a time, so the list fills in as it goes: a large image
  // on a NAS disk can take a while to read, and one that fails is marked, not left checking.
  useEffect(() => {
    const todo = rows
      .map((r) => r.loc.absolute_path)
      .filter((p) => !known.has(p));
    if (todo.length === 0) return;
    let live = true;
    void (async () => {
      for (const path of todo) {
        if (!live) return;
        try {
          for (const s of await lz4.status([path])) known.set(s.path, s);
        } catch (e) {
          known.set(path, {
            path,
            status: "error",
            reason: e instanceof Error ? e.message : String(e),
          });
        }
        if (live) setStatuses(Object.fromEntries(known));
      }
    })();
    return () => {
      live = false;
    };
  }, [rows]);

  const ffpfscFor = (g: CollectionGame): [string, string][] | null => {
    const hit = sheet && ffpfscRowsFor(sheet, g.game_id, g.title)[0];
    return sheet && hit ? ffpfscCells(sheet.headers, hit) : null;
  };
  const stateOf = (r: Row): Lz4State | undefined =>
    statuses[r.loc.absolute_path]?.status;

  const q = search.trim().toLowerCase();
  const shown = rows.filter((r) => {
    if (root && r.loc.root !== root) return false;
    if (q && !`${r.game.title} ${r.game.game_id}`.toLowerCase().includes(q))
      return false;
    const s = stateOf(r);
    if (filter === "can") return canBeLz4(s);
    if (filter === "packed") return s === "packed";
    if (filter === "no") return s === "no_ampr" || s === "error";
    return true;
  });

  const inRoot = rows.filter((r) => !root || r.loc.root === root);
  const packed = inRoot.filter((r) => stateOf(r) === "packed").length;
  const can = inRoot.filter((r) => canBeLz4(stateOf(r)));
  const canBytes = can.reduce((n, r) => n + r.loc.size_bytes, 0);
  const checking = inRoot.filter((r) => stateOf(r) === undefined).length;

  if (!library && loading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }
  if (!library?.roots?.length) {
    return (
      <EmptyState
        icon={FolderPlus}
        title={tr(
          "lz4mine.no_roots_title",
          undefined,
          "Add your games folder first",
        )}
        message={tr(
          "lz4mine.no_roots_body",
          undefined,
          "My games lists the PS5 games in your library folders, such as roms/ps5. Add that folder in Collection; it is scanned in place.",
        )}
        action={
          <Button onClick={() => navigate("/collection")}>
            {tr("lz4mine.open_collection", undefined, "Open Collection")}
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="lz4-my-games">
      <div className="grid grid-cols-3 gap-2 sm:gap-3">
        <Kpi
          value={String(packed)}
          label={tr("lz4mine.kpi_packed", undefined, "games LZ4 packed")}
        />
        <Kpi
          value={String(can.length)}
          label={tr("lz4mine.kpi_can", undefined, "games that can be LZ4")}
          accent
        />
        <Kpi
          value={formatCollectionBytes(canBytes)}
          label={
            checking
              ? tr(
                  "lz4mine.kpi_checking",
                  { n: checking },
                  "to pack · checking {n} more…",
                )
              : tr(
                  "lz4mine.kpi_bytes",
                  undefined,
                  "of games that can still be LZ4",
                )
          }
        />
      </div>

      <Card>
        <div className="flex flex-col gap-3">
          <div className="grid items-center gap-2 sm:grid-flow-col sm:grid-cols-[minmax(0,1fr)] sm:auto-cols-[minmax(9rem,13rem)]">
            <div className="min-w-0">
              <Input
                aria-label={tr("lz4mine.search", undefined, "Search games")}
                placeholder={tr("lz4mine.search", undefined, "Search games")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                leftIcon={<Search size={14} />}
              />
            </div>
            <Select
              aria-label={tr("lz4mine.filter", undefined, "Show")}
              value={filter}
              onChange={(e) => setFilter(e.target.value as Filter)}
              options={[
                {
                  value: "all",
                  label: tr("lz4mine.f_all", undefined, "All games"),
                },
                {
                  value: "can",
                  label: tr("lz4mine.f_can", undefined, "Can be LZ4"),
                },
                {
                  value: "packed",
                  label: tr("lz4mine.f_packed", undefined, "LZ4"),
                },
                {
                  value: "no",
                  label: tr("lz4mine.f_no", undefined, "Not LZ4"),
                },
              ]}
            />
            {roots.length > 1 && (
              <Select
                aria-label={tr("lz4mine.folder", undefined, "Folder")}
                value={root}
                onChange={(e) => setRoot(e.target.value)}
                options={[
                  {
                    value: "",
                    label: tr("lz4mine.all_folders", undefined, "All folders"),
                  },
                  ...roots.map((r) => ({ value: r, label: r })),
                ]}
              />
            )}
            <Button
              variant="ghost"
              leftIcon={<RefreshCw size={14} />}
              disabled={scanning}
              onClick={() => void startCollectionScan()}
            >
              {scanning
                ? tr("lz4mine.scanning", undefined, "Scanning…")
                : tr("lz4mine.rescan", undefined, "Scan folders")}
            </Button>
          </div>

          <Input
            label={tr("lz4mine.lz4_dir", undefined, "LZ4 folder")}
            hint={tr(
              "lz4mine.lz4_dir_hint",
              undefined,
              "Games converted to LZ4 are saved here as game folders (name-lz4), like ps5-lz4's LZ4 folder. In the Docker setup it is /lz4. Empty: the output folder under Convert.",
            )}
            value={lz4Dir}
            onChange={(e) => setLz4Dir(e.target.value)}
            spellCheck={false}
          />

          {shown.length === 0 ? (
            <EmptyState
              icon={Gamepad2}
              title={
                rows.length === 0
                  ? tr("lz4mine.none_title", undefined, "No PS5 games found")
                  : tr("lz4mine.none_match", undefined, "No games match")
              }
              message={
                rows.length === 0
                  ? tr(
                      "lz4mine.none_body",
                      undefined,
                      "Game folders and images (.exfat, .ffpfs, .ffpfsc) of PS5 games in your library folders show up here after a scan.",
                    )
                  : undefined
              }
            />
          ) : (
            <ul className="divide-y divide-[var(--color-border)]">
              {shown.map((r) => (
                <GameRow
                  key={r.loc.absolute_path}
                  row={r}
                  state={stateOf(r)}
                  status={statuses[r.loc.absolute_path]}
                  compat={compat?.games[r.game.game_id]}
                  ffpfsc={ffpfscFor(r.game)}
                  onConvert={() => onConvert(r.loc.absolute_path)}
                  onFfpfsc={() => onFfpfsc(r.loc.absolute_path, r.loc.type === "folder")}
                />
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}

function Kpi({
  value,
  label,
  accent = false,
}: {
  value: string;
  label: string;
  accent?: boolean;
}) {
  return (
    <Card>
      <div
        className={`text-lg font-bold tabular-nums sm:text-2xl ${accent ? "text-[var(--color-accent)]" : ""}`}
      >
        {value}
      </div>
      <div className="text-xs text-[var(--color-muted)] sm:text-sm">
        {label}
      </div>
    </Card>
  );
}

function GameRow({
  row,
  state,
  status,
  compat,
  ffpfsc,
  onConvert,
  onFfpfsc,
}: {
  row: Row;
  state: Lz4State | undefined;
  status: Lz4Status | undefined;
  compat: CompatEntry | undefined;
  /** The game's row in the community's .ffpfsc list, in the sheet's column order. */
  ffpfsc: [string, string][] | null;
  onConvert: () => void;
  onFfpfsc: () => void;
}) {
  const tr = useTr();
  const { game, loc } = row;
  return (
    <li
      className="flex flex-wrap items-center gap-3 py-3"
      data-testid="lz4-game-row"
    >
      <div className="h-11 w-11 shrink-0 overflow-hidden rounded-lg">
        <CollectionCover game={game} className="h-full w-full" />
      </div>
      <div className="min-w-0 flex-[1_1_240px]">
        <div className="truncate font-semibold" title={loc.absolute_path}>
          {game.title}
        </div>
        <div className="truncate text-xs text-[var(--color-muted)]">
          {game.game_id} · {locationKind(loc.type)} ·{" "}
          {formatCollectionBytes(loc.size_bytes)}
        </div>
        <CommunityLine compat={compat} />
        <FfpfscLine cells={ffpfsc} />
      </div>
      <div className="flex shrink-0 flex-col items-start gap-1">
        <StateBadge state={state} status={status} />
      </div>
      <div className="flex shrink-0 gap-2">
        {canBeLz4(state) && (
          <Button size="sm" onClick={onConvert}>
            {tr("lz4mine.convert", undefined, "Convert to LZ4")}
          </Button>
        )}
        {/* An image or folder can always be compressed instead; an .ffpfs/.ffpfsc is one. */}
        {(loc.type === "folder" || loc.type === "mount.exfat" || loc.type === "mount.ffpkg") &&
          state !== "packed" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onFfpfsc}
              title={tr(
                "lz4mine.ffpfsc_hint",
                undefined,
                "Compress the game into a .ffpfsc image (PFSC) in the output folder under Convert; the original is only read.",
              )}
            >
              {tr("lz4mine.ffpfsc", undefined, "Convert to .ffpfsc")}
            </Button>
          )}
        {state === "packed" && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() =>
              void openExternalUrl(compatReportUrl(game.game_id, game.title))
            }
          >
            {tr("lz4mine.report", undefined, "Report how it runs")}
          </Button>
        )}
      </div>
    </li>
  );
}

function StateBadge({
  state,
  status,
}: {
  state: Lz4State | undefined;
  status?: Lz4Status;
}) {
  const tr = useTr();
  switch (state) {
    case "packed":
      return (
        <Badge tone="good">{tr("lz4mine.s_packed", undefined, "LZ4")}</Badge>
      );
    case "ok":
      return (
        <Badge tone="accent">
          {tr("lz4mine.s_can", undefined, "can be LZ4")}
        </Badge>
      );
    case "runtime":
      return (
        <Badge
          tone="accent"
          title={tr(
            "lz4mine.s_runtime_hint",
            undefined,
            "Convert to LZ4 puts ampr_emu 0.4.2.1, the APR-EMU build that reads LZ4 packs, into the LZ4 copy (the original is not touched).",
          )}
        >
          {tr("lz4mine.s_can_runtime", undefined, "can be LZ4 (adds APR-EMU)")}
        </Badge>
      );
    case "no_ampr":
      return (
        <Badge tone="neutral" title={status?.reason}>
          {tr("lz4mine.s_no", undefined, "not LZ4: no AMPR")}
        </Badge>
      );
    case "error":
      return (
        <Badge tone="bad" title={status?.reason}>
          {tr("lz4mine.s_error", undefined, "could not read")}
        </Badge>
      );
    default:
      return (
        <span className="flex items-center gap-1.5 text-xs text-[var(--color-muted)]">
          <Spinner size={12} />
          {tr("lz4mine.s_checking", undefined, "checking…")}
        </span>
      );
  }
}

function CommunityLine({ compat }: { compat: CompatEntry | undefined }) {
  const tr = useTr();
  if (!compat?.reports) {
    return (
      <div className="text-xs text-[var(--color-muted)]">
        {tr("lz4mine.no_reports", undefined, "no reports")}
      </div>
    );
  }
  const verdict = compatVerdict(compat);
  const playing = compat.works + compat.issues;
  const color =
    verdict === "good"
      ? "text-[var(--color-good)]"
      : verdict === "bad"
        ? "text-[var(--color-bad)]"
        : "text-[var(--color-warn)]";
  return (
    <div className={`text-xs ${color}`}>
      {tr(
        "lz4mine.reports",
        { playing, count: compat.reports },
        "community: plays for {playing} of {count}",
      )}
    </div>
  );
}

/** What the community's .ffpfsc list says about the game: its row's cells, coloured where a
 *  cell reads as works or not. */
function FfpfscLine({ cells: all }: { cells: [string, string][] | null }) {
  const tr = useTr();
  if (!all?.length) return null;
  const cells = all.filter(([, v]) => !/^[A-Z]{4}\d{5}$/.test(v));
  const tones = cells.map(([, v]) => ffpfscTone(v));
  const tone = tones.includes("bad")
    ? "bad"
    : tones.includes("good")
      ? "good"
      : null;
  const color =
    tone === "good"
      ? "text-[var(--color-good)]"
      : tone === "bad"
        ? "text-[var(--color-bad)]"
        : "text-[var(--color-muted)]";
  return (
    <div
      className={`truncate text-xs ${color}`}
      title={cells.map(([k, v]) => `${k}: ${v}`).join("\n")}
    >
      {tr("ffpfsc.line", undefined, ".ffpfsc list")}:{" "}
      {cells
        .slice(1)
        .map(([, v]) => v)
        .join(" · ")}
    </div>
  );
}
