export interface IDragger {
  activate(): void;
  deactivate(): void;
  dispose(): void;
  readonly id: string;
}

export type IDraggerProvider<TViewer> = (viewer: TViewer) => IDragger;

export interface IDraggersRegistry<TViewer> {
  getDraggerNames(): string[];
  getProvider(name: string): IDraggerProvider<TViewer> | undefined;
  registerDragger(name: string, provider: IDraggerProvider<TViewer>): void;
}
