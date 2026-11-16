import { afterEach, describe, expect, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import {
  IncognitoModeProvider,
  useIncognitoMode,
  usePublishIncognitoMode,
} from "@/components/workspace/incognito-mode-context";

function Reader() {
  return <div data-testid="reader">{String(useIncognitoMode())}</div>;
}

function Publisher({ active }: { active: boolean }) {
  usePublishIncognitoMode(active);
  return null;
}

function renderMode(active: boolean | null) {
  return render(
    <IncognitoModeProvider>
      {active !== null && <Publisher active={active} />}
      <Reader />
    </IncognitoModeProvider>,
  );
}

function readerText() {
  return screen.getByTestId("reader").textContent;
}

afterEach(cleanup);

describe("incognito mode context", () => {
  test("defaults to an ordinary chat", () => {
    renderMode(null);

    expect(readerText()).toBe("false");
  });

  test("publishes an incognito chat before the first paint", () => {
    renderMode(true);

    expect(readerText()).toBe("true");
  });

  test("releases the flag when the surface switches back", () => {
    const { rerender } = renderMode(true);

    rerender(
      <IncognitoModeProvider>
        <Publisher active={false} />
        <Reader />
      </IncognitoModeProvider>,
    );

    expect(readerText()).toBe("false");
  });

  test("releases the flag when the incognito page unmounts", () => {
    const { rerender } = renderMode(true);

    rerender(
      <IncognitoModeProvider>
        <Reader />
      </IncognitoModeProvider>,
    );

    expect(readerText()).toBe("false");
  });
});
