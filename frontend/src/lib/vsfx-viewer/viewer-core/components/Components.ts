import type {
  IComponentInstaller,
  IComponentsRegistry,
} from "./IComponents";

export class ComponentsRegistry<TViewer> implements IComponentsRegistry<TViewer> {
  private readonly components = new Map<string, IComponentInstaller<TViewer>>();

  getComponentNames() {
    return [...this.components.keys()];
  }

  getInstaller(name: string) {
    return this.components.get(name);
  }

  registerComponent(name: string, installer: IComponentInstaller<TViewer>) {
    this.components.set(name, installer);
  }
}

export function componentsRegistry<TViewer>() {
  return new ComponentsRegistry<TViewer>();
}
