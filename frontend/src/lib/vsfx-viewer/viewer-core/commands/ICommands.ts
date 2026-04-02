export type ICommandHandler<
  TViewer,
  TArgs extends readonly unknown[] = readonly unknown[],
> = (
  viewer: TViewer,
  ...args: TArgs
) => unknown;

export interface ICommandService {
  executeCommand(name: string, ...args: unknown[]): unknown;
}

export interface ICommandsRegistry<TViewer> {
  getCommand(name: string): ICommandHandler<TViewer> | undefined;
  getCommandNames(): string[];
  registerCommand<TArgs extends readonly unknown[]>(
    name: string,
    handler: ICommandHandler<TViewer, TArgs>,
  ): void;
  registerCommandAlias(name: string, alias: string): void;
}
