import type { IDraggerProvider, IDraggersRegistry } from "./IDraggers";

export class DraggersRegistry<TViewer> implements IDraggersRegistry<TViewer> {
  private readonly draggers = new Map<string, IDraggerProvider<TViewer>>();

  getDraggerNames() {
    return [...this.draggers.keys()];
  }

  getProvider(name: string) {
    return this.draggers.get(name);
  }

  registerDragger(name: string, provider: IDraggerProvider<TViewer>) {
    this.draggers.set(name, provider);
  }
}

export function draggersRegistry<TViewer>() {
  return new DraggersRegistry<TViewer>();
}
