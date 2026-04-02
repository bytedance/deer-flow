import { defaultOptions, type IOptions, type ResolvedOptions } from "./IOptions";

export class Options {
  private current: ResolvedOptions;

  constructor(initial?: IOptions) {
    this.current = {
      ...defaultOptions(),
      ...initial,
    };
  }

  get value() {
    return this.current;
  }

  patch(next: IOptions) {
    this.current = {
      ...this.current,
      ...next,
    };

    return this.current;
  }

  reset() {
    this.current = defaultOptions();

    return this.current;
  }
}
