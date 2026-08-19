# LocalWebServerManager — Look and feel

> **Status:** Split out of [`docs/design.md`](design.md) on
> 2026-08-20 (LWSM-1157), which had reached 1223 lines and whose
> rule-14 gate capped at three loops without converging. The
> section below is that document's § Look and feel, **moved
> verbatim** — no rule here changed in the move. What did change
> is the citations that crossed the new boundary: references to
> § Accessibility now name its file.
> **Phase:** B — Design.
> **Source of truth for:** *what is* — the theme layer, the
> palettes, and the token contract every widget colours through.
> **Companion:** [`design-accessibility.md`](design-accessibility.md)
> holds the contrast floors these tokens are solved against, and
> is the other half of the same contract. The rest of the design
> — architecture, components, detection, data flow, ADRs — stays
> in [`design.md`](design.md).

## Look and feel

The default Qt widget style looks like a 2005 configuration
dialog, which is not what a tool you keep open all day should
look like. The app ships its own **theme layer**: a set of
semantic colour tokens, one palette per theme, applied as a
generated Qt style sheet at runtime.

**Themes are switchable without a restart** — changing one
regenerates the style sheet and reapplies it. The choice lives in
`settings.json`.

### The palettes — adopted from `finbreak`, not invented

`finbreak` already solved this well and the user likes the
result, so this project **adopts its theme system rather than
writing a parallel one** (`docs/standards/coding.md § 1.3`, reuse
before rewriting).

**The palette values are copied into this repository, not
referenced out of it.** `finbreak` is a separate, unversioned
project that lives outside this tree at a path depending on the
user's own scan root, so a design document that points at it is
not buildable by anyone else — and this repository is public.
LWSM-1031 lands the values as a table in this repo (one row per
token, one column per theme); `finbreak` is cited as
**provenance**, meaning where the values came from and who to ask
about them, never as the source an implementer reads. Until that
table exists the theme layer has no contract, which is why
LWSM-1031 owns transcribing it as its first step rather than its
last.

**Eight palettes** — six aesthetic (three light, three dark) plus
the two high-contrast ones `design-accessibility.md` § Accessibility requires. All
eight are themes in every respect that matters to the code: same
token set, same contrast test, same picker.

| Theme | Kind | Character |
|---|---|---|
| **midnight** *(default dark)* | dark | Deep ground, warm gold accent. |
| **graphite** | dark | Neutral grey with a cool blue accent — the "long session" theme. |
| **emerald** | dark | Dark with a green accent. |
| **ledger** *(default light)* | light | Warm paper ground, muted gold accent. |
| **parchment** | light | Warmer still, softer contrast. |
| **mint** | light | Cool light ground, green accent. |
| **contrast-dark** | dark | Maximum-contrast text, heavy borders, thick focus ring, no decorative subtlety. |
| **contrast-light** | light | The same, on a light ground. |

Plus **Follow system**, which tracks the desktop's light/dark
preference. It resolves to `midnight` or `ledger` normally, and to
`contrast-dark` or `contrast-light` when the desktop reports a
high-contrast preference — so a user who has already told their
desktop they need contrast does not have to tell this app too.
Dark is the default, per the user's stated preference.

### Tokens, not colours

A theme is **nine semantic tokens plus an `is_dark` flag**, the
same shape finbreak uses:

`window` · `base` · `alt_base` · `text` · `muted_text` ·
`accent` · `accent_soft` · `attention` · `border` — and
`is_dark`, which drives the light/dark grouping in the picker.

This project **extends** that set with **eight** — one per derived
state, which is ADR-0004's seven, **plus `state_unknown`, which is
not one of them**: `unknown` means nobody has looked yet rather than
a state observation produced, and it renders in every list before the
first poll returns, so leaving it untokened would show it in body
text. ADR-0004's list therefore defines the seven, not the set:
`state_running` (`running (managed)`) · `state_starting`
(`starting`) · `state_wrong_port` (`running (wrong port)`) ·
`state_foreign` (`running (foreign)`) · `state_blocked`
(`port blocked`) · `state_failed` (`failed`) · `state_stopped`
(`stopped`) · `state_unknown` (`unknown`).

**The focus ring takes `accent` and gets no token of its own**, so
every palette gets a legible ring out of the contrast it already has
to prove for its accent — one fewer value to solve for per palette,
and one that cannot drift from it. `Theme.focus_ring_color()`
expands it, because `§ O7` forbids a widget building a `QColor`.

**A generated style sheet costs font inheritance, and that is the
price of theming this way.** QStyleSheetStyle resolves a font onto
every descendant, which marks it explicitly set — so an application
font change reaches the window and propagates no further, and the
in-app 100-200 % control moves nothing the user reads unless the new
font is pushed down by hand. Measured 2026-08-19 (LWSM-1032): at
200 % the state column widened from 53 px to 103 px around text that
stayed at 9 pt. `MainWindow.changeEvent` re-pushes to every
descendant; anything else adopting a style sheet inherits this.

`stopping` gets no token: it is the optimistic overlay's transient
label, not a state derived from observation (ADR-0004, `design.md` § State
management). Adding a state to ADR-0004 means adding a token here,
which the contrast test in `docs/standards/testing.md § T8` then
parametrises over automatically.

Widgets name tokens, never colours. Adding a theme means adding a
palette, never touching a widget, and
`docs/standards/coding.md § O7` makes a literal colour in widget
code a review failure. Tokens expand into a `QPalette` (so native
widgets follow) **and** a generated style sheet (for the polish
Qt's palette cannot express) — finbreak's two-layer split, which
is worth copying because a stylesheet-only theme leaves stock
dialogs looking wrong.

The one deliberate divergence: finbreak stores the choice in
`QSettings`; this project stores it in `settings.json` with
everything else, per `docs/standards/coding.md § O6`.

