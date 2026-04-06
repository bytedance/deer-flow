import type { ICommandHandler, ICommandsRegistry } from "./ICommands";

export class CommandsRegistry<TViewer> implements ICommandsRegistry<TViewer> {
  private readonly aliases = new Map<string, string>();
  private readonly commands = new Map<string, ICommandHandler<TViewer>>();

  getCommand(name: string) {
    const target = this.aliases.get(name) ?? name;

    return this.commands.get(target);
  }

  getCommandNames() {
    return [...this.commands.keys()];
  }

  registerCommand<TArgs extends readonly unknown[]>(
    name: string,
    handler: ICommandHandler<TViewer, TArgs>,
  ) {
    this.commands.set(name, handler as ICommandHandler<TViewer>);
  }

  registerCommandAlias(name: string, alias: string) {
    this.aliases.set(alias, name);
  }
}

export function commandsRegistry<TViewer>() {
  return new CommandsRegistry<TViewer>();
}
