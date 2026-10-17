// Convert Games: My games (your PS5 games and which can be LZ4), Convert (ps5upload's
// converter, with LZ4 asset packs for a game image) and Compatibility (how LZ4 games run for
// other players). The tab is in the URL (?tab=), so a refresh or a link keeps it.

import { useSearchParams } from "react-router";
import { PackagePlus } from "lucide-react";

import { PageHeader, Tabs } from "../../components";
import { useConvertPrefs } from "../../state/convertPrefs";
import { useFpkgConversion } from "../../state/fpkgConversion";
import { useTr } from "../../state/lang";
import FpkgConvertScreen from "../FpkgConvert";
import { Compatibility } from "./Compatibility";
import { MyGames } from "./MyGames";

type ConvertTab = "mine" | "convert" | "compat";

function tabOf(raw: string | null): ConvertTab {
  return raw === "convert" || raw === "compat" ? raw : "mine";
}

export default function ConvertScreen() {
  const tr = useTr();
  const [params, setParams] = useSearchParams();
  const tab = tabOf(params.get("tab"));
  const setTab = (next: ConvertTab) => {
    if (next === tab) return;
    const p = new URLSearchParams(params);
    p.set("tab", next);
    setParams(p);
  };
  /** Pack one game into an LZ4 game folder (`<name>-lz4`) in the LZ4 folder, as ps5-lz4
   *  does, adding ampr_emu 0.4.2.1 when the game's own cannot read the packs; the Convert tab
   *  shows it running. The original is only read. */
  const convertWithLz4 = (path: string) => {
    const { lz4Dir, outputDir } = useConvertPrefs.getState();
    void useFpkgConversion
      .getState()
      .buildFolder(path, lz4Dir.trim() || outputDir.trim() || undefined, { installRuntime: true });
    setTab("convert");
  };
  /** Compress one game into a .ffpfsc image in the output folder under Convert: an image is
   *  compressed as it is, a game folder written as a compressed image. The original is only
   *  read. */
  const convertToFfpfsc = (path: string, isFolder: boolean) => {
    // Not next to the source (the default for an image): the library is mounted read-only.
    const out = useConvertPrefs.getState().outputDir.trim() || "~/Downloads/fpkgs";
    const run = useFpkgConversion.getState();
    void (isFolder ? run.buildImage(path, out, true, "exfat") : run.compress(path, out));
    setTab("convert");
  };

  const tabs = (
    <Tabs
      variant="segmented"
      size="sm"
      ariaLabel={tr("convert_games_title", undefined, "Convert Games")}
      value={tab}
      onChange={(id) => setTab(id as ConvertTab)}
      tabs={[
        { id: "mine", label: tr("lz4mine.tab", undefined, "My games") },
        { id: "convert", label: tr("convert.tab", undefined, "Convert") },
        {
          id: "compat",
          label: tr("lz4compat.tab", undefined, "Compatibility"),
        },
      ]}
    />
  );

  if (tab === "convert") return <FpkgConvertScreen headerRight={tabs} />;
  return (
    <div className="app-page flex flex-col gap-4">
      <PageHeader
        icon={PackagePlus}
        title={tr("convert_games_title", undefined, "Convert Games")}
        description={
          tab === "mine"
            ? tr(
                "lz4mine.subtitle",
                undefined,
                "The PS5 games in your library folders and which of them can be LZ4. Convert to LZ4 packs a game's data into LZ4 asset packs that APR-EMU reads while the game runs, and saves it as a game folder (name-lz4) in the LZ4 folder, as ps5-lz4 does. The original is only read.",
              )
            : tr(
                "lz4compat.subtitle",
                undefined,
                "How games run for other players: packed with LZ4 (their game reports on GitHub; add yours with Report how it runs on a packed game in My games) and as .ffpfsc images (the community's .ffpfsc list).",
              )
        }
        right={tabs}
      />
      {tab === "mine" ? (
        <MyGames onConvert={convertWithLz4} onFfpfsc={convertToFfpfsc} />
      ) : (
        <Compatibility />
      )}
    </div>
  );
}
