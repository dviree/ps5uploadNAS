// PKG Installer (More › PKG Installer): every install package in the engine's folders (in
// Docker, the NAS folders mounted into the container: PS4 packages, backports, DLC, updates,
// packages Convert made), with Install on each. Install hands the package to Upload &
// Install, which streams it to the PS5 as a package dropped there.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { Download, Package, RefreshCw, Search } from "lucide-react";

import { localFs } from "../../api/localFs";
import { Button, Card, EmptyState, ErrorCard, Input, PageHeader, Spinner } from "../../components";
import { formatBytes } from "../../lib/format";
import { scanPackages, type FoundPkg } from "../../lib/pkgScan";
import { useConnectionStore } from "../../state/connection";
import { useTr } from "../../state/lang";

export default function PkgInstallerScreen() {
  const tr = useTr();
  const navigate = useNavigate();
  const payloadUp = useConnectionStore((s) => s.payloadStatus === "up" && !!s.host?.trim());
  const [pkgs, setPkgs] = useState<FoundPkg[] | null>(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const scan = useCallback(async () => {
    setScanning(true);
    setError(null);
    try {
      const roots = await localFs.storageRoots();
      setPkgs(await scanPackages(roots, (p) => localFs.listDir(p)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setScanning(false);
    }
  }, []);
  useEffect(() => {
    void scan();
  }, [scan]);

  const groups = useMemo(() => {
    const q = search.trim().toLowerCase();
    const shown = (pkgs ?? []).filter(
      (p) => !q || p.name.toLowerCase().includes(q) || p.folder.toLowerCase().includes(q),
    );
    const byRoot = new Map<string, FoundPkg[]>();
    for (const p of shown) byRoot.set(p.root, [...(byRoot.get(p.root) ?? []), p]);
    for (const list of byRoot.values()) list.sort((a, b) => a.name.localeCompare(b.name));
    return [...byRoot.entries()];
  }, [pkgs, search]);

  return (
    <div className="app-page flex flex-col gap-4">
      <PageHeader
        icon={Package}
        title={tr("pkginst.title", undefined, "PKG Installer")}
        description={tr(
          "pkginst.subtitle",
          undefined,
          "Every package in the server's folders: games, backports, DLC and updates. Install sends one to the PS5 with Stream & install.",
        )}
        right={
          <Button
            variant="secondary"
            size="sm"
            leftIcon={<RefreshCw size={14} />}
            onClick={() => void scan()}
            disabled={scanning}
          >
            {tr("pkginst.rescan", undefined, "Rescan")}
          </Button>
        }
      />
      {!payloadUp && (
        <ErrorCard
          title={tr(
            "pkginst.no_ps5",
            undefined,
            "Connect to the PS5 and start the helper to install packages.",
          )}
        />
      )}
      {error && <ErrorCard title={error} />}
      <Input
        aria-label={tr("pkginst.search", undefined, "Search packages")}
        placeholder={tr("pkginst.search", undefined, "Search packages")}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        leftIcon={<Search size={14} />}
      />
      {pkgs === null || (scanning && pkgs.length === 0) ? (
        <div className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
          <Spinner size={14} />
          {tr("pkginst.scanning", undefined, "Looking for packages…")}
        </div>
      ) : groups.length === 0 ? (
        <EmptyState
          icon={Package}
          title={tr("pkginst.none", undefined, "No packages found")}
          message={tr(
            "pkginst.none_body",
            undefined,
            "Put .pkg files in one of the server's folders, then Rescan.",
          )}
        />
      ) : (
        groups.map(([root, list]) => (
          <Card key={root}>
            <h3 className="mb-2 text-sm font-semibold">
              {root}{" "}
              <span className="font-normal text-[var(--color-muted)]">
                {tr("pkginst.count", { count: list.length }, "{count} packages")}
              </span>
            </h3>
            <ul className="flex flex-col divide-y divide-[var(--color-border)]">
              {list.map((p) => (
                <li key={p.path} className="flex items-center gap-3 py-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm" title={p.name}>
                      {p.name}
                    </div>
                    <div className="truncate text-xs text-[var(--color-muted)]">
                      {[p.folder, formatBytes(p.size)].filter(Boolean).join(" · ")}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    leftIcon={<Download size={14} />}
                    disabled={!payloadUp}
                    onClick={() => navigate("/send", { state: { droppedPath: p.path } })}
                  >
                    {tr("pkginst.install", undefined, "Install")}
                  </Button>
                </li>
              ))}
            </ul>
          </Card>
        ))
      )}
    </div>
  );
}
