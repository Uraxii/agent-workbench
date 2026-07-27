# Avoiding AI Generated UI Tells

## Purpose

LLM generated interfaces often look competent and still feel synthetic. The problem is not one bad color or one fashionable font. It is the compound effect of default choices that have no provenance: Tailwind grays, blue or indigo accents, Inter, uniform cards, rounded corners, soft shadows, cheerful copy, and generic icons. Each choice is common because it is safe, documented, easy to generate, and overrepresented in training examples. Together they read as the statistical center of modern web UI.

This document names the tells, explains the mechanism that produces them, and gives rules that force authored design: every visual decision must trace to a source, constraint, or product reason.

## 1. The tells

### 1.1 Color: framework palette instead of authored palette

**Tell: Tailwind default neutrals.**

Common values from the Tailwind v3 palette:

| Token | Hex | Tell |
|---|---:|---|
| `slate-950` | `#020617` | nearly black navy dashboard background |
| `slate-900` | `#0f172a` | default dark app shell |
| `slate-800` | `#1e293b` | card background or raised panel |
| `slate-700` | `#334155` | border, input, inactive tab |
| `slate-400` | `#94a3b8` | secondary text |
| `gray-900` | `#111827` | dark neutral background |
| `zinc-900` | `#18181b` | shadcn adjacent dark surface |
| `blue-500` | `#3b82f6` | primary action, focus ring, link |
| `indigo-500` | `#6366f1` | secondary accent, gradient stop |

The look is recognizable because the neutrals are not chosen for the product. They are the default utility classes that appear in tutorials, examples, AI generated snippets, and component demos.

**Tell: purple to blue gradient.**

Common pattern: `from-indigo-500 via-purple-500 to-blue-500`, or a headline gradient from `#6366f1` to `#3b82f6`. It implies energy without saying anything about the artifact review domain.

**Tell: dark navy dashboard.**

Common pattern: `bg-slate-950`, cards at `bg-slate-900` or `bg-slate-800`, borders at `border-slate-700`, text at `text-slate-100` and `text-slate-400`. It feels like a generated SaaS dashboard because it is the safe midpoint between developer tools, crypto dashboards, observability products, and Tailwind examples.

**Tell: semantic colors copied from defaults.**

Status colors often arrive as `green-500`, `yellow-500`, `red-500`, `blue-500`, or Bootstrap roles such as primary, success, warning, danger, and info. The system does not ask whether artifact review needs states like unreviewed, contested, stale, accepted, superseded, or blocked. It imports a generic success/warning/error worldview.

**Why it happens mechanically.**

LLMs predict likely continuations. For web UI prompts, the high probability continuation is Tailwind, Bootstrap, Material, or shadcn style code. Those systems publish examples with named color tokens, accessible enough defaults, and visually acceptable screenshots. The model learns that `slate`, `blue`, `indigo`, `rounded`, `shadow`, and `card` are safe. Without a source image, brand archive, physical material, or stated visual constraint, generation regresses to those defaults.

### 1.2 Type: Inter as a non-decision

**Tell: Inter everywhere.**

Inter is excellent, free, and designed for user interfaces. That is exactly why it became the default answer. In generated UI it often appears as the only face, with no product voice beyond clean neutrality.

**Tell: system font stack used as a decision.**

`font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` is a good fallback stack. It is not a design concept. When used as the whole typographic strategy, it says the interface never chose a voice.

**Tell: uniform weights and framework scale.**

Generated mockups lean on `text-sm`, `text-base`, `text-xl`, `font-medium`, `font-semibold`, and `tracking-tight`. The result is polished but textureless: every component speaks in the same tone, with the same spacing, rhythm, and emphasis.

**Tell: no contrast between voices.**

A professional review tool has at least four voices: navigation, evidence, annotation, metadata. Generated UI often gives all four the same sans face, same weight range, and same line height. A human authored system would make evidence dense, annotations readable, metadata quiet, and actions unmistakable.

**Why it happens mechanically.**

Inter and system stacks dominate tutorials, templates, Tailwind projects, Vercel style examples, shadcn installations, and React starter kits. LLMs therefore learn that type choice equals "use Inter". They also avoid unusual pairings because unusual choices are more likely to be judged risky.

### 1.3 Shape and depth: decorative softness

**Tell: one radius everywhere.**

The generated signature is `rounded-lg`, `rounded-xl`, or `rounded-2xl` applied to every card, button, input, modal, and badge. In pixel terms, the repeated look is usually 8px, 12px, or 16px. Nothing expresses which objects are containers, controls, or temporary overlays.

**Tell: soft diffuse shadows.**

Shadows appear as decoration rather than physics: `shadow-lg`, `shadow-xl`, `shadow-black/20`, or blurred overlays on dark surfaces. They do not answer what is above what, where the light is, or which element is interactive.

**Tell: glassmorphism.**

Common pattern: translucent surfaces, `backdrop-blur`, white borders at low opacity, gradient glows behind panels. It photographs well in examples but harms density and legibility in tools.

**Tell: gradient glows and blurred blobs.**

A blue or purple blurred circle behind a dashboard title is a strong AI tell. It fills empty space without adding information, brand, or hierarchy.

**Why it happens mechanically.**

Rounded cards and soft shadows are easy to express in utility classes, common in component libraries, and unlikely to be rejected as ugly. They are visual hedges. The model adds them because they increase perceived polish in a generic screenshot, not because the product asked for softness.

### 1.4 Layout: everything becomes a card

**Tell: all content on cards.**

Every object is wrapped in a white or slate card with padding, border, radius, title, icon, and subtitle. Cards are used for navigation, metrics, filters, comments, files, and empty states. The page becomes a tray of interchangeable rectangles.

**Tell: uniform grid of equal cards.**

Generated layouts prefer three or four equal columns, equal gaps, equal heights, and repeated icon plus heading plus text blocks. The rhythm is pleasant, but no item has editorial priority.

**Tell: centered hero with gradient headline.**

This belongs to marketing pages, not review tools. In a tool, the first screen usually needs orientation, work state, queue, recent changes, or a primary object, not a slogan.

**Tell: no density variation.**

Everything gets `p-4`, `p-6`, `gap-4`, or `space-y-4`. Dense metadata and sparse decisions receive the same treatment. Generated UI avoids compression because compression requires knowing what matters.

**Tell: no asymmetry.**

Generated pages center, balance, and equalize. Human interfaces often use uneven columns, pinned inspectors, narrow metadata rails, dominant canvases, or compressed tables because the task demands it.

**Why it happens mechanically.**

Cards and grids are the easiest generic layout primitives. They satisfy a prompt for "dashboard" or "modern app" with little domain knowledge. The model has learned the tutorial skeleton: shell, hero, stats, cards, table. It repeats the skeleton unless constrained by a task model.

### 1.5 Iconography and imagery: generic symbols

**Tell: emoji as icons.**

Emoji are fast placeholders. In production tool UI they often feel unserious, visually mismatched, and platform dependent. They also bypass the hard work of choosing an icon language.

**Tell: one popular icon set at one weight.**

Lucide, Heroicons, Phosphor, and Material Symbols can all work. The tell is not the set. The tell is using one outline weight everywhere, at the same size, with no optical adjustment against the type.

**Tell: generic illustration style.**

Floating abstract shapes, friendly empty state cartoons, and isometric dashboards read as stock SaaS. They rarely express the actual artifact, workflow, or failure mode.

**Why it happens mechanically.**

Icons and illustrations are selected from the most available public examples. LLMs can name popular sets and generate generic SVG motifs. They cannot infer a product specific mark language unless the prompt supplies sources and exclusions.

### 1.6 Copy: uniformly cheerful tool voice

**Tell: cheerful microcopy.**

"You're all set", "Let's get started", "Unlock insights", "Review with confidence", "Seamless collaboration", and "Beautiful artifacts" sound like launch page filler. In a review tool, users need status, evidence, risk, and next action.

**Tell: hollow labels.**

Labels like Overview, Insights, Activity, Recent, Smart, Enhanced, and Workspace often conceal missing domain structure. They are plausible nouns, not operational concepts.

**Tell: marketing voice inside a tool.**

Generated UIs frequently keep selling after the user is already inside the product. Real tools stop pitching and start helping.

**Why it happens mechanically.**

Training data overrepresents landing pages, demo apps, and docs examples. Their copy is broad, positive, and low commitment. The model avoids precise claims because precise claims require domain understanding and can be wrong.

## 2. The underlying cause

Generated UI defaults to the statistical center of its training data. The center of web UI has layers: Bootstrap normalized the component vocabulary, Material normalized elevation and semantic color roles, Tailwind normalized utility token composition, and shadcn normalized accessible React components with polished Tailwind defaults. None of those systems is bad. The problem is that generated design often combines their averages without inheriting their reasons.

"Make it look good" is an underspecified objective. The model satisfies it by choosing common, safe, tutorial proven patterns. Safe average choices reduce obvious errors, but they also erase provenance. The output says "modern app" before it says "self hosted artifact review".

The fix is not more adjectives. Prompts like "premium", "professional", "cinematic", "less AI", or "more bespoke" still leave the model free to sample the median. The fix is constraint and provenance:

- A palette must derive from a named source or measured color relation.
- A type choice must support a named product voice and be licensed for the deployment model.
- A layout must follow the work being done, not a dashboard template.
- Radius, shadow, and borders must encode hierarchy or interaction.
- Icons must match the type and the domain.
- Copy must name the real object, state, and action.

If a reviewer asks "why this?", every visible choice needs an answer stronger than "looks good".

## 3. How human authored design differs

### 3.1 Palette from a source, not swatches

Designers often begin with provenance: a photograph, printed artifact, material sample, archive, brand history, industry reference, or product object. For an artifact review app, sources might include:

- scanner bed blacks, inspection lamps, archival folders, proof marks, film contact sheets
- terminal phosphor, lab labels, manila tags, stamped approvals
- the actual artifacts users review, sampled only after privacy review

The source does not mean copying colors directly. It means the palette has a reason. A cold blue might come from inspection light. A warm neutral might come from paper. A red might come from stamped rejection marks.

### 3.2 Temperature biased neutrals

Default grays are often neutral in hue. Real palettes usually bias their neutrals. A dark professional tool can use:

- blue biased blacks for technical precision
- green biased grays for archival or terminal associations
- warm gray for document and paper adjacency
- purple avoided unless the product has a reason for it

The bias should be subtle and consistent across the ramp. Pure gray is rarely the most authored choice.

### 3.3 Typographic pairing with voice

Human authored type systems assign voices:

- interface face for controls and navigation
- text face for long notes, review comments, or documentation
- monospace for hashes, paths, diffs, timestamps, and artifact IDs

The pairing should have contrast without novelty. A tool can feel professional by pairing a sturdy interface sans with a serious serif for annotations, or a readable humanist sans with a precise mono for evidence.

### 3.4 Non uniform density

Real work has unequal importance. Good tools vary density:

- dense tables for scan work
- roomy inspectors for decisions
- compact metadata rails
- large preview regions for the artifact itself
- narrow action zones where mistakes are costly

Uniform spacing is a clue that the layout was generated before the task was understood.

### 3.5 Purposeful asymmetry

Asymmetry often comes from function: a dominant artifact preview, a right side evidence rail, a bottom timeline, or a persistent review queue. It creates hierarchy without decorative gradients.

### 3.6 Detail at the 1px level

Human authored UI is visible in small decisions:

- borders that separate planes without glowing
- selected states that survive low contrast displays
- focus rings with enough area and contrast
- table row dividers tuned separately from card borders
- icons optically aligned to cap height, not just centered in a box
- shadows reserved for overlays or draggable objects

Generated UI tends to spend attention on large decorative effects and miss these details.

### 3.7 Restraint in radius and shadow

Radius should express object type. Example:

| Object | Radius rule |
|---|---|
| data table, artifact frame | 2px to 4px |
| input, small button | 4px to 6px |
| popover, menu | 6px to 8px |
| modal or large panel | 8px maximum unless brand says otherwise |

Shadow should express elevation. If a surface is not above another surface, it probably needs a border, not a shadow.

### 3.8 Iconography matched to type

An icon set should match stroke contrast, corner style, and optical weight of the type. A geometric mono heavy interface can support square or technical icons. A humanist text system needs softer icons. Do not mix emoji, outline icons, filled status glyphs, and generic illustrations without an explicit hierarchy.

## 4. Typefaces for self hosted tools

The app must not make external network requests. Any typeface used in production must be bundled and self hosted, with license files kept in the repo or deployment artifact. Do not rely on Google Fonts or a CDN at runtime.

### 4.1 Free and self hostable options

| Role | Typeface | Why it helps avoid the Inter read | License status |
|---|---|---|---|
| interface | IBM Plex Sans | engineered, slightly industrial, more opinionated than Inter | SIL Open Font License 1.1, self hostable |
| interface | Atkinson Hyperlegible | distinctive readable forms, accessibility association | SIL Open Font License 1.1, self hostable |
| interface | Source Sans 3 | workmanlike, less Vercel coded than Inter | SIL Open Font License 1.1, self hostable, not reverified in this pass |
| text | Source Serif 4 | serious editorial voice for comments and review notes | SIL Open Font License 1.1, self hostable |
| text | Newsreader | high readability, document flavor | SIL Open Font License likely via Google Fonts, not reverified in this pass |
| monospace | JetBrains Mono | precise developer tool voice, strong code readability | SIL Open Font License 1.1, self hostable |
| monospace | IBM Plex Mono | pairs with Plex Sans, technical but warmer than many monos | SIL Open Font License 1.1 by family license, self hostable |
| monospace | Iosevka | dense, technical, excellent for tables and code | OFL or custom open license depending package, not reverified in this pass |

### 4.2 Commercial options

Commercial faces can be excellent, but the deployment license must explicitly allow self hosting in this app. Do not assume webfont, desktop, app, and server rights are the same.

| Role | Typeface | Use case | License status |
|---|---|---|---|
| interface | Graphik | restrained professional SaaS without Inter's exact texture | commercial, verify self hosting rights with Commercial Type |
| interface | Neue Haas Grotesk | neutral but more authored than default system stacks | commercial, verify with Monotype or licensed distributor |
| text | Lyon Text | serious review and editorial notes | commercial, verify with Commercial Type |
| monospace | Operator Mono | expressive code and annotation voice | commercial, verify with Hoefler and Co. |

### 4.3 Credible pairings for a dark professional review tool

**Pairing A: industrial archive.**

- Interface: IBM Plex Sans
- Text and comments: Source Serif 4
- Code, paths, hashes: IBM Plex Mono or JetBrains Mono
- Mood: technical, serious, self hosted, not startup glossy
- License: all verified as SIL Open Font License 1.1 if using Plex, Source Serif 4, and JetBrains Mono

**Pairing B: accessible inspection bench.**

- Interface: Atkinson Hyperlegible
- Text and comments: Source Serif 4
- Code, paths, hashes: JetBrains Mono
- Mood: legible, humane, evidence first
- License: all verified as SIL Open Font License 1.1

**Pairing C: dense operator console.**

- Interface: IBM Plex Sans Condensed or IBM Plex Sans
- Text and comments: IBM Plex Sans
- Code, paths, hashes: Iosevka or IBM Plex Mono
- Mood: compact, technical, high information density
- License: Plex verified as SIL Open Font License 1.1; Iosevka not reverified in this pass

### 4.4 Type rules

Pass rules for implementation:

- Choose at least two typographic voices if the app has both controls and long form review text.
- Set the fallback stack as fallback only, not as the design decision.
- Limit weights. Two or three weights usually beat five.
- Tune line height by role: dense metadata, normal controls, generous comments.
- Keep font files local and include license text.
- Test actual artifact names, long paths, hashes, timestamps, and reviewer comments before accepting the type system.

## 5. Color method

### 5.1 Build a neutral ramp in a perceptual space

Use OKLCH or another perceptual color space because lightness changes track perceived lightness better than hex, RGB, or HSL. That makes contrast, ramps, and hue shifts easier to reason about. CSS Color Module Level 4 defines `oklch()` and `oklab()`.

Method:

1. Pick a source and name it.
2. Choose a hue bias from the source, usually subtle for neutrals.
3. Set chroma low for neutrals, but not zero.
4. Step lightness deliberately, with tighter steps where UI surfaces cluster.
5. Convert to hex for implementation only after checking gamut and contrast.
6. Test the ramp on real screens and with real content.

### 5.2 Worked neutral ramp

Source: inspection bench under cool task light, with dark coated metal and paper evidence tags. Bias: cool blue green. Goal: dark professional tool that does not use Tailwind slate directly.

| Token | OKLCH | Hex | Use |
|---|---:|---:|---|
| `ink-0` | `oklch(12% 0.018 230)` | `#071015` | app background |
| `ink-1` | `oklch(16% 0.018 230)` | `#0d171d` | shell surface |
| `ink-2` | `oklch(21% 0.018 230)` | `#172229` | card surface |
| `ink-3` | `oklch(28% 0.016 230)` | `#26323a` | raised surface, input |
| `ink-4` | `oklch(38% 0.014 230)` | `#3f4b53` | border strong |
| `ink-5` | `oklch(55% 0.012 230)` | `#728089` | muted text |
| `ink-6` | `oklch(72% 0.010 230)` | `#a7b1b8` | secondary text |
| `ink-7` | `oklch(88% 0.008 230)` | `#d8dee2` | primary text |
| `ink-8` | `oklch(95% 0.006 230)` | `#eef2f4` | high emphasis text |

The exact hexes should be verified in the design tool or color library used by implementation. The important part is the method: constant hue bias, low chroma, controlled lightness, and named source.

### 5.3 Pick one accent with provenance

Do not start from `blue-500`. Pick an accent from a source and state its job. Example:

- Source: blue green inspection tape on artifact bins.
- Role: primary focus, selected item, current review object.
- Constraint: never used for success or decoration.
- Candidate: `oklch(68% 0.105 205)` after contrast checking.

One accent can carry identity if it is used consistently. Multiple saturated accents usually recreate the framework palette tell.

### 5.4 Derive semantic status colors

Semantic colors need both meaning and distinguishability. Do not rely on hue alone.

Rules:

- Define product states first: accepted, rejected, needs evidence, stale, conflicted, blocked.
- Assign hue, label, icon, and pattern or border treatment for each state.
- Check color vision deficiency simulation for deuteranopia, protanopia, and tritanopia.
- Keep status colors visually separate from the brand accent.
- Use lightness contrast as well as hue contrast.
- Verify text contrast against WCAG 2.2: 4.5:1 for normal text, 3:1 for large text at Level AA.

Example status direction:

| State | Visual direction | Non color cue |
|---|---|---|
| accepted | low chroma green, not neon | check mark, solid left rule |
| rejected | red leaning slightly warm | X mark, double border or hard stop label |
| needs evidence | amber or ochre | document icon, dotted left rule |
| conflicted | violet or magenta only if not used as brand | split marker, two tone border |
| stale | desaturated gray brown | clock icon, muted stripe |

### 5.5 Verify contrast and behavior

Before shipping:

- Check every text and icon color against the exact background it appears on.
- Check focus rings against both normal and hovered surfaces.
- Check disabled controls for recognizability, not only contrast exemption.
- Check charts and status pills in color vision deficiency simulation.
- Print or screenshot the design in grayscale. If state disappears, the design fails.
- Test the palette in the actual app, not only in a palette page.

## 6. Pass or fail checklist

A design fails if any answer below is "no".

### Color

- Can every palette color be traced to a named source, product reason, or measured ramp rule?
- Are `#3b82f6`, `#6366f1`, `#0f172a`, `#111827`, and `#18181b` absent unless explicitly justified?
- Is there no decorative purple to blue gradient?
- Are semantic colors derived from product states rather than Bootstrap or Tailwind role names?
- Do status colors remain distinguishable under color vision deficiency simulation?
- Does all normal text meet at least 4.5:1 contrast, and large text at least 3:1?

### Type

- Is Inter absent, or is there a specific reason stronger than "clean UI font"?
- Is the system font stack only a fallback, not the typographic concept?
- Are there distinct voices for controls, review text, metadata, and code where needed?
- Are font files self hosted with license files included?
- Have long paths, hashes, timestamps, and comments been tested in the chosen faces?

### Shape and depth

- Are radius values assigned by object type rather than one global `rounded-xl` habit?
- Are 8px, 12px, and 16px radii avoided unless they serve a hierarchy rule?
- Are shadows reserved for actual elevation, overlays, or drag states?
- Is `backdrop-blur` absent unless transparency is required by the task?
- Are gradient glows and blurred blobs absent?

### Layout

- Is the primary artifact or work object visually dominant?
- Is at least one area denser or quieter because the task demands it?
- Are cards used only where a grouped object needs a container?
- Is the layout not a uniform grid of equal cards?
- Is there purposeful asymmetry tied to workflow?
- Is there no centered marketing hero inside the tool surface?

### Iconography and imagery

- Are emoji absent from production navigation, status, and action controls?
- Does the icon stroke weight match the type weight and size?
- Are status icons distinguishable without color?
- Are empty states domain specific rather than stock SaaS illustrations?

### Copy

- Does every label name a real object, state, or action in the product?
- Is marketing copy absent from authenticated tool screens?
- Are empty states specific about what happened and what to do next?
- Are cheerful phrases removed where the user needs evidence or risk?

### Provenance

- Can a reviewer ask "why this?" for color, type, layout, shape, icon, and copy and get a concrete answer?
- Is at least one visible design decision derived from the artifact review domain rather than a web UI framework?
- Would the design still make sense if all gradients, glows, and shadows were removed?

## Sources

Verified during this pass:

- Tailwind Labs, "Customizing Colors", Tailwind CSS v3 documentation, URL: https://v3.tailwindcss.com/docs/customizing-colors. Verified default names and values including `slate-900 #0f172a`, `blue-500 #3b82f6`, and `indigo-500 #6366f1`.
- Tailwind Labs, "Colors", Tailwind CSS documentation, URL: https://tailwindcss.com/docs/colors. Verified current color docs list palettes such as slate, gray, zinc, blue, and indigo and expose OKLCH tokens.
- Rasmus Andersson, "Inter typeface family", URL: https://rsms.me/inter/. Verified Inter is described as free and open source under SIL Open Font License 1.1.
- IBM, "IBM Plex", URL: https://www.ibm.com/plex/. Page fetch was blocked in this pass, so licensing was verified from the project license instead.
- IBM, "IBM Plex License", GitHub, URL: https://github.com/IBM/plex/blob/master/LICENSE.txt. Verified SIL Open Font License 1.1.
- Adobe, "Source Serif License", GitHub, URL: https://github.com/adobe-fonts/source-serif/blob/release/LICENSE.md. Verified SIL Open Font License 1.1.
- Braille Institute of America, "Atkinson Hyperlegible License", GitHub, URL: https://github.com/googlefonts/atkinson-hyperlegible/blob/main/OFL.txt. Verified SIL Open Font License 1.1.
- JetBrains, "JetBrains Mono License", GitHub, URL: https://github.com/JetBrains/JetBrainsMono/blob/master/OFL.txt. Verified SIL Open Font License 1.1.
- Bootstrap team, "Color", Bootstrap 5.3 documentation, URL: https://getbootstrap.com/docs/5.3/customize/color/. Verified semantic role map: primary, secondary, success, info, warning, danger, light, dark.
- shadcn, "Documentation", URL: https://ui.shadcn.com/docs. Verified shadcn/ui describes itself as a component code distribution platform, not a component library.
- W3C, "Web Content Accessibility Guidelines (WCAG) 2.2", 2024, URL: https://www.w3.org/TR/WCAG22/. Verified Level AA contrast thresholds of 4.5:1 for normal text and 3:1 for large text.
- W3C, "CSS Color Module Level 4", URL: https://www.w3.org/TR/css-color-4/. Verified `oklab()` and `oklch()` color functions.
- Andrey Sitnik, "OKLCH in CSS: why we moved from RGB and HSL", Evil Martians, URL: https://evilmartians.com/chronicles/oklch-in-css-why-quit-rgb-hsl. Verified practical reasons for OKLCH in CSS and design systems.
- Kate Moran, "Flat Design: Its Origins, Its Problems, and Why Flat 2.0 Is Better for Users", Nielsen Norman Group, 2015, URL: https://www.nngroup.com/articles/flat-design/. Verified usability issue of removing signifiers and appropriate use of subtle depth cues.

Cited with caution:

- Material Design color system, URL checked: https://m2.material.io/design/color/the-color-system.html. Fetch returned only minimal page identity, not enough detail to verify color role specifics in this pass.
- Google Fonts pages for IBM Plex Sans, Source Serif 4, Atkinson Hyperlegible, JetBrains Mono, and Inter were reachable, but license text was not exposed in fetched content. Licenses above were verified from upstream project license files where listed.
- Newsreader, Source Sans 3, Iosevka, Graphik, Neue Haas Grotesk, Lyon Text, and Operator Mono are included as practical candidates, but their current license terms or self hosting rights were not verified in this pass. Verify before use.
