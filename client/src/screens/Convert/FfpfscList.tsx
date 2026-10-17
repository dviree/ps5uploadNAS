// Compatibility's .ffpfsc list: the community's sheet of how games run as .ffpfsc images (the
// list ps5-lz4 shows on a game), with the sheet's own columns. Games in your library are
// marked, and Only my games narrows to them.

import { useEffect, useMemo, useState } from "react";
import { ExternalLink, FileSpreadsheet, RefreshCw, Search } from "lucide-react";

import { ffpfscCells, ffpfscTone } from "../../api/lz4";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorCard,
  Input,
  Select,
  Spinner,
} from "../../components";
import { openExternalUrl } from "../../lib/openExternalUrl";
import {
  collectionGames,
  loadCollection,
  useCollectionStore,
} from "../../state/collection";
import { useTr } from "../../state/lang";
import { loadFfpfscSheet, useFfpfscSheet } from "../../state/lz4Compat";

const TITLE_ID = /[A-Z]{4}\d{5}/;

export function FfpfscList() {
  const tr = useTr();
  const sheet = useFfpfscSheet((s) => s.sheet);
  const loading = useFfpfscSheet((s) => s.loading);
  const error = useFfpfscSheet((s) => s.error);
  const library = useCollectionStore((s) => s.library);
  const [search, setSearch] = useState("");
  const [only, setOnly] = useState<"all" | "mine">("all");

  useEffect(() => {
    void loadFfpfscSheet();
    if (!useCollectionStore.getState().library) void loadCollection();
  }, []);

  const mine = useMemo(
    () => new Set(collectionGames(library).map((g) => g.game_id.toUpperCase())),
    [library],
  );
  const idOf = (row: Record<string, string>) =>
    Object.values(row)
      .map((c) => c.toUpperCase().match(TITLE_ID)?.[0])
      .find(Boolean);

  const rows = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (sheet?.rows ?? []).filter((r) => {
      if (q && !Object.values(r).join(" ").toLowerCase().includes(q))
        return false;
      if (only === "mine") {
        const id = idOf(r);
        return !!id && mine.has(id);
      }
      return true;
    });
  }, [sheet, search, only, mine]);

  return (
    <div className="flex flex-col gap-4" data-testid="ffpfsc-list">
      <Card>
        <div className="grid items-center gap-2 sm:auto-cols-[minmax(9rem,13rem)] sm:grid-flow-col sm:grid-cols-[minmax(0,1fr)]">
          <div className="min-w-0">
            <Input
              aria-label={tr("ffpfsc.search", undefined, "Search the list")}
              placeholder={tr("ffpfsc.search", undefined, "Search the list")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              leftIcon={<Search size={14} />}
            />
          </div>
          <Select
            aria-label={tr("lz4compat.filter", undefined, "Show")}
            value={only}
            onChange={(e) => setOnly(e.target.value as "all" | "mine")}
            options={[
              {
                value: "all",
                label: tr("lz4compat.f_all", undefined, "All games"),
              },
              {
                value: "mine",
                label: tr("lz4compat.f_mine", undefined, "Only my games"),
              },
            ]}
          />
          <Button
            variant="ghost"
            leftIcon={<RefreshCw size={14} />}
            disabled={loading}
            onClick={() => void loadFfpfscSheet(true)}
          >
            {tr("lz4compat.refresh", undefined, "Refresh")}
          </Button>
          {sheet?.url && (
            <Button
              variant="ghost"
              leftIcon={<ExternalLink size={14} />}
              onClick={() => void openExternalUrl(sheet.url)}
            >
              {tr("ffpfsc.open_sheet", undefined, "Open the sheet")}
            </Button>
          )}
        </div>
      </Card>

      {error && !sheet ? (
        <ErrorCard
          title={tr(
            "ffpfsc.error",
            undefined,
            "Could not read the .ffpfsc list",
          )}
          detail={error}
        />
      ) : !sheet ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={FileSpreadsheet}
          title={
            sheet.url
              ? tr("ffpfsc.none", undefined, "No games match")
              : tr(
                  "ffpfsc.off",
                  undefined,
                  "The .ffpfsc list is turned off on this engine",
                )
          }
        />
      ) : (
        <Card>
          <ul className="divide-y divide-[var(--color-border)]">
            {rows.map((r, i) => {
              const id = idOf(r);
              return (
                <li key={i} className="py-3" data-testid="ffpfsc-row">
                  {id && mine.has(id) && (
                    <Badge tone="accent" size="sm">
                      {tr("lz4compat.mine", undefined, "in my games")}
                    </Badge>
                  )}
                  <dl className="mt-1 grid gap-x-4 gap-y-0.5 text-sm sm:grid-cols-[minmax(8rem,14rem)_1fr]">
                    {ffpfscCells(sheet.headers, r).map(([k, v]) => {
                      const tone = ffpfscTone(v);
                      return (
                        <div key={k} className="contents">
                          <dt className="text-xs text-[var(--color-muted)] sm:text-sm">
                            {k}
                          </dt>
                          <dd
                            className={
                              tone === "good"
                                ? "text-[var(--color-good)]"
                                : tone === "bad"
                                  ? "text-[var(--color-bad)]"
                                  : ""
                            }
                          >
                            {v}
                          </dd>
                        </div>
                      );
                    })}
                  </dl>
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
}
