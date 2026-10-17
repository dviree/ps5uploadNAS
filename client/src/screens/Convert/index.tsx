// Convert Games: My games (your PS5 games and which can be LZ4), Convert (ps5upload's
// converter, with LZ4 asset packs for a game image) and Compatibility (how LZ4 games run for
// other players). The tab is in the URL (?tab=), so a refresh or a link keeps it.

import { useSearchParams } from "react-router";
import { PackagePlus } from "lucide-react";

import { PageHeader, Tabs } from "../../components";
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
  /** Open the converter on one game, with LZ4 asset packs on (FpkgConvert reads the state). */
  const convertWithLz4 = (path: string) => {
    const p = new URLSearchParams(params);
    p.set("tab", "convert");
    setParams(p, { state: { source: path, lz4: true } });
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
                "The PS5 games in your library folders and which of them can be LZ4. Convert to LZ4 packs a game's data into LZ4 asset packs that APR-EMU reads while the game runs, in a game image ShadowMount+ mounts.",
              )
            : tr(
                "lz4compat.subtitle",
                undefined,
                "How games packed with LZ4 run for other players, from their game reports on GitHub. Add yours with Report how it runs on a packed game in My games.",
              )
        }
        right={tabs}
      />
      {tab === "mine" ? (
        <MyGames onConvert={convertWithLz4} />
      ) : (
        <Compatibility />
      )}
    </div>
  );
}
