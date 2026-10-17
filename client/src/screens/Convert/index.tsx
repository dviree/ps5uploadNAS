// Convert Games: ps5upload's own converter (package, game image, folder) and, beside it,
// ps5-lz4 (lz4/nas-lz4, from PS5-LZ4-NAS). The tab is in the URL (?tab=lz4), so a
// refresh or a link keeps it.

import { useSearchParams } from "react-router";
import { PackagePlus } from "lucide-react";

import { PageHeader, Tabs } from "../../components";
import { useTr } from "../../state/lang";
import FpkgConvertScreen from "../FpkgConvert";
import Lz4ConvertScreen from "../Lz4Convert";

type ConvertTab = "convert" | "lz4";

export default function ConvertScreen() {
  const tr = useTr();
  const [params, setParams] = useSearchParams();
  const tab: ConvertTab = params.get("tab") === "lz4" ? "lz4" : "convert";
  const setTab = (next: ConvertTab) => {
    if (next === tab) return;
    const p = new URLSearchParams(params);
    if (next === "convert") p.delete("tab");
    else p.set("tab", next);
    setParams(p);
  };

  const tabs = (
    <Tabs
      variant="segmented"
      size="sm"
      ariaLabel={tr("convert.engine", undefined, "Converter")}
      value={tab}
      onChange={(id) => setTab(id as ConvertTab)}
      tabs={[
        {
          id: "convert",
          label: tr("convert.tab_ps5upload", undefined, "Package & image"),
        },
        { id: "lz4", label: tr("lz4.title", undefined, "LZ4") },
      ]}
    />
  );

  if (tab === "convert") return <FpkgConvertScreen headerRight={tabs} />;
  return (
    <div className="app-page flex flex-col gap-4">
      <PageHeader
        icon={PackagePlus}
        title={tr("convert_games_title", undefined, "Convert Games")}
        description={tr(
          "convert.lz4_subtitle",
          undefined,
          "ps5-lz4: which games can be LZ4, packing them for APR-EMU, sending them to the PS5, PS5 games, ShadowMount, saves, community reports and FTP.",
        )}
        right={tabs}
      />
      <Lz4ConvertScreen />
    </div>
  );
}
