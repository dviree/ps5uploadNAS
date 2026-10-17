// Convert Games' LZ4 tab: ps5-lz4's web page (lz4/nas-lz4, the ps5-lz4-ui container on port
// 5921) as it is, in its own look: My games with what can be LZ4, Activity, PS5 games,
// ShadowMount, Saves, Community reports, Remote and FTP. This screen only finds it; the
// address is asked for only when it can't be reached.

import { useCallback, useEffect, useState } from "react";

import { useEngineStore } from "../../state/engine";
import { useTr } from "../../state/lang";
import {
  defaultLz4Url,
  loadLz4Url,
  normalizeLz4Url,
  saveLz4Url,
} from "./lz4Url";

// ps5-lz4's glass look (lz4/nas-lz4/ui.html): frosted panels with light edges and violet
// buttons, for the message shown when the page can't be reached.
const LZ4 = {
  line: "rgba(255,255,255,0.2)",
  muted: "rgba(236,232,255,0.74)",
  surface: "rgba(46,30,110,0.96)",
};
const control =
  "rounded-[10px] border border-[rgba(255,255,255,0.24)] bg-[rgba(255,255,255,0.12)] text-white";
const primary =
  "rounded-[10px] bg-[linear-gradient(135deg,#b794ff,#7c5cff_50%,#4f7bff)] px-4 py-2 text-[13px] font-semibold text-white shadow-[0_6px_22px_rgba(60,30,160,0.45)] hover:brightness-110";

type Reach = "checking" | "up" | "down";

/** Whether anything answers at `url`. The page sends no CORS headers for itself, so the
 *  request is opaque: it resolves when the server answers and rejects when nothing does. */
async function probe(url: string): Promise<boolean> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 4000);
  try {
    await fetch(`${url}/`, {
      mode: "no-cors",
      signal: ctl.signal,
      cache: "no-store",
    });
    return true;
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

  const check = useCallback(async () => {
    setReach("checking");
    setReach((await probe(url)) ? "up" : "down");
  }, [url]);

  useEffect(() => {
    void check();
  }, [check]);

  useEffect(() => setDraft(url), [url]);

  if (reach === "down") {
    return (
      <div
        className="mx-auto my-8 max-w-[640px] rounded-2xl border p-6 text-white shadow-[0_16px_38px_rgba(0,0,0,0.3)]"
        style={{ borderColor: LZ4.line, background: LZ4.surface }}
        data-testid="lz4-down"
      >
        <h2 className="mb-2 text-lg font-semibold">
          {tr("lz4.down_title", undefined, "ps5-lz4 isn't running")}
        </h2>
        <p className="mb-4 text-sm leading-normal" style={{ color: LZ4.muted }}>
          {tr(
            "lz4.down_body",
            { url },
            "Nothing answered at {url}. Start ps5-lz4 on the NAS (scripts/nas-install.sh sets it up next to ps5upload), or type where it runs.",
          )}
        </p>
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const v = normalizeLz4Url(draft);
            saveLz4Url(v);
            setSaved(v || null);
            void check();
          }}
        >
          <input
            aria-label={tr("lz4.url_label", undefined, "ps5-lz4 address")}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={defaultLz4Url(engineUrl)}
            spellCheck={false}
            className={`${control} min-w-0 flex-[1_1_240px] px-3 py-2 text-[13px] focus:outline-2 focus:outline-offset-1 focus:outline-[#b794ff]`}
          />
          <button type="submit" className={primary}>
            {tr("lz4.try_again", undefined, "Try again")}
          </button>
        </form>
      </div>
    );
  }

  return (
    <iframe
      src={`${url}/`}
      title={tr("lz4.title", undefined, "LZ4")}
      className="h-[calc(100dvh-13rem)] min-h-[560px] w-full rounded-[18px] border"
      style={{ borderColor: LZ4.line, background: "#24145c" }}
      data-testid="lz4-convert"
    />
  );
}
