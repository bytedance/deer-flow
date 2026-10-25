# DESIGN.md

The visual system of the DeerFlow frontend, as it ships today. It records what the
code already does so new UI matches it. The source of truth stays in code:
tokens in `src/styles/globals.css`, primitives in `src/components/ui/`. When this
file and the code disagree, fix one of them in the same change.

## Surfaces

The app has three surfaces that share one token set:

| Surface            | Routes                             | Character                                                                          |
| ------------------ | ---------------------------------- | ---------------------------------------------------------------------------------- |
| Workspace (app UI) | `/workspace/*`, `/login`, `/setup` | Dense, calm, task-focused. Most UI work happens here.                              |
| Docs               | `/[lang]/docs/*` (Nextra 4)        | Reading-first. Nextra theme with the landing `Header` in place of Nextra's navbar. |
| Landing and blog   | `/`, `/blog/*`                     | Brand-forward. The only place decorative effects are allowed.                      |

## Color

Colors are shadcn-style semantic tokens in OKLCH, defined on `:root` and `.dark`
in `globals.css` and exposed to Tailwind through `@theme inline`
(`bg-background`, `text-muted-foreground`, `border-border`, ...).

- **Neutrals carry a warm tint.** Light surfaces use hue 87.47 at chroma 0.0098
  (paper, not pure white). Dark surfaces use hue 106.64 at chroma 0.0036.
- **Primary is pure black in light mode and pure white in dark mode.** There is
  no brand hue; contrast does the work.
- **The only chromatic UI color is the focus ring** (`--ring`, blue at hue 255)
  plus `--destructive` (red). Charts use `--chart-1..5`.

| Token                  | Light                        | Dark                                 | Use                                 |
| ---------------------- | ---------------------------- | ------------------------------------ | ----------------------------------- |
| `--background`         | `oklch(0.9855 0.0098 87.47)` | `oklch(0.24 0.0036 106.64)`          | Page                                |
| `--foreground`         | `oklch(0.145 0 0)`           | `oklch(0.985 0 0)`                   | Body text                           |
| `--card` / `--popover` | `oklch(1 0.0098 87.47)`      | `oklch(0.238 / 0.205 0.0036 106.64)` | Raised surfaces, menus, popovers    |
| `--primary`            | `oklch(0 0 0)`               | `oklch(1 0 0)`                       | Primary buttons, strongest emphasis |
| `--secondary`          | `oklch(0.9455 0.0098 87.47)` | `oklch(0.3 0.0036 106.64)`           | Secondary buttons, input fills      |
| `--muted-foreground`   | `oklch(0.556 0 0)`           | `oklch(0.708 0 0)`                   | Secondary text, captions            |
| `--accent`             | `oklch(0.94 0.0098 87.47)`   | `oklch(0.32 0.0036 106.64)`          | Hover and active rows               |
| `--border` / `--input` | `oklch(0.922 / 0.88 ...)`    | `oklch(1 0 0 / 10% / 15%)`           | Hairlines, field borders            |
| `--ring`               | `oklch(0.58 0.18 255)`       | `oklch(0.74 0.16 255)`               | Focus outlines                      |
| `--destructive`        | `oklch(0.577 0.245 27.3)`    | `oklch(0.704 0.191 22.2)`            | Errors, delete                      |

Rules:

- Use semantic tokens, never raw hex or Tailwind palette colors, in app and docs
  UI. Exceptions that exist today are listed under **Known exceptions**.
- Tints are `color-mix(in oklch, var(--token) N%, transparent)` or Tailwind
  opacity modifiers (`bg-secondary/60`), so they follow the theme.
- Theme switching is `next-themes` with `attribute="class"` and system default.
  Every new color must work in both modes; check both before shipping.

## Typography

- **Sans** (`--font-sans`): the platform UI stack (`ui-sans-serif, system-ui`).
  Used for all UI and body text.
- **Serif** (Tailwind `font-serif`): reserved for the **DeerFlow wordmark** and
  a few brand moments (header, footer quote, auth pages, workspace header).
  Don't use it for UI labels or body text.
- **Mono** (`font-mono`): code, paths, IDs, token counts.
- Dark mode sets `font-weight: 300` on `.dark` to offset light-on-dark bloom.
  Don't fight it with per-component weights.
- Sizes are Tailwind's scale. UI text is `text-sm` (14px); body and reading text
  is `text-base` (16px); don't set body copy smaller than 14px.

## Shape, spacing, elevation

- **Radius**: `--radius` is 10px. `rounded-md` (8px) for controls, `rounded-lg`
  (10px) for cards and panels, `rounded-xl`+ only for large containers. Keep
  radii consistent within one component.
- **Spacing**: Tailwind's 4px scale. Page gutters are `px-4` on mobile.
- **Width**: `.container-md` steps 40/48/64/80rem; workspace panes use
  `--container-width-{xs,sm,md,lg}`.
- **Elevation**: borders before shadows. `shadow-xs` on outline buttons,
  `shadow-lg` only on overlays (sheets, dialogs, menus).

## Components

Build from `src/components/ui/` (shadcn on Radix) before writing new primitives:
`Button`, `Input`, `Textarea`, `Select`, `Dialog`, `Sheet`, `DropdownMenu`,
`Command`, `Tooltip`, `HoverCard`, `Tabs`, `Switch`, `Badge`, `Card`, `Empty`,
`Skeleton`, `Sonner` (toasts), and more.

- **Buttons** (`button.tsx`): `default` (primary), `outline`, `secondary`,
  `ghost`, `link`, `destructive`. Sizes `sm` (32px), `default` (36px), `lg`
  (40px), `icon*`. One `default` button per area; the rest are `outline` or
  `ghost`.
- **Icons**: `lucide-react` at `size-4` inside controls. `@radix-ui/react-icons`
  only where it is already used (e.g. the GitHub mark).
- **Empty states**: use `Empty` with a sentence that says what to do next, not
  only "No items."
- **Loading**: `Skeleton` for layout-shaped loading, a spinner only for short
  inline waits.
- **Overlays**: Radix `Sheet`/`Dialog` lock body scrolling and pointer events.
  Nested portals must stay inside the modal's allowed content region, above
  z-50, with pointer events enabled. Mobile docs search uses Headless UI's
  `Portal.Group` targeting the sheet content; z-index alone cannot permit scroll.
  See `components/landing/mobile-nav.tsx`.

## Docs (Nextra)

- The docs layout renders the landing `Header` instead of Nextra's navbar, and
  never renders Nextra's `<Head>`, so Nextra's `--nextra-*` variables are unset.
  Restyle Nextra parts with app tokens in `globals.css` (see the search panel
  rules) instead of defining `--nextra-*`.
- Search is Nextra's `<Search>` in the header's `search` slot (desktop) and the
  mobile menu sheet (below `sm`), localized via `t.home.search*`, with an
  `aria-label`. Matches use a soft foreground tint plus bold, not inverted
  blocks.
- Known gap: below 768px there is no control to open the docs sidebar.

## Motion

- Short, functional transitions: `transition-colors` on hover, Radix
  enter/exit animations, `tw-animate-css` utilities. Durations 150 to 300ms.
- Named animations live in `@theme` in `globals.css` (`fade-in`, `fade-in-up`,
  `loading-bar`, `skeleton-entrance`, ...). Reuse them before adding new ones.
- Respect `prefers-reduced-motion` for anything that loops or moves content.

## Accessibility

- Every input has a visible label or an `aria-label`; placeholders are hints,
  not labels.
- Icon-only buttons need `aria-label` (e.g. `aria-label="Open menu"`).
- Keep the visible focus ring (`focus-visible:ring-ring/50`); never remove
  outlines without a replacement.
- Touch targets in mobile-only UI are at least 44px tall.
- Body text contrast is at least 4.5:1 in both themes; `muted-foreground` is for
  secondary text only.

## Copy

- Utility language in the app: say what the area is or what the user can do.
- Every user-visible string goes through `src/core/i18n/locales/` with both
  `en-US` and `zh-CN` entries.
- Use the typographic ellipsis (`…`) in placeholders and loading text.

## Known exceptions

Landing-only decoration that does not follow the rules above. Don't copy these
into app or docs UI:

- `Section` headings use a white-to-gray gradient text (`bg-clip-text`), and
  `.golden-text` is a gold gradient.
- `.ambilight` is a rainbow glow, and the header's Star on GitHub button has a
  pink-to-violet blur behind it (`#ff80b5` to `#9089fc`).
- `galaxy`, `aurora-text`, `flickering-grid`, `magic-bento`, `spotlight-card`
  and `shine-border` in `components/ui/` are landing effects.
