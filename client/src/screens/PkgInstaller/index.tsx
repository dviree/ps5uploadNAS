// PKG Installer (More › PKG Installer): every install package in the engine's folders (in
// Docker, the NAS folders mounted into the container: PS4 packages, backports, DLC, updates,
// packages Convert made), with Install on each. Install hands the package to Upload &
// Install, which streams it to the PS5 as a package dropped there. Each package says what the
// PS5 already has (its header read, then the console's install preflight, as Upload & Install
// checks a package), and Install all sends what is missing or newer, games first.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { Download, ListChecks, Package, RefreshCw, Search } from "lucide-react";

import { localFs } from "../../api/localFs";
import { pkgInstallPreflight } from "../../api/ps5";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorCard,
  Input,
  PageHeader,
  Spinner,
} from "../../components";
import type { BadgeTone } from "../../components/Badge";
import { transferAddr } from "../../lib/addr";
import { formatBytes } from "../../lib/format";
import { invoke } from "../../lib/invokeLogged";
import {
  checkFrom,
  planInstallAll,
  type PkgCheck,
} from "../../lib/pkgInstallPlan";
import { scanPackages, type FoundPkg } from "../../lib/pkgScan";
import { useConnectionStore } from "../../state/connection";
import { useTr } from "../../state/lang";

interface SplitHead {
  total_size?: number;
  head?: {
    content_id?: string;
    category?: string;
    app_ver?: string;
    platform?: string;
    package_type?: string;
    fingerprint?: string;
  };
}

/** Read one package's header and ask the console what it has of it. */
async function checkPackage(path: string, host: string): Promise<PkgCheck> {
  const meta = await invoke<SplitHead>("pkg_metadata_split", { path }).catch(
    () => null,
  );
  const head = meta?.head;
  const pre = head?.content_id
    ? await pkgInstallPreflight(transferAddr(host), head.content_id, {
        packageType: head.package_type ?? null,
        size: meta?.total_size,
        fingerprint: head.fingerprint,
      })
    : null;
  return checkFrom(head, pre);
}

export default function PkgInstallerScreen() {
  const tr = useTr();
  const navigate = useNavigate();
  const host = useConnectionStore((s) => s.host?.trim() ?? "");
  const payloadUp = useConnectionStore(
    (s) => s.payloadStatus === "up" && !!s.host?.trim(),
  );
  const [checks, setChecks] = useState<Map<string, PkgCheck>>(new Map());
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

  // What the PS5 has of each package: four header reads and preflights at a time, again on each
  // scan and when the console changes.
  useEffect(() => {
    if (!pkgs || !payloadUp || !host) return;
    let cancelled = false;
    setChecks(
      new Map(
        pkgs.map((p) => [
          p.path,
          {
            relation: "checking",
            installedVer: null,
            version: "",
            category: "",
            contentId: "",
          },
        ]),
      ),
    );
    void (async () => {
      for (let i = 0; i < pkgs.length && !cancelled; i += 4) {
        const batch = pkgs.slice(i, i + 4);
        const done = await Promise.all(
          batch.map(
            async (p) => [p.path, await checkPackage(p.path, host)] as const,
          ),
        );
        if (cancelled) return;
        setChecks((prev) => {
          const next = new Map(prev);
          for (const [path, c] of done) next.set(path, c);
          return next;
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pkgs, payloadUp, host]);

  const checking = [...checks.values()].some((c) => c.relation === "checking");
  const plan = useMemo(
    () =>
      planInstallAll(
        (pkgs ?? []).flatMap((p) => {
          const check = checks.get(p.path);
          return check ? [{ ...p, check }] : [];
        }),
      ),
    [pkgs, checks],
  );

  const statusOf = (p: FoundPkg): { text: string; tone: BadgeTone } | null => {
    const c = checks.get(p.path);
    if (!c) return null;
    const v = c.installedVer ? ` v${c.installedVer}` : "";
    switch (c.relation) {
      case "checking":
        return {
          text: tr("pkginst.st.checking", undefined, "Checking…"),
          tone: "neutral",
        };
      case "not-installed":
        return {
          text: tr("pkginst.st.not_installed", undefined, "Not installed"),
          tone: "accent",
        };
      case "newer":
        return {
          text: tr("pkginst.st.newer", { v }, "Newer than the installed{v}"),
          tone: "accent",
        };
      case "same":
      case "installed":
        return {
          text: tr("pkginst.st.installed", { v }, "Installed{v}"),
          tone: "good",
        };
      case "older":
        return {
          text: tr("pkginst.st.older", { v }, "Older than the installed{v}"),
          tone: "warn",
        };
      case "base-missing":
        return {
          text: tr("pkginst.st.base_missing", undefined, "Game not on the PS5"),
          tone: "warn",
        };
      default:
        return {
          text: tr("pkginst.st.unknown", undefined, "Unknown"),
          tone: "neutral",
        };
    }
  };

  const installAll = () =>
    navigate("/send", {
      state: { droppedPaths: plan.install.map((p) => p.path) },
    });

  const groups = useMemo(() => {
    const q = search.trim().toLowerCase();
    const shown = (pkgs ?? []).filter(
      (p) =>
        !q ||
        p.name.toLowerCase().includes(q) ||
        p.folder.toLowerCase().includes(q),
    );
    const byRoot = new Map<string, FoundPkg[]>();
    for (const p of shown)
      byRoot.set(p.root, [...(byRoot.get(p.root) ?? []), p]);
    for (const list of byRoot.values())
      list.sort((a, b) => a.name.localeCompare(b.name));
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
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              leftIcon={<ListChecks size={14} />}
              onClick={installAll}
              disabled={!payloadUp || checking || plan.install.length === 0}
              title={tr(
                "pkginst.install_all_hint",
                undefined,
                "Installs what the PS5 doesn't have yet or has older: games, then updates, then DLC.",
              )}
            >
              {tr(
                "pkginst.install_all",
                { count: plan.install.length },
                "Install all ({count})",
              )}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<RefreshCw size={14} />}
              onClick={() => void scan()}
              disabled={scanning}
            >
              {tr("pkginst.rescan", undefined, "Rescan")}
            </Button>
          </div>
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
                {tr(
                  "pkginst.count",
                  { count: list.length },
                  "{count} packages",
                )}
              </span>
            </h3>
            <ul className="flex flex-col divide-y divide-[var(--color-border)]">
              {list.map((p) => {
                const status = statusOf(p);
                const check = checks.get(p.path);
                return (
                  <li key={p.path} className="flex items-center gap-3 py-2">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm" title={p.name}>
                        {p.name}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-muted)]">
                        <span className="truncate">
                          {[
                            p.folder,
                            check?.version ? `v${check.version}` : "",
                            formatBytes(p.size),
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                        {status && (
                          <Badge size="sm" tone={status.tone}>
                            {status.text}
                          </Badge>
                        )}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      leftIcon={<Download size={14} />}
                      disabled={!payloadUp}
                      onClick={() =>
                        navigate("/send", { state: { droppedPath: p.path } })
                      }
                    >
                      {tr("pkginst.install", undefined, "Install")}
                    </Button>
                  </li>
                );
              })}
            </ul>
          </Card>
        ))
      )}
    </div>
  );
}
