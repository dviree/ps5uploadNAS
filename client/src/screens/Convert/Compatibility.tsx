// Convert Games' Compatibility, in two lists: LZ4 reports (every game other players have
// reported with LZ4 asset packs, the LZ4 Compression project's compat.json, as ps5-lz4's
// Community tab shows it, with search, a filter and three sorts) and the community's .ffpfsc
// list. Games in your own library are marked.

import { useEffect, useMemo, useState } from "react";
import { ExternalLink, RefreshCw, Search, Users } from "lucide-react";

import {
  compatIssueUrl,
  compatVerdict,
  type CompatEntry,
  type CompatStatus,
} from "../../api/lz4";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorCard,
  Input,
  Select,
  Spinner,
  Tabs,
} from "../../components";
import { openExternalUrl } from "../../lib/openExternalUrl";
import {
  collectionGames,
  loadCollection,
  useCollectionStore,
} from "../../state/collection";
import { useTr } from "../../state/lang";
import { loadLz4Compat, useLz4Compat } from "../../state/lz4Compat";
import { FfpfscList } from "./FfpfscList";

type Filter = "all" | "good" | "problems" | "mine";
type Sort = "latest" | "most" | "name";

function Lz4Reports() {
  const tr = useTr();
  const data = useLz4Compat((s) => s.data);
  const loading = useLz4Compat((s) => s.loading);
  const error = useLz4Compat((s) => s.error);
  const library = useCollectionStore((s) => s.library);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("latest");

  useEffect(() => {
    void loadLz4Compat();
    if (!useCollectionStore.getState().library) void loadCollection();
  }, []);

  const mine = useMemo(
    () => new Set(collectionGames(library).map((g) => g.game_id.toUpperCase())),
    [library],
  );

  const entries = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = Object.entries(data?.games ?? {}).filter(([id, e]) => {
      if (q && !`${id} ${e.name ?? ""}`.toLowerCase().includes(q)) return false;
      const v = compatVerdict(e);
      if (filter === "good") return v === "good";
      if (filter === "problems") return v !== "good";
      if (filter === "mine") return mine.has(id.toUpperCase());
      return true;
    });
    const date = (e: CompatEntry) => e.lastReport?.date ?? "";
    list.sort(([a, x], [b, y]) =>
      sort === "most"
        ? y.reports - x.reports
        : sort === "name"
          ? (x.name ?? a).localeCompare(y.name ?? b)
          : date(y).localeCompare(date(x)),
    );
    return list;
  }, [data, search, filter, sort, mine]);

  return (
    <div className="flex flex-col gap-4" data-testid="lz4-compatibility">
      <Card>
        <div className="flex flex-col gap-3">
          <div className="grid items-center gap-2 sm:grid-flow-col sm:grid-cols-[minmax(0,1fr)] sm:auto-cols-[minmax(9rem,13rem)]">
            <div className="min-w-0">
              <Input
                aria-label={tr("lz4compat.search", undefined, "Search reports")}
                placeholder={tr(
                  "lz4compat.search",
                  undefined,
                  "Search reports",
                )}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                leftIcon={<Search size={14} />}
              />
            </div>
            <Select
              aria-label={tr("lz4compat.filter", undefined, "Show")}
              value={filter}
              onChange={(e) => setFilter(e.target.value as Filter)}
              options={[
                {
                  value: "all",
                  label: tr("lz4compat.f_all", undefined, "All games"),
                },
                {
                  value: "good",
                  label: tr("lz4compat.f_good", undefined, "Works"),
                },
                {
                  value: "problems",
                  label: tr(
                    "lz4compat.f_problems",
                    undefined,
                    "Problems (won't start / crashes)",
                  ),
                },
                {
                  value: "mine",
                  label: tr("lz4compat.f_mine", undefined, "Only my games"),
                },
              ]}
            />
            <Select
              aria-label={tr("lz4compat.sort", undefined, "Sort")}
              value={sort}
              onChange={(e) => setSort(e.target.value as Sort)}
              options={[
                {
                  value: "latest",
                  label: tr(
                    "lz4compat.s_latest",
                    undefined,
                    "Latest report first",
                  ),
                },
                {
                  value: "most",
                  label: tr("lz4compat.s_most", undefined, "Most reports"),
                },
                {
                  value: "name",
                  label: tr("lz4compat.s_name", undefined, "Name"),
                },
              ]}
            />
            <Button
              variant="ghost"
              leftIcon={<RefreshCw size={14} />}
              disabled={loading}
              onClick={() => void loadLz4Compat(true)}
            >
              {tr("lz4compat.refresh", undefined, "Refresh")}
            </Button>
          </div>
        </div>
      </Card>

      {error && !data ? (
        <ErrorCard
          title={tr("lz4compat.error", undefined, "Could not read the reports")}
          detail={error}
        />
      ) : !data ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : entries.length === 0 ? (
        <EmptyState
          icon={Users}
          title={tr("lz4compat.none", undefined, "No reports match")}
        />
      ) : (
        <Card>
          <ul className="divide-y divide-[var(--color-border)]">
            {entries.map(([id, e]) => (
              <ReportRow
                key={id}
                id={id}
                entry={e}
                mine={mine.has(id.toUpperCase())}
              />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function ReportRow({
  id,
  entry,
  mine,
}: {
  id: string;
  entry: CompatEntry;
  mine: boolean;
}) {
  const tr = useTr();
  const verdict = compatVerdict(entry);
  const last = entry.lastReport;
  const statusLabel = (s: CompatStatus) =>
    ({
      works: tr("lz4compat.st_works", undefined, "works"),
      issues: tr("lz4compat.st_issues", undefined, "works with issues"),
      noStart: tr("lz4compat.st_nostart", undefined, "won't start"),
      crash: tr("lz4compat.st_crash", undefined, "crashes"),
    })[s];
  const details = [
    last?.gameVersion && `v${last.gameVersion}`,
    last?.level &&
      tr("lz4compat.level", { level: last.level }, "level {level}"),
    last?.source,
    last?.firmware && tr("lz4compat.fw", { fw: last.firmware }, "FW {fw}"),
    last?.date?.slice(0, 10),
  ].filter(Boolean);
  return (
    <li
      className="flex flex-wrap items-center gap-3 py-3"
      data-testid="lz4-compat-row"
    >
      <div className="min-w-0 flex-[1_1_260px]">
        <div className="flex items-center gap-2">
          <span className="truncate font-semibold">{entry.name || id}</span>
          {mine && (
            <Badge tone="accent" size="sm">
              {tr("lz4compat.mine", undefined, "in my games")}
            </Badge>
          )}
        </div>
        <div className="truncate text-xs text-[var(--color-muted)]">
          {id}
          {last && (
            <>
              {" · "}
              {tr(
                "lz4compat.last",
                { status: statusLabel(last.status) },
                "last: {status}",
              )}
              {details.length > 0 && ` · ${details.join(" · ")}`}
            </>
          )}
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap gap-1">
        <Badge
          tone={
            verdict === "good" ? "good" : verdict === "bad" ? "bad" : "warn"
          }
        >
          {tr(
            "lz4compat.summary",
            { playing: entry.works + entry.issues, count: entry.reports },
            "plays for {playing} of {count}",
          )}
        </Badge>
        {entry.noStart + entry.crash > 0 && (
          <Badge tone="bad" size="sm">
            {tr(
              "lz4compat.broken",
              { n: entry.noStart + entry.crash },
              "{n} won't start / crash",
            )}
          </Badge>
        )}
      </div>
      {last?.issue && (
        <Button
          size="sm"
          variant="ghost"
          leftIcon={<ExternalLink size={12} />}
          onClick={() => void openExternalUrl(compatIssueUrl(last.issue!))}
        >
          {tr("lz4compat.open", undefined, "Report")}
        </Button>
      )}
    </li>
  );
}

export function Compatibility() {
  const tr = useTr();
  const [list, setList] = useState<"lz4" | "ffpfsc">("lz4");
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        variant="pills"
        size="sm"
        ariaLabel={tr("lz4compat.tab", undefined, "Compatibility")}
        value={list}
        onChange={(id) => setList(id as "lz4" | "ffpfsc")}
        tabs={[
          {
            id: "lz4",
            label: tr("lz4compat.list_lz4", undefined, "LZ4 reports"),
          },
          {
            id: "ffpfsc",
            label: tr("lz4compat.list_ffpfsc", undefined, ".ffpfsc list"),
          },
        ]}
      />
      {list === "lz4" ? <Lz4Reports /> : <FfpfscList />}
    </div>
  );
}
