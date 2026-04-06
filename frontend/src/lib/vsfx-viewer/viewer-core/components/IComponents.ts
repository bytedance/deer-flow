export type IComponentInstaller<TViewer> = (viewer: TViewer) => void | (() => void);

export interface IComponentsRegistry<TViewer> {
  getComponentNames(): string[];
  getInstaller(name: string): IComponentInstaller<TViewer> | undefined;
  registerComponent(name: string, installer: IComponentInstaller<TViewer>): void;
}
