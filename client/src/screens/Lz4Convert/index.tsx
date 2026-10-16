// Convert Games: the LZ4 Compression engine (lz4/, from PS5-LZ4-NAS) and nothing else. The
// engine serves its own page on port 5920 with every function it has (LZ4 asset packs,
// .ffpfsc, images, validate and repair, APR-EMU versions, copy and move, history), so this
// screen shows that page as it is, in its own theme, and only keeps track of where it runs.

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";

import { openExternalUrl } from "../../lib/openExternalUrl";
import { useEngineStore } from "../../state/engine";
import { useTr } from "../../state/lang";
import { defaultLz4Url, loadLz4Url, normalizeLz4Url, saveLz4Url } from "./lz4Url";
import logo from "./lz4-logo.png";
import "./lz4Theme.css";

type Reach = "checking" | "up" | "down";

/** The engine answers /api/status (with CORS open) whenever it is running. */
async function probe(url: string): Promise<boolean> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 4000);
  try {
    const r = await fetch(`${url}/api/status`, { signal: ctl.signal, cache: "no-store" });
    return r.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export default function Lz4ConvertScreen() {
  const tr = useTr();
  const engineUrl = useEngineStore((s) => s.engineUrl);
  const [saved, setSaved] = useState<string | null>(() => loadLz4Url());
  const url = saved ?? defaultLz4Url(engineUrl);
  const [draft, setDraft] = useState(url);
  const [reach, setReach] = useState<Reach>("checking");
  // Bumped to reload the page inside the frame.
  const [frameKey, setFrameKey] = useState(0);

  const check = useCallback(async () => {
    setReach("checking");
    setReach((await probe(url)) ? "up" : "down");
  }, [url]);

  useEffect(() => {
    void check();
  }, [check]);

  useEffect(() => setDraft(url), [url]);

  const apply = () => {
    const v = normalizeLz4Url(draft);
    saveLz4Url(v);
    setSaved(v || null);
    setFrameKey((k) => k + 1);
  };

  return (
    <div className="lz4-theme" data-testid="lz4-convert">
      <div className="lz4-bar">
        <img src={logo} alt="" className="lz4-logo" />
        <div className="lz4-title">
          <div className="lz4-name">{tr("lz4.title", undefined, "LZ4 Compression")}</div>
          <div className="lz4-sub">
            {reach === "up"
              ? tr("lz4.running_at", { url }, "Running at {url}")
              : reach === "down"
                ? tr("lz4.not_reachable", { url }, "Not reachable at {url}")
                : tr("lz4.checking", { url }, "Looking for the engine at {url}…")}
          </div>
        </div>
        <form
          className="lz4-url"
          onSubmit={(e) => {
            e.preventDefault();
            apply();
          }}
        >
          <input
            aria-label={tr("lz4.url_label", undefined, "LZ4 engine address")}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={defaultLz4Url(engineUrl)}
            spellCheck={false}
          />
          <button type="submit" className="lz4-btn">
            {tr("lz4.connect", undefined, "Connect")}
          </button>
        </form>
        <button
          type="button"
          className="lz4-icon-btn"
          title={tr("lz4.reload", undefined, "Reload")}
          onClick={() => {
            setFrameKey((k) => k + 1);
            void check();
          }}
        >
          <RefreshCw size={16} />
        </button>
        <button
          type="button"
          className="lz4-icon-btn"
          title={tr("lz4.open_browser", undefined, "Open in the browser")}
          onClick={() => void openExternalUrl(url)}
        >
          <ExternalLink size={16} />
        </button>
      </div>

      {reach === "down" ? (
        <div className="lz4-panel" data-testid="lz4-down">
          <h2>{tr("lz4.down_title", undefined, "The LZ4 engine isn't running")}</h2>
          <p>
            {tr(
              "lz4.down_body",
              undefined,
              "Start it next to the ps5upload engine with the Docker compose file: docker compose -f engine/compose.yaml up -d --build. It serves its page on port 5920. On a PS5, load lz4-compression.elf and type the console's address above instead.",
            )}
          </p>
          <button type="button" className="lz4-btn" onClick={() => void check()}>
            {tr("lz4.try_again", undefined, "Try again")}
          </button>
        </div>
      ) : (
        <iframe
          key={`${url}#${frameKey}`}
          src={`${url}/`}
          title={tr("lz4.title", undefined, "LZ4 Compression")}
          className="lz4-frame"
        />
      )}
    </div>
  );
}
