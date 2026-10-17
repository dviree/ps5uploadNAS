// Convert Games: the LZ4 Compression engine (lz4/, from PS5-LZ4-NAS) and nothing else. The
// engine serves its own page on port 5920 with every function it has (LZ4 asset packs,
// .ffpfsc, images, validate and repair, APR-EMU versions, copy and move, history), so this
// screen shows that page as it is, in its own theme, and only keeps track of where it runs.

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";

import { openExternalUrl } from "../../lib/openExternalUrl";
import { useEngineStore } from "../../state/engine";
import { useTr } from "../../state/lang";
import {
  defaultLz4Url,
  loadLz4Url,
  normalizeLz4Url,
  saveLz4Url,
} from "./lz4Url";
import logo from "./lz4-logo.png";

// The LZ4 Compression page's own look (lz4/assets/lz4-compression.html): always dark, with its
// colours, fonts and glass panels, so the bar around the engine's page matches it.
const LZ4 = {
  bg: "#101313",
  surface: "rgba(25,28,28,0.96)",
  line: "rgba(240,245,240,0.11)",
  text: "#f1f0eb",
  muted: "#aaa8a1",
  panelBg: "rgba(31,34,34,0.88)",
};
const LZ4_FONT =
  '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Avenir Next", "Segoe UI", sans-serif';
const LZ4_TITLE_FONT =
  '"SST", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Segoe UI", sans-serif';
const control =
  "rounded-[10px] border border-[rgba(240,245,240,0.11)] bg-[rgba(35,38,38,0.9)] text-[#f1f0eb]";
const primary =
  "rounded-[10px] bg-[linear-gradient(145deg,#2b86bd,#1d5f8c)] px-4 py-2 text-[13px] font-semibold text-white shadow-[0_18px_42px_rgba(20,103,151,0.25)] hover:brightness-110";
const iconBtn = `${control} inline-flex h-9 w-9 shrink-0 items-center justify-center hover:brightness-110`;

type Reach = "checking" | "up" | "down";

/** The engine answers /api/status (with CORS open) whenever it is running. */
async function probe(url: string): Promise<boolean> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 4000);
  try {
    const r = await fetch(`${url}/api/status`, {
      signal: ctl.signal,
      cache: "no-store",
    });
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
    <div
      className="flex h-[calc(100dvh-7rem)] min-h-[560px] flex-col gap-2.5 rounded-[18px] p-2.5 text-[15px] antialiased [color-scheme:dark]"
      style={{ background: LZ4.bg, color: LZ4.text, fontFamily: LZ4_FONT }}
      data-testid="lz4-convert"
    >
      <div
        className="flex flex-wrap items-center gap-2.5 rounded-[14px] border px-3 py-2.5 shadow-[0_16px_38px_rgba(0,0,0,0.3)] backdrop-blur-xl"
        style={{ borderColor: LZ4.line, background: LZ4.panelBg }}
      >
        <img src={logo} alt="" className="h-[34px] w-[34px] rounded-[9px]" />
        <div className="min-w-0 flex-[1_1_180px]">
          <div
            className="text-[17px] font-semibold"
            style={{ fontFamily: LZ4_TITLE_FONT }}
          >
            {tr("lz4.title", undefined, "LZ4 Compression")}
          </div>
          <div className="truncate text-xs" style={{ color: LZ4.muted }}>
            {reach === "up"
              ? tr("lz4.running_at", { url }, "Running at {url}")
              : reach === "down"
                ? tr("lz4.not_reachable", { url }, "Not reachable at {url}")
                : tr(
                    "lz4.checking",
                    { url },
                    "Looking for the engine at {url}…",
                  )}
          </div>
        </div>
        <form
          className="flex min-w-0 flex-[1_1_280px] gap-2"
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
            className={`${control} min-w-0 flex-1 px-3 py-2 text-[13px] focus:outline-2 focus:outline-offset-1 focus:outline-[#2b86bd]`}
          />
          <button type="submit" className={primary}>
            {tr("lz4.connect", undefined, "Connect")}
          </button>
        </form>
        <button
          type="button"
          className={iconBtn}
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
          className={iconBtn}
          title={tr("lz4.open_browser", undefined, "Open in the browser")}
          onClick={() => void openExternalUrl(url)}
        >
          <ExternalLink size={16} />
        </button>
      </div>

      {reach === "down" ? (
        <div
          className="mx-auto my-12 max-w-[640px] rounded-2xl border p-6 shadow-[0_16px_38px_rgba(0,0,0,0.3)]"
          style={{ borderColor: LZ4.line, background: LZ4.surface }}
          data-testid="lz4-down"
        >
          <h2 className="mb-2 text-lg font-semibold">
            {tr("lz4.down_title", undefined, "The LZ4 engine isn't running")}
          </h2>
          <p
            className="mb-4 text-sm leading-normal"
            style={{ color: LZ4.muted }}
          >
            {tr(
              "lz4.down_body",
              undefined,
              "Start it next to the ps5upload engine with the Docker compose file: docker compose -f engine/compose.yaml up -d --build. It serves its page on port 5920. On a PS5, load lz4-compression.elf and type the console's address above instead.",
            )}
          </p>
          <button
            type="button"
            className={primary}
            onClick={() => void check()}
          >
            {tr("lz4.try_again", undefined, "Try again")}
          </button>
        </div>
      ) : (
        <iframe
          key={`${url}#${frameKey}`}
          src={`${url}/`}
          title={tr("lz4.title", undefined, "LZ4 Compression")}
          className="w-full flex-1 rounded-[14px] border"
          style={{ borderColor: LZ4.line, background: LZ4.bg }}
        />
      )}
    </div>
  );
}
