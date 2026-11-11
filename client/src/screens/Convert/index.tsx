import { useLocation, useSearchParams } from "react-router";
import { PackagePlus } from "lucide-react";
import { PageHeader, Tabs } from "../../components";
import { getEngineUrl } from "../../state/engine";
import FpkgConvertScreen from "../FpkgConvert";

export default function ConvertScreen() {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const handed = location.state as { source?: unknown; sources?: unknown } | null;
  const tab = params.get("tab") === "convert" || params.has("view") || handed?.source || handed?.sources ? "convert" : "zstd";
  const tabs = <Tabs variant="segmented" size="sm" ariaLabel="Convert Games" value={tab}
    onChange={(id) => setParams({ tab: id })}
    tabs={[{ id: "zstd", label: "Zstd" }, { id: "convert", label: "Workshop" }]} />;
  if (tab === "convert") return <FpkgConvertScreen headerRight={tabs} />;
  return <div className="app-page flex flex-col gap-4">
    <PageHeader icon={PackagePlus} title="Zstd" right={tabs} />
    <iframe title="Zstd NAS converter" src={`${getEngineUrl()}/api/nas-zstd/`}
      className="w-full flex-1 rounded-xl border-0" style={{ minHeight: "80vh" }} />
  </div>;
}
