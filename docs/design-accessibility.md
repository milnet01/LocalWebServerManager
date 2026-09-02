# LocalWebServerManager — Accessibility

> **Status:** Split out of [`docs/design.md`](design.md) on
> 2026-08-20 (LWSM-1157), which had reached 1223 lines and whose
> rule-14 gate capped at three loops without converging. The
> section below is that document's § Accessibility, **moved
> verbatim** — no promise, no check-table row and no non-negotiable
> changed in the move. What did change is the citations that
> crossed the new boundary: references to § Tokens, not colours
> and § Look and feel now name their file, and references to
> § Components name theirs.
> **Phase:** B — Design.
> **Source of truth for:** *what is* — who this app is built for,
> what magnifier use demands of the layout, and the check table
> that is the acceptance surface for every accessibility item.
> **Companion:** [`design-look-and-feel.md`](design-look-and-feel.md)
> defines the tokens whose contrast the floors below are stated
> against. `docs/standards/testing.md § T8` carries four of the
> checks below as executable tests. The rest of the design —
> architecture, components, detection, data flow, ADRs — stays in
> [`design.md`](design.md).

## Accessibility

**The primary user is partially sighted and reads with a screen
magnifier** (user, 2026-08-03). That is not a compliance
checkbox on this project — it is a description of who the app is
for, and it changes the layout, not just the settings screen.

### What magnifier use actually demands

A magnifier shows a small window onto the screen, and the user
pans it. Everything below follows from that one fact:

- **Status is a word first, a colour second.** A coloured dot is
  a small target carrying the most important information in the
  app — the wrong way round for someone panning a lens. Each row
  leads with the **state spelled out** ("running", "port
  blocked"). The full rule and its test are *Never colour alone*
  below; what magnifier use adds is that the word must come
  **first in the row**, not merely be present somewhere in it.
- **Related information sits together.** A project's name, state,
  port and controls are adjacent and readable **within one lens
  view — a 600 logical-pixel-wide window at the row's height, at
  100 % text size**,
  which is the budget the layout test asserts against — never name
  on the far left and state on the far right,
  which forces a pan and a memory test. This tempers the usual
  "generous spacing" advice: vertical rhythm stays generous,
  horizontal sprawl does not.
- **Feedback appears where the action happened.** A message in a
  far-off status bar is invisible to someone whose lens is on a
  button. Errors surface **next to the row that raised them**, not
  in a corner. Confirmations are the next bullet's, and land
  differently — a dialog is placed by the compositor, not by us.
- **Confirmations are parented to the window and centred on it**, so
  the compositor opens them over the list the user is working in
  rather than somewhere they have to go hunting for — a confirmation they cannot
  find is a confirmation they will dismiss blind. Note the mechanism:
  this is **not** `move()` on a dialog. Under Wayland an application
  cannot position its own window, and ADR-0007's KWin path
  deliberately skips transients so it never places a dialog. Modal
  parenting is what the framework will honour; anything stronger
  is a promise the platform refuses.

  **And modal parenting delivers less than this bullet claimed until
  2026-08-19.** Measured while closing LWSM-1032, against the pinned
  PySide6 6.11.1: Qt centres a `QMessageBox` on the parent's WINDOW,
  not on the parent widget. A box parented to the last of four rows
  and a box parented to the window produced the identical screen
  rectangle, overlapping the middle two rows and neither of the
  outer two. So "over that widget" is not something this application
  can promise for any particular row, and the bullet above now says
  *parented to the window and centred on it*, which is what Qt
  actually does. The check row below was narrowed to match; what is
  testable is that the dialog lands over the project list rather than
  in a corner of the screen, and that it is **application**-modal.

  **Not "modal to the window"** — that is Qt's `WindowModal`, which
  blocks `MainWindow` alone and leaves the tray's own per-project
  start/stop menu (`design.md` § Components) live while a trust prompt waits,
  which is the hole the modality exists to close. A `QMessageBox` is
  `ApplicationModal` from construction, measured 2026-08-19, so this
  is a property to assert rather than one to add.

  **A confirmation raised from the tray shows and raises the window
  first**, so there is a list for it to land over. `design.md` § Components gives
  the tray a per-project start/stop menu and closing the window hides
  to tray, so this is reachable with no window on screen — where
  "centred on the window" and the check row below are both
  meaningless. The window comes back; the dialog is not orphaned.

  **The alternative was considered and declined** (user, 2026-08-19):
  an inline confirmation on the row would satisfy the original wording
  exactly, and it would stop the trust prompt being modal — a user
  could start a second project while one is waiting for an answer,
  which is a change to ADR-0007's threat model rather than to this
  section's layout advice.
- **Nothing important is hover-only.** Hover states are easy to
  miss at magnification and impossible to discover by keyboard.
  Every affordance is visible at rest.

### The non-negotiables

**A high-contrast theme ships as a first-class option**, beyond
the six aesthetic ones: maximum-contrast text, heavy borders, a
thick focus ring, no decorative subtlety. Available in light and
dark — `contrast-light` and `contrast-dark` in
`design-look-and-feel.md` § Look and feel's table. This is an
assistive tool, not a seventh colour scheme, and it is not allowed
to regress: these two clear **7:1** (WCAG AAA)
against the 4.5:1 the other six must meet, so a change that
quietly softens them fails the build. `testing.md § T8` already
carries that floor — it names 4.5:1 for every theme and 7:1 for
these two — so it needs no amendment, and the row below points at
its check rather than asking for a second one. (Until 2026-08-19
this said T8 "today states one threshold for all themes" and that
LWSM-1031 would land the amendment. LWSM-1031 landed it; the
sentence was left describing the world before it.)

**An in-app text-size control**, independent of the desktop's
scaling — 100 % to 200 % — because desktop-wide scaling is a
blunt instrument when only one window needs to be bigger. The
layout must **reflow** at every step and must never **clip**: a
`QLabel` does not elide by default, it cuts, and the missing
characters leave no trace at all.

**Eliding is a different act, and it is allowed.** The row has a
width budget — § Everything else holds a row to one lens view — and
a long project name spends it, so the name and browser cells are
capped and cut with an ellipsis on purpose. What that costs must be
recoverable: **where text is elided the whole string stays reachable,
in a tooltip and in the accessible name.** Elision is a fitting
concern and must never reach the accessibility tree, so a screen
reader is read the full name and every control is named from it.

Until 2026-09-02 this said "never clip or truncate", and that the
200 % test asserted no text was elided. Both were wrong: the app has
elided deliberately since LWSM-1174, and that test measures each
cell against the string it actually renders, which is the elided one
— so it has always been a clipping check and never an elision one.
The rule the app follows is the one now written above.

**Never colour alone.** The commonest colour blindness is exactly
red/green. Every state the app can display carries **at least three
signals** — the word, a distinct glyph, and colour — and the set it
quantifies over is **what the row can render today**, which is not
ADR-0004's seven. Three of the seven are implemented
(`running (managed)`, `stopped`, plus `starting` from the overlay);
the other four (`running (wrong port)`, `running (foreign)`,
`port blocked`, `failed`) arrive with P06's classifier and earn their
glyph with the state rather than ahead of it. Two more render without
being derived states at all: `unknown`, which has its own token, and
`stopping`, which `design-look-and-feel.md` § Tokens, not colours
deliberately gives none and which therefore falls through to the body text colour.

**So `stopping` carries two signals, not three, and that is the
decision rather than a gap** — a colour of its own would say a
transient overlay is a state derived from observation, which is
exactly what `design-look-and-feel.md` § Tokens, not colours
refuses. The word and the glyph still distinguish it, which is what
the greyscale test checks. Every other displayable state carries all
three.

The test is blunt: *the status list must be fully readable in
greyscale* — compared over the **state cell**, which for this purpose
is the painted glyph column plus the state label, measured together
from the row's left edge. They are not one widget: the glyph is
painted by the row (LWSM-1071, so it stays out of the accessibility
tree) and the word is a `QLabel`. A comparison of the label alone
would miss the glyph, which is one of the three signals.

**Focus is unmissable.** A thick, high-contrast focus ring on
every focusable widget in every theme — the magnifier user's
"where am I?" depends on it entirely. The app never steals focus
from what the user is reading.

**Contrast.** Every text-on-background pair in **every** theme
meets **WCAG AA** — 4.5:1 for body text, 3:1 for large text and
for the non-text indicators that carry state. Contrast is
arithmetic, so this is a unit test over the palettes rather than
a matter of taste, and **a new theme cannot be added without
passing it.** The adopted finbreak palettes are checked on
arrival, not assumed: any pair that falls short is adjusted here
and the divergence recorded, since the source app had its own
reasons for its values.

**Full keyboard operation.** Every action — start, stop, restart,
open, rescan, centre on screen, custom actions — is reachable
without a mouse, with
a visible focus ring that meets contrast on every theme. Tab
order follows visual order. No action is available only via
double-click, hover, or a tray icon.

**Screen readers.** Every interactive widget gets an accessible
name, and a description (`setAccessibleName` /
`setAccessibleDescription`) where the name is not self-explanatory —
`coding.md § O8` clause 1 sets that condition, and this section does
not widen it. Status reaches a screen reader as
the same text *Never colour alone* already requires, so Orca
announces "project-b, running, port 5005" rather than an unnamed
icon — no separate accessibility-only string to drift. A state
change announces itself once, not on every poll.

**Respects the desktop, not our preferences.** System font family
and size, honouring the desktop's font scaling and high-DPI
settings rather than pinning pixel sizes — the in-app text-size
control multiplies that, it does not replace it. No animation
conveys information, and any decorative animation honours a
reduce-motion preference.

**Targets.** Clickable targets no smaller than 24×24 logical
pixels at 100 %, scaling with the text-size setting rather than
staying fixed while the text around them grows.

**This is tested, not asserted** — and the list is exhaustive on
purpose, because an accessibility claim with no test behind it is
decoration. `docs/standards/testing.md § T8` carries **four** of
the checks: contrast arithmetic across every theme, keyboard
reachability of every action, accessible names on every
interactive widget, and nothing clipped at 200 %.

The remaining promises above need surfaces T8 does not yet have,
so LWSM-1032 lands them alongside the four:

| Promise | How it is checked |
|---|---|
| Readable in greyscale (never colour alone) | every state's rendered **state cell** differs from every other after a luminance-only transform, thresholded to ink-or-no-ink. Not the whole row: button enablement differs by state, so a whole-row comparison passes without the state cell rendering anything distinct — measured 2026-08-19, and greyscale alone is not enough either, since two colours of different luminance are two different greys |
| High-contrast pair clears 7:1 | **already covered by `testing.md § T8`**, whose contrast check is parametrised across themes and applies the stricter floor to `contrast-light` / `contrast-dark`. Listed so the promise stays traceable, not so a second assertion gets written |
| Focus ring meets contrast in every theme | the same contrast arithmetic, over focus-ring vs background pairs |
| Targets ≥ 24×24 at 100 %, scaling with text size | measure every clickable widget's hit rect at 100 % and 200 % |
| A state change announces itself once, not per poll | count accessibility notifications across N polls with no state change; assert zero |
| No animation conveys information, and reduce-motion is honoured | assert no animation object exists across a real state change — there are none to suppress, so both halves hold together, and the row fails the day one is added |
| Confirmations appear over the list, and are application-modal | assert `windowModality() == ApplicationModal`, and that the dialog's screen rect overlaps the row list — the *result*, never that a parent was passed (ADR-0007). Narrowed from "overlaps the raising widget's" on 2026-08-19: Qt centres on the parent's window whichever widget is passed, so the original could not pass for the first or last row of a list long enough for the dialog to miss them — at one row it passes, which is exactly the fixture size that would have hidden this — and no code change would have made it (LWSM-1032). **The rect half is an assertion about Qt's own centring, taken headless, and cannot speak for the compositor** — under Wayland placement is KWin's (ADR-0007) and degrades honestly. The modality half holds on every platform |
| A confirmation raised with the window hidden shows it first | with the window hidden, drive the tray's start path and assert the window is visible before the dialog is shown. **Lands with the tray (P09)**, which is the only surface that can raise one with no window on screen; until then there is no path to drive and the row is stated rather than run |
| The state word is first in the row | assert the state label's x-position precedes every other cell's |
| Related information fits one lens view | assert name, state, port and controls all fall inside a 600 px-wide window **at 100 % text size**. Deliberately not held at 200 %: the text doubles and the row with it, which is the control doing its job — wrapping the row to preserve the number would put the state and its controls on different lines, which is the pan this budget exists to prevent |
| Elided text keeps its full string | where a cell renders a cut string, assert its tooltip holds the whole one and the row's accessible name does too — and that **every** control in the row is named from the full text rather than the rendered text. The last clause is the one that failed in practice: the controls read the label back, which has been the elided string since LWSM-1174, so a screen reader was given four identically-truncated names whose whole purpose is telling one project's buttons from another's. A short-named fixture cannot see it, because there the two strings are equal |
| Feedback appears next to its control | assert an error's rect overlaps the row that raised it |
| Nothing important is hover-only | assert every action is reachable without a hover event |
| Focus is never stolen | drive a poll cycle during editing; assert focus did not move |
| System font and scaling honoured | assert no widget pins a font family or pixel size, **and that a change to the application font reaches a row's labels and buttons** — measured by `fontMetrics()`, the metric the widget paints with, never by a width the row derives from its own font. Not-pinning is not sufficient: QStyleSheetStyle resolves a font onto every descendant, so with a style sheet installed an application font change reaches the window and stops there (`design-look-and-feel.md` § Look and feel) |

**Every promise in § What magnifier use actually demands and
§ The non-negotiables appears in one of those two lists** — those
two subsections, not § Everything else below, whose contents are
taste rather than promises. That is what makes the section
trustworthy: not that the tests all exist today — LWSM-1032 lands
the table's rows — but that a promise cannot be added here without
a row appearing beside it. A claim with neither is decoration, and
reviewing this section means checking that the two lists still
cover it.

### Everything else

One accent colour used sparingly so it means something; no
gradients pretending to be depth, no bevels, no icon-only buttons
without both a tooltip and an accessible name. A manager utility
should look like it belongs on the desktop it runs on, not like a
web page pretending to be an app.

