import {
  render as testingLibraryRender,
  type RenderOptions,
} from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

type TestProvidersProps = {
  children: ReactNode;
};

function TestProviders({ children }: TestProvidersProps) {
  return <>{children}</>;
}

function render(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return testingLibraryRender(ui, {
    wrapper: TestProviders,
    ...options,
  });
}

export * from "@testing-library/react";
export { render };
