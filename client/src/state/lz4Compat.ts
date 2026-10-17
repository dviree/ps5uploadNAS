import { create } from "zustand";

import { fetchCompat, type CompatData } from "../api/lz4";

/** The community's LZ4 game reports, read once per session (and on Refresh) and shared by
 *  Convert Games' My games and Compatibility tabs. */
interface CompatState {
  data: CompatData | null;
  loading: boolean;
  error: string | null;
}

export const useLz4Compat = create<CompatState>(() => ({
  data: null,
  loading: false,
  error: null,
}));

let inFlight: Promise<void> | null = null;

export function loadLz4Compat(force = false): Promise<void> {
  const s = useLz4Compat.getState();
  if (inFlight) return inFlight;
  if (s.data && !force) return Promise.resolve();
  useLz4Compat.setState({ loading: true, error: null });
  inFlight = fetchCompat()
    .then((data) => useLz4Compat.setState({ data, loading: false }))
    .catch((e: unknown) =>
      useLz4Compat.setState({
        loading: false,
        error: e instanceof Error ? e.message : String(e),
      }),
    )
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}
