import { getEngineUrl } from "../state/engine";
import { selectConsoleByAddress, useRosterStore } from "../state/roster";
import { isTauriEnv } from "./tauriEnv";

/** The web UI keeps its consoles per browser and per address, so a phone opening the page
 *  over Tailscale (another address than at home) starts with none. A self-hosted engine says
 *  which console it was set up for (`PS5_ADDR`); a browser with no console chosen takes it. */
export async function adoptEngineConsole(): Promise<void> {
  if (isTauriEnv() || useRosterStore.getState().profiles.length > 0) return;
  try {
    const r = await fetch(`${getEngineUrl()}/api/version`);
    if (!r.ok) return;
    const { ps5_addr } = (await r.json()) as { ps5_addr?: string | null };
    if (ps5_addr?.trim() && useRosterStore.getState().profiles.length === 0) {
      selectConsoleByAddress(ps5_addr.trim());
    }
  } catch {
    // No engine yet: the user picks the console as before.
  }
}
