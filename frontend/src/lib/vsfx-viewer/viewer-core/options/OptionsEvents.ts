import type { ResolvedOptions } from "./IOptions";

export type OptionsEventMap = {
  change: ResolvedOptions;
};

export type OptionsChangeEvent = {
  data: ResolvedOptions;
  type: "change";
};
