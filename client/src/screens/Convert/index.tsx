// Convert Games: My games (your PS5 games and which can be LZ4), Convert (ps5upload's
// converter, with LZ4 asset packs for a game image) and Compatibility (how LZ4 games run for
// other players). The tab is in the URL (?tab=), so a refresh or a link keeps it.

import { useLocation, useSearchParams } from "react-router";
import { PackagePlus } from "lucide-react";

import { PageHeader, Tabs } from "../../components";
import type { CollectionGame, CollectionLocation } from "../../api/collection";
import {
  DEFAULT_SEND_SUBPATH,
  collectionSendItem,
} from "../../lib/collectionSend";
import { DEFAULT_IMAGE_SUBPATH } from "../../lib/imageUpload";
import { useConnectionStore } from "../../state/connection";
import { useConvertPrefs } from "../../state/convertPrefs";
import { useFpkgConversion } from "../../state/fpkgConversion";
import { useTr } from "../../state/lang";
import { useUploadStore } from "../../state/upload";
import { useUploadQueueStore } from "../../state/uploadQueue";
import FpkgConvertScreen from "../FpkgConvert";
import { Compatibility } from "./Compatibility";
import { MyGames } from "./MyGames";

type ConvertTab = "mine" | "convert" | "compat";

/** With no tab in the URL, a link that brings a game to convert (`state.source`, from
 *  Collection, Files or a game page) or opens Look Inside (`?view=`) lands on Convert. */
function tabOf(raw: string | null, toConverter: boolean): ConvertTab {
  if (raw === "convert" || raw === "compat" || raw === "mine") return raw;
  return toConverter ? "convert" : "mine";
}

export default function ConvertScreen() {
  const tr = useTr();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const handed = location.state as {
    source?: unknown;
    sources?: unknown;
  } | null;
  const tab = tabOf(
    params.get("tab"),
    params.has("view") || Boolean(handed?.source || handed?.sources),
  );
  const setTab = (next: ConvertTab) => {
    if (next === tab) return;
    const p = new URLSearchParams(params);
    p.set("tab", next);
    setParams(p);
  };
  /** Pack one game into an LZ4 game folder (`<name>-lz4`) in the LZ4 folder, as ps5-lz4
   *  does, adding ampr_emu 0.4.2.1 when the game's own cannot read the packs; the Convert tab
   *  shows it running. The original is only read. */
  /** The connected PS5 and the drive Upload last used, for "& send to PS5". */
  const sendTarget = () => {
    const c = useConnectionStore.getState();
    const host = c.payloadStatus === "up" ? (c.host?.trim() ?? "") : "";
    return host
      ? { host, volume: useUploadStore.getState().destinationVolume ?? "/data" }
      : null;
  };
  const convertWithLz4 = (path: string, sendTitle?: string) => {
    const { lz4Dir, outputDir } = useConvertPrefs.getState();
    // "& send to PS5": once built, the LZ4 game folder goes into the Upload queue for the
    // connected PS5, into the folder ShadowMount+ scans on the drive Upload last used.
    const c = useConnectionStore.getState();
    const host = c.payloadStatus === "up" ? (c.host?.trim() ?? "") : "";
    const send =
      sendTitle !== undefined && host
        ? {
            title: sendTitle,
            host,
            volume: useUploadStore.getState().destinationVolume ?? "/data",
            subpath: DEFAULT_SEND_SUBPATH,
            register: true,
          }
        : undefined;
    void useFpkgConversion
      .getState()
      .buildFolder(
        path,
        lz4Dir.trim() || outputDir.trim() || undefined,
        { installRuntime: true },
        send,
      );
    setTab("convert");
  };
  /** Compress one game into a .ffpfsc image in the output folder under Convert: an image is
   *  compressed as it is, a game folder written as a compressed image. The original is only
   *  read. */
  const convertToFfpfsc = (path: string, isFolder: boolean, send = false) => {
    // Not next to the source (the default for an image): the library is mounted read-only.
    const out =
      useConvertPrefs.getState().outputDir.trim() || "~/Downloads/fpkgs";
    const run = useFpkgConversion.getState();
    // "& send to PS5": the finished .ffpfsc goes into the Upload queue, like an LZ4 folder.
    const to = send ? sendTarget() : null;
    const thenUpload = to
      ? {
          host: to.host,
          volume: to.volume,
          subpath: DEFAULT_IMAGE_SUBPATH,
          deleteAfter: false,
        }
      : undefined;
    void (isFolder
      ? run.buildImage(path, out, true, "exfat", thenUpload)
      : run.compress(path, out, thenUpload));
    setTab("convert");
  };
  /** Send a game as it is (a folder, an LZ4 game folder or an image) to the connected PS5
   *  through the Upload queue, as Send to PS5 on a game page does. */
  const sendToPs5 = (game: CollectionGame, loc: CollectionLocation) => {
    const to = sendTarget();
    if (!to) return;
    const q = useUploadQueueStore.getState();
    const id = q.add(
      collectionSendItem(game, loc, {
        host: to.host,
        volume: to.volume,
        subpath: DEFAULT_SEND_SUBPATH,
        register: true,
      }),
    );
    void q.startHost(to.host, { onlyIds: [id] });
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
        <MyGames
          onConvert={convertWithLz4}
          onFfpfsc={convertToFfpfsc}
          onSend={sendToPs5}
        />
      ) : (
        <Compatibility />
      )}
    </div>
  );
}
