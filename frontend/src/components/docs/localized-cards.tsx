import { Cards as NextraCards } from "nextra/components";
import type { ComponentProps } from "react";

import { LocalizedCard } from "./localized-mdx-components";

function LocalizedCardsRoot(props: ComponentProps<typeof NextraCards>) {
  return <NextraCards {...props} />;
}

export const LocalizedCards = Object.assign(LocalizedCardsRoot, {
  Card: LocalizedCard,
  displayName: "LocalizedCards",
});
