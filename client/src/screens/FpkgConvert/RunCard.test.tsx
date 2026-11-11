import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../state/lang", () => ({
  useTr: () =>
    (key: string, vars?: Record<string, string | number>, fallback?: string) => {
      let s = fallback ?? key;
      for (const [k, v] of Object.entries(vars ?? {})) s = s.replace(`{${k}}`, String(v));
      return s;
    },
}));

import type { Pipeline } from "../../state/fpkgConversion";
import { ImageChoice, PacksNote, ZstdOption, folderPackOptions, folderPacks, packOptions } from "./ImageOptions";
import {
  RunCard,
  deleteLabel,
  lz4Active,
  type Lz4Choice,
  type OutputChoiceProps,
  type RunCardProps,
} from "./RunCard";

// No DOM here (vitest in node, no testing-library): render to markup and check what a user
// would see and could press.
const noop = () => {};
/** ③'s one set of choices: a package, kept. */
const choice = (over: Partial<OutputChoiceProps> = {}): OutputChoiceProps => ({
  make: "pkg",
  onMake: noop,
  imageFormat: "ffpkg",
  imageCompress: false,
  onImageChoice: noop,
  then: "keep",
  onThen: noop,
  deleteAfter: false,
  onDeleteAfter: noop,
  canInstall: true,
  ...over,
});
const actions = {
  choice: choice(),
  onRun: noop,
  onCompress: noop,
  onCancel: noop,
  onInstall: noop,
  onLaunch: noop,
  onShowFolder: noop,
  onDelete: noop,
  onAnother: noop,
};

function html(
  pipeline: Pipeline,
  opts: { canInstall?: boolean; isImage?: boolean; title?: string; sourceBytes?: number } = {},
  extra: Partial<RunCardProps> = {},
) {
  return renderToStaticMarkup(
    <RunCard
      pipeline={pipeline}
      installTask={null}
      host="10.0.0.2"
      canInstall={opts.canInstall ?? true}
      isImage={opts.isImage ?? false}
      deleteArmed={false}
      title={opts.title ?? null}
      sourceBytes={opts.sourceBytes ?? 0}
      {...actions}
      {...extra}
    />,
  );
}

/** The button whose text contains `text` — `{ disabled }` from its real attribute (its class
 *  list also names Tailwind's `disabled:` variants) — or null when there is none. */
function button(out: string, text: string): { disabled: boolean } | null {
  const re = /<button([^>]*)>([\s\S]*?)<\/button>/g;
  for (let m = re.exec(out); m; m = re.exec(out)) {
    const shown = m[2].replace(/<[^>]+>/g, "").replace(/&amp;/g, "&");
    if (shown.includes(text)) return { disabled: /\sdisabled(=""|\s|$)/.test(m[1]) };
  }
  return null;
}

const done = {
  phase: "done" as const,
  source: "/g",
  host: "10.0.0.2",
  packagePath: "/out/a.pkg",
  packageBytes: 1024,
  convertMs: 60_000,
  installMs: 30_000,
  stageMs: {},
  deleted: false,
  titleId: "PPSA17221",
};

describe("RunCard", () => {
  it("names the console a Convert & install run will install on", () => {
    const running = {
      phase: "running" as const,
      mode: "convert-install" as const,
      source: "/g",
      host: "10.0.0.2",
      stage: "compress" as const,
      stageDone: 1,
      stageTotal: 2,
      startedMs: 0,
      stageStartedMs: 0,
      stageMs: {},
      jobId: "j",
      installTaskId: null,
      taskId: null,
      packagePath: null,
      titleId: null,
      copiedSource: null,
      extractedSource: null,
    };
    const out = renderToStaticMarkup(
      <RunCard
        pipeline={running}
        installTask={null}
        host="10.0.0.9"
        canInstall
        isImage={false}
        deleteArmed={false}
        targetLabel="PS5 Pro"
        {...actions}
      />,
    );
    expect(out).toContain("Will install on PS5 Pro");
  });

  it("hides Show in folder when no file manager can open it", () => {
    const { onShowFolder: _drop, ...rest } = actions;
    void _drop;
    const out = renderToStaticMarkup(
      <RunCard
        pipeline={{ ...done, mode: "convert" }}
        installTask={null}
        host="10.0.0.2"
        canInstall
        isImage={false}
        deleteArmed={false}
        {...rest}
      />,
    );
    expect(button(out, "Show in folder")).toBeNull();
    expect(button(html({ ...done, mode: "convert" }), "Show in folder")).not.toBeNull();
  });

  it("offers only Convert when no console is connected", () => {
    const out = html({ phase: "idle" }, { canInstall: false });
    expect(button(out, "Convert only")?.disabled).toBe(false);
    expect(button(out, "Convert & install")).toBeNull();
    expect(out).toContain("Connect to a PS5 to install");
  });

  it("offers .ffpfsc compression only for an image source", () => {
    expect(button(html({ phase: "idle" }), "Compress to .ffpfsc")).toBeNull();
    expect(button(html({ phase: "idle" }, { isImage: true }), "Compress to .ffpfsc")).not.toBeNull();
  });

  describe("one set of choices for Convert and the queue", () => {
    const idle = (over: Partial<OutputChoiceProps>, more: Record<string, unknown> = {}) =>
      renderToStaticMarkup(
        <RunCard
          pipeline={{ phase: "idle" }}
          installTask={null}
          host="10.0.0.2"
          canInstall
          isImage={false}
          deleteArmed={false}
          {...actions}
          choice={choice(over)}
          onQueue={noop}
          canQueue
          {...more}
        />,
      );
    /** The option labels of the select labelled `label`. */
    const options = (out: string, label: string) => {
      const at = out.indexOf(label);
      const sel = /<select[\s\S]*?<\/select>/.exec(out.slice(at))?.[0] ?? "";
      return [...sel.matchAll(/<option[^>]*>([^<]*)<\/option>/g)].map((m) => m[1].replace(/&amp;/g, "&"));
    };

    it("asks what to do after (what to make is chosen under ②)", () => {
      const out = idle({});
      expect(out).not.toContain(">Make<");
      expect(out).not.toContain("A package (.pkg)");
      expect(options(out, "After converting")).toEqual(["Keep the package", "Stream & install", "Upload & install"]);
      expect(button(out, "Add this game to the queue")?.disabled).toBe(false);
    });

    it("saves an image to this computer or straight to the PS5", () => {
      const img = { make: "image" as const, onSaveTo: noop };
      expect(options(idle(img, { canImage: true }), "Save to")).toEqual([
        "This computer",
        "The PS5, straight (nothing stored here)",
      ]);
      // A package has no such choice.
      expect(idle({ onSaveTo: noop })).not.toContain("Save to");
      const toPs5 = idle({ ...img, saveTo: "ps5" }, { canImage: true });
      expect(toPs5).not.toContain("After converting");
      expect(toPs5).toContain("goes on where it stopped");
      expect(button(toPs5, "Make game image")?.disabled).toBe(false);
      // An image that can't stream there says why and runs nothing.
      const refused = idle({ ...img, saveTo: "ps5", ps5Refusal: "Save this one to this computer." }, { canImage: true });
      expect(refused).toContain("Save this one to this computer.");
      expect(button(refused, "Make game image")?.disabled).toBe(true);
      // Nor with no console to send to.
      const noPs5 = idle({ ...img, saveTo: "ps5", canInstall: false }, { canImage: true });
      expect(button(noPs5, "Make game image")?.disabled).toBe(true);
    });

    it("saves an image or a game folder straight to a server folder", () => {
      const img = { make: "image" as const, onSaveTo: noop, onServerFolder: noop };
      expect(options(idle(img, { canImage: true }), "Save to")).toEqual([
        "This computer",
        "The PS5, straight (nothing stored here)",
        "A server, straight (nothing stored here)",
      ]);
      // A folder goes to this computer or a server, never straight to the PS5.
      const folder = { make: "folder" as const, onSaveTo: noop, onServerFolder: noop };
      expect(options(idle(folder, { canFolder: true }), "Save to")).toEqual([
        "This computer",
        "A server, straight (nothing stored here)",
      ]);
      // With no folder on a server chosen yet, nothing runs.
      const noFolder = idle({ ...img, saveTo: "server" }, { canImage: true });
      expect(noFolder).toContain('data-testid="server-dest"');
      expect(noFolder).not.toContain("After converting");
      expect(button(noFolder, "Make game image")?.disabled).toBe(true);
      const chosen = idle({ ...img, saveTo: "server", serverFolder: "remote://nas1/games" }, { canImage: true });
      expect(chosen).toContain("read back there before it gets its name");
      expect(button(chosen, "Make game image")?.disabled).toBe(false);
      // An image that can't stream there says why and runs nothing.
      const refused = idle(
        { ...img, saveTo: "server", serverFolder: "remote://nas1/games", serverRefusal: "Not this one." },
        { canImage: true },
      );
      expect(refused).toContain("Not this one.");
      expect(button(refused, "Make game image")?.disabled).toBe(true);
      // A folder build has no image refusal.
      const folderTo = idle(
        { ...folder, saveTo: "server", serverFolder: "remote://nas1/games", serverRefusal: "Not this one." },
        { canFolder: true },
      );
      expect(button(folderTo, "Make game folder")?.disabled).toBe(false);
      // The queue offers no server.
      expect(options(idle({ make: "image", onSaveTo: noop }, { canImage: true }), "Save to")).not.toContain(
        "A server, straight (nothing stored here)",
      );
    });

    it("says a finished image is on a server, with nothing to upload, show or delete", () => {
      const out = html(
        {
          phase: "done",
          mode: "image",
          source: "/g",
          host: "10.0.0.2",
          packagePath: "remote://nas1/games/G.exfat",
          packageBytes: 9,
          convertMs: 1,
          installMs: 0,
          stageMs: {},
          deleted: false,
          titleId: null,
        },
        { canInstall: true },
        { onUploadImage: noop },
      );
      expect(out).toContain("written straight to the server");
      expect(out).toContain("nas1 › games/G.exfat");
      expect(button(out, "Upload to PS5")).toBeNull();
      expect(button(out, "Show in folder")).toBeNull();
    });

    it("says a finished image is on the PS5, with nothing to upload", () => {
      const out = html(
        {
          phase: "done",
          mode: "image",
          source: "/g",
          host: "10.0.0.2",
          packagePath: "/data/homebrew/G.exfat",
          packageBytes: 9,
          convertMs: 1,
          installMs: 0,
          stageMs: {},
          deleted: false,
          titleId: null,
          onConsole: true,
        },
        { canInstall: true },
        { onUploadImage: noop },
      );
      expect(out).toContain("written straight to the PS5");
      expect(out).toContain("/data/homebrew/G.exfat");
      expect(button(out, "Upload to PS5")).toBeNull();
      expect(button(out, "Show in folder")).toBeNull();
    });

    it("names the action after the choice", () => {
      expect(button(idle({}), "Convert only")).not.toBeNull();
      expect(button(idle({ then: "stream" }), "Convert & install")).not.toBeNull();
      expect(button(idle({ then: "upload" }, { replaces: true }), "Convert & replace")).not.toBeNull();
      expect(button(idle({ make: "image" }, { canImage: true }), "Make game image")?.disabled).toBe(false);
      expect(button(idle({ make: "image", imageCompress: true }, { canImage: true }), "Make compressed image")).not.toBeNull();
    });

    it("offers deleting after only when the result is sent somewhere", () => {
      expect(idle({})).not.toContain("Delete the package once installed");
      expect(idle({ then: "stream" })).toContain("Delete the package once installed");
      expect(idle({ make: "image", then: "upload" }, { canImage: true })).toContain(
        "Delete the image once it is on the PS5",
      );
    });

    it("an image is kept or uploaded, never installed, and only a folder here becomes one", () => {
      const out = idle({ make: "image" }, { canImage: false });
      expect(options(out, "After converting")).toEqual(["Keep the image", "Upload it to the PS5"]);
      expect(button(out, "Make game image")?.disabled).toBe(true);
      expect(out).toContain("Only a game folder, game image or archive (.zip, .7z, .rar) with a game in it can become a game image");
      // Queueing still works: a folder of games can be queued as images.
      expect(button(out, "Add this game to the queue")?.disabled).toBe(false);
    });

    it("a folder is only kept, and a folder source cannot become one", () => {
      const ok = idle({ make: "folder" }, { canFolder: true });
      expect(options(ok, "After converting")).toEqual(["Keep the folder"]);
      expect(button(ok, "Make game folder")?.disabled).toBe(false);
      expect(ok).not.toContain("This is already a folder");
      const already = idle({ make: "folder" }, { canFolder: false, isFolderSource: true });
      expect(button(already, "Make game folder")?.disabled).toBe(true);
      expect(already).toContain("This is already a folder");
      const archive = idle({ make: "folder" }, { canFolder: false });
      expect(button(archive, "Make game folder")?.disabled).toBe(true);
      expect(archive).toContain("Only a game image or a package made with the debug key can become a folder");
      // Nothing is sent anywhere, so no console is asked for.
      expect(idle({ make: "folder" }, { canFolder: true, canInstall: false })).not.toContain("Connect to a PS5");
    });
  });

  it("a finished folder shows its path and Show in folder, nothing to install or delete", () => {
    const out = html(
      { ...done, mode: "folder", host: null, packagePath: "/out/Game", titleId: null, installMs: 0 },
      { sourceBytes: 1024 },
    );
    expect(out).toContain("Game folder written and read back.");
    expect(out).toContain("/out/Game");
    expect(button(out, "Show in folder")).not.toBeNull();
    expect(button(out, "Stream & install")).toBeNull();
    expect(button(out, "Delete package")).toBeNull();
    expect(button(out, "View details")).toBeNull();
    expect(button(out, "Upload to PS5")).toBeNull();
    expect(out).not.toContain("% of");
  });

  it("names a folder build's stages for a folder", () => {
    const out = html({
      phase: "running",
      mode: "folder",
      source: "/g/Game.exfat",
      host: null,
      stage: "write",
      stageDone: 1,
      stageTotal: 2,
      startedMs: 0,
      stageStartedMs: 0,
      stageMs: {},
      jobId: "j",
      installTaskId: null,
      taskId: null,
      packagePath: null,
      titleId: null,
      copiedSource: null,
      extractedSource: null,
    });
    expect(out).toContain("Write folder");
    expect(out).toContain("Read the folder back");
    expect(out).not.toContain("Write package");
    expect(button(out, "Cancel")).not.toBeNull();
  });

  it("lists the stages while running, with Cancel during the build", () => {
    const out = html({
      phase: "running",
      mode: "convert-install",
      source: "/g",
      host: "10.0.0.2",
      stage: "compress",
      stageDone: 5,
      stageTotal: 10,
      startedMs: 0,
      stageStartedMs: 0,
      stageMs: { check: 1000, plan: 2000 },
      jobId: "j",
      installTaskId: null,
      taskId: null,
      copiedSource: null,
      extractedSource: null,
      packagePath: null,
      titleId: null,
    });
    for (const label of ["Check source", "Plan package", "Compress", "Write package", "Verify", "Send to PS5", "Install on PS5"]) {
      expect(out).toContain(label);
    }
    expect(button(out, "Cancel")).not.toBeNull();
    expect(button(out, "Convert only")).toBeNull();
  });

  describe("pause (#631)", () => {
    const now = Date.now();
    // The speed is worked out against the clock: hold it still, or a slow run reads 9.89 MiB/s.
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ["Date"] });
      vi.setSystemTime(now);
    });
    afterEach(() => {
      vi.useRealTimers();
    });
    const writing = (over: Partial<Extract<Pipeline, { phase: "running" }>> = {}): Pipeline => ({
      phase: "running",
      mode: "convert",
      source: "/g",
      host: null,
      stage: "write",
      stageDone: 100 * 1024 * 1024,
      stageTotal: 400 * 1024 * 1024,
      startedMs: now - 20_000,
      stageStartedMs: now - 20_000,
      stageMs: {},
      jobId: "j",
      installTaskId: null,
      taskId: null,
      packagePath: null,
      titleId: null,
      copiedSource: null,
      extractedSource: null,
      ...over,
    });
    const pausable = { onPause: noop, onResume: noop };

    it("offers Pause beside Cancel while the job runs, and Resume once paused", () => {
      let out = html(writing(), {}, pausable);
      expect(button(out, "Pause")).not.toBeNull();
      expect(button(out, "Resume")).toBeNull();
      expect(button(out, "Cancel")).not.toBeNull();
      out = html(writing({ paused: true, pausedAtMs: now - 5000 }), {}, pausable);
      expect(button(out, "Resume")).not.toBeNull();
      expect(button(out, "Cancel")).not.toBeNull();
      expect(out).toContain("Paused — the queue waits");
      // No speed or time left while nothing moves.
      expect(out).not.toContain("left");
      expect(out).not.toMatch(/iB\/s/);
    });

    it("has no Pause where the caller cannot pause, or before the job exists", () => {
      expect(button(html(writing()), "Pause")).toBeNull();
      expect(button(html(writing({ jobId: null }), {}, pausable), "Pause")).toBeNull();
      expect(button(html(writing({ stage: "copy" }), {}, pausable), "Pause")).toBeNull();
    });

    it("leaves paused time out of the speed", () => {
      // 100 MiB in 20 s, 10 of them paused: 10 MiB/s, not 5.
      const out = html(writing({ stagePausedMs: 10_000, pausedMs: 10_000 }), {}, pausable);
      expect(out).toMatch(/· (9\.9\d|10\.0) MiB\/s/);
    });

    it("shows the Use less of this computer switch while a build runs", () => {
      expect(html(writing(), {}, pausable)).toContain("Use less of this computer");
    });
  });

  it("names the kept package and offers both install routes after an install failure", () => {
    const out = html({
      phase: "failed",
      mode: "convert-install",
      source: "/g",
      host: "10.0.0.2",
      stage: "install",
      message: "unreachable",
      packagePath: "/out/a.pkg",
      stageMs: {},
      titleId: null,
    });
    expect(out).toContain("built and kept");
    expect(out).toContain("unreachable");
    expect(button(out, "Stream & install")).not.toBeNull();
    expect(button(out, "Upload & install")).not.toBeNull();
  });

  it("offers no retry when the build itself failed", () => {
    const out = html({
      phase: "failed",
      mode: "convert",
      source: "/g",
      host: null,
      stage: "write",
      message: "disk full",
      packagePath: null,
      stageMs: {},
      titleId: null,
    });
    expect(button(out, "Stream & install")).toBeNull();
    expect(button(out, "Upload & install")).toBeNull();
    expect(out).not.toContain("built and kept");
  });

  it("shows the result actions after an install, and no Launch for Convert only", () => {
    const installed = html({ ...done, mode: "convert-install" });
    for (const name of ["Launch on PS5", "Stream & install", "Upload & install", "Delete package", "Convert another game"]) {
      expect(button(installed, name)).not.toBeNull();
    }
    expect(button(html({ ...done, mode: "convert" }), "Launch on PS5")).toBeNull();
  });

  it("follows Convert only with a choice of stream or upload install, each needing a console", () => {
    const converted = html({ ...done, mode: "convert" });
    expect(button(converted, "Stream & install")).toMatchObject({ disabled: false });
    expect(button(converted, "Upload & install")).toMatchObject({ disabled: false });
    expect(converted).toContain("copies it to the PS5 first");
    const offline = html({ ...done, mode: "convert" }, { canInstall: false });
    expect(button(offline, "Stream & install")).toMatchObject({ disabled: true });
    expect(button(offline, "Upload & install")).toMatchObject({ disabled: true });
    expect(button(html({ ...done, mode: "image" }), "Upload & install")).toBeNull();
  });

  it("drops the package actions once the package is deleted", () => {
    const out = html({ ...done, mode: "convert-install", deleted: true });
    expect(out).toContain("Package deleted");
    for (const name of ["Stream & install", "Upload & install", "Delete package", "Launch on PS5"]) {
      expect(button(out, name)).toBeNull();
    }
    expect(button(out, "Convert another game")).not.toBeNull();
  });

  it("names the game and how much the package saved", () => {
    const out = html({ ...done, mode: "convert-install", packageBytes: 1024 }, { title: "Minecraft", sourceBytes: 2048 });
    expect(out).toContain("Installed on PS5 — Minecraft");
    expect(out).toContain("50%");
  });

  it("shows speed and time left for a build stage and overall", () => {
    const out = html({
      phase: "running",
      mode: "convert",
      source: "/g",
      host: null,
      stage: "compress",
      stageDone: 50 * 1024 * 1024,
      stageTotal: 100 * 1024 * 1024,
      startedMs: Date.now() - 20_000,
      stageStartedMs: Date.now() - 10_000,
      stageMs: {},
      jobId: "j",
      installTaskId: null,
      taskId: null,
      copiedSource: null,
      extractedSource: null,
      packagePath: null,
      titleId: null,
    });
    expect(out).toMatch(/MiB\/s/);
    expect((out.match(/left/g) ?? []).length).toBeGreaterThanOrEqual(2);
  });

  it("asks before deleting: the first press arms, the second confirms", () => {
    expect(deleteLabel(false)).toBe("Delete package");
    expect(deleteLabel(true)).toBe("Confirm delete");
  });

  describe("Zstd-only asset packs", () => {
    const choice = (over: Partial<Lz4Choice> = {}): Lz4Choice => ({
      readiness: { runtime_version: null, refusal: null, kind: "runtime" },
      on: true, onToggle: noop, profileName: null, onProfile: noop,
      installRuntime: false, onInstallRuntime: noop, kind: "zstd", onKind: noop,
      zstdLevel: 5, onZstdLevel: noop, ...over,
    });
    const idle = (format: "exfat" | "ffpkg", c = choice()) =>
      renderToStaticMarkup(<ImageChoice format={format} compress={false} onChoice={noop} lz4={c} />);

    it("offers only Zstd packing, including for exFAT", () => {
      for (const format of ["exfat", "ffpkg"] as const) {
        const out = idle(format);
        expect(out).toContain('data-testid="zstd-option"');
        expect(out).not.toContain('data-testid="lz4-option"');
        expect(out).not.toContain("AMPR LZ4 asset packs");
        expect(out).toContain("Tested 0.3.5");
        expect(lz4Active(format, choice())).toBe(true);
        expect(packOptions(format, choice())).toEqual({ zstdLevel: 5, zstdRuntime: "latest" });
      }
    });
    it("does not reintroduce an LZ4 control for an old queued choice", () => {
      expect(idle("exfat", choice({ kind: "lz4" }))).not.toContain('data-testid="lz4-option"');
    });
    it("packs folders with Zstd and refuses unsupported AMPR games", () => {
      expect(folderPacks(choice())).toBe(true);
      expect(folderPackOptions(choice())).toEqual({ level: 5, runtime: "latest" });
      const refused = choice({ readiness: { kind: "no_ampr", refusal: "unsupported" } });
      expect(folderPacks(refused)).toBe(false);
      expect(folderPackOptions(refused)).toBeUndefined();
      expect(lz4Active("exfat", refused)).toBe(false);
    });
    it("explains requirements before inspection and when packing is enabled", () => {
      const pending = renderToStaticMarkup(<ImageChoice format="ffpkg" compress={false} onChoice={noop} packsNote />);
      expect(pending).toContain("Zstd asset packs appear here");
      expect(idle("ffpkg")).toContain("A packed game only plays when ShadowMount+ mounts it.");
      expect(renderToStaticMarkup(<ZstdOption lz4={choice()} folder />)).toContain('data-testid="zstd-runtime"');
      expect(renderToStaticMarkup(<PacksNote lz4={choice()} folder />)).toBe("");
    });
  });
});
