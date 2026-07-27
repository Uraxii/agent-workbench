# Artifact Server Iconography

## Purpose and constraints

The artifact review server needs a quiet icon system for a private, self-hosted review app. The app reviews images, render galleries, HTML reports, and code or text artifacts created by automated agents and checked by one human. It is dark first, WCAG AA, React and TypeScript, and it must make no external network requests. Icon assets must therefore be permissively licensed, bundled with the app, and usable without a CDN, remote font request, or hosted stylesheet.

The design risk is visual slop. A generated interface in 2026 often reaches for Lucide or Heroicons at one default outline weight, repeats icons too densely, and treats the icon set as the design language. This app should not do that. Icons are a notation layer, not the product identity.

## Recommendation

Use **Phosphor Icons** as the base set, through `@phosphor-icons/react`, with local bundling only. The license is **MIT License**. Phosphor is self-hostable through npm packages and raw SVG assets. It has a broad but not infinite catalog, a React package, and multiple optical weights controlled by one design family. Use the regular weight for most UI, bold only at `16px` when the regular stroke thins out in dense dark mode, and filled only for persistent state badges where the silhouette must survive color loss.

Do not use Lucide as the primary set for this product. Lucide is good, permissive, and efficient, but it is also the current generated-app default. The existing internal note chose it for valid first-build reasons. This document replaces that stance because the user's explicit feedback names that exact look as a tell. Lucide can remain a fallback reference during implementation, but the shipped system should not read as Lucide everywhere at one `2px` outline weight.

## Candidate sets

Counts change often. Counts below are from project pages when the fetched page stated them, otherwise from the current npm package or repository package inspected during this research. If a count or license was not visible from the checked source, it is marked as uncertain rather than guessed.

| Set | License | Self-hostable | Count checked | Drawing style | Typeface fit | Verdict |
|---|---|---:|---:|---|---|---|
| Lucide | ISC License. Some Feather-derived icons also carry MIT notices in the repo license file. | Yes. React package, SVG package, tree-shakeable imports. | Project page showed `1754` icons. Current React package had more component modules, so exact shipped count depends on version. | Outline SVG, 24px grid convention, rounded caps and joins, commonly `2px` stroke, adjustable stroke width. | Pairs with neutral grotesks and interface sans faces such as Inter, Geist, IBM Plex Sans. | Technically strong, visually overfamiliar. Reject as primary for this app. |
| Phosphor | MIT License, copyright Phosphor Icons, 2023 in the checked core license. | Yes. `@phosphor-icons/react`, `@phosphor-icons/core`, raw SVG assets by weight. | React package v2.1.10 exposed `1512` icon components in the checked CSR build. Public page fetch did not state a count. | Friendly geometric family with weights including thin, light, regular, bold, fill, and duotone. Stroke details were not stated on the fetched pages. | Works with warm humanist or geometric sans faces. Good with IBM Plex Sans, Inter, Source Sans 3, and Atkinson Hyperlegible. | Recommended. Less default than Lucide, flexible weights, broad enough for product UI. |
| Tabler Icons | MIT License, also sold as a personal and commercial bundle on the project page. | Yes. React package, SVG, sprite, webfont, design files. | Project page stated `6166` icons. | 24 by 24 grid, `2px` stroke, outline and filled styles, square but rounded enough for UI. | Best with utilitarian sans faces, especially Inter, IBM Plex Sans, and Roboto. | Excellent catalog, but too broad and close to generated SaaS defaults if used everywhere. |
| Remix Icon | Remix Icon License v1.0 on the repo license page. npm metadata reported Apache-2.0, so verify with counsel before use. | Yes. npm package contains SVG files. | Checked npm package v4.9.1 had `3231` SVG files. | Neutral system symbols, many outline and filled pairs, more pictographic and denser than Lucide. Grid and stroke details were not visible in fetched sources. | Pairs with Roboto, Noto Sans, Inter, and compact enterprise UI typography. | Usable, but license ambiguity between repo and npm metadata makes it less clean for this app. |
| Iconoir | MIT License. | Yes. React, Vue, Flutter, Swift, CSS, font, Figma, raw formats are advertised. | Project page stated `1671` icons. | Outline first, adjustable optical size, stroke weight, and color on the project page. Often airy and distinctive. | Pairs with modern grotesks and editorial sans faces. | Strong alternative if Phosphor feels too friendly. Some icons are more decorative than review UI needs. |
| Material Symbols | Google material-design-icons repo states Apache License Version 2.0 for icons. Fontsource Material Symbols package reported OFL-1.1. | Yes, but avoid Google Fonts runtime requests. Use local variable fonts or local SVG package only. | Fetched pages did not state total count. | Outlined, Rounded, and Sharp styles. Variable axes include optical size `20` to `48`, weight `100` to `700`, grade `-50` to `200`, and fill `0` to `100`. Perfect pixel-grid alignment only at `20px` and `24px` per the checked repo text. | Designed around Material and Roboto. Can clash with bespoke dark tools. | Usable only if the whole UI follows Material. Otherwise it brings too much Google product flavor. |
| IBM Carbon Icons | Apache License, Version 2.0, copyright IBM Corp. | Yes. `@carbon/icons-react`. | React package v11.84.0 exposed `2739` ES icon modules in the checked package. | Enterprise icon language with strong grid discipline and multiple size exports in the broader Carbon system. Stroke specifics were not visible in fetched pages. | Best with IBM Plex Sans and Carbon-like dense enterprise UI. | Very credible for review tooling, but visually says IBM enterprise. Consider if the whole design uses IBM Plex. |
| Microsoft Fluent UI System Icons | MIT License, copyright Microsoft Corporation, 2020. | Yes. React package, SVG atoms, icon fonts, and inline SVG guidance in the repo. | Checked React package had `2893` SVG atom modules. | Regular, Filled, Light, and Color families in package files. Friendly Microsoft product style. | Pairs with Segoe UI, Aptos, and soft humanist sans faces. | High quality, but the Microsoft product association is strong. Not ideal for an agent artifact tool. |
| Bootstrap Icons | MIT License, copyright The Bootstrap Authors. | Yes. SVGs, SVG sprite, web fonts, npm. | Project page stated over `2000`; checked npm package v1.13.1 had `2078` SVG icons under `package/icons`. | Mostly filled or outline glyphs depending on icon, 16px Bootstrap heritage, practical rather than refined. | Pairs with Bootstrap-style system UI and plain sans faces. | Reliable, but too generic and uneven for a design-forward review surface. |
| Radix Icons | MIT License. | Yes. `@radix-ui/react-icons`, downloadable SVG zip. | Checked React package had `318` icon declaration files. | Crisp `15px` icons, minimal and sharp, optimized for Radix primitive controls. | Pairs with small dense UI type such as Inter, Geist, and system UI. | Excellent for primitive controls, too small and sparse as the only product icon set. |
| Feather | MIT License, copyright Cole Bemis. | Yes. SVG download and npm package. | Checked npm package had `288` SVG icons. | 24px, `2px` stroke, simple rounded outline. | Pairs with light neutral sans faces. | Historically important, but too small and now visually absorbed into Lucide. Not enough for this app. |
| Primer Octicons | MIT License, copyright GitHub Inc. | Yes. React, JavaScript, Ruby packages. | Checked React package v19.31.0 had `383` icon components. | Handcrafted GitHub product icons, mostly compact filled and outline forms. Size details were not visible in fetched pages. | Pairs with system UI, Mona Sans, Inter, and developer tooling typography. | Good lesser-used option for code review surfaces. Catalog is smaller and GitHub association is strong. |
| Teenyicons | MIT License. | Yes. npm package, SVG directories, outline and solid sprite files. | Checked npm package had `600` outline and `600` solid SVG files. | Tiny minimal `1px` icons on a `15x15` grid, outline and solid variants. | Pairs with small dense sans UI and compact data tables. | High quality lesser-used option, but too delicate for 44px touch controls and image review chrome. |
| Heroicons | MIT License on the project page. | Yes. React and Vue libraries. | Project page stated `316` icons. | Outline `24x24` at `1.5px` stroke, plus Solid, Mini, and Micro styles. | Pairs with Tailwind-style Inter layouts. | Not recommended. It is another generated-interface default, even with a clean license. |
| Apple SF Symbols | License terms were not visible in the fetched page. Apple positions it for Apple platforms and San Francisco. | Not acceptable for this web app without separate license confirmation. | Apple page stated over `7000` symbols. | Nine weights, three scales, Apple platform alignment, multiple rendering modes. | Designed for San Francisco on Apple platforms. | Treat as not usable. The app is a private web app, not an Apple-platform native app, and redistribution permissions were not confirmed. |

## The slop problem

Generated UI defaults in 2026 are recognizable because they combine the same decisions: Lucide or Heroicons everywhere, one outline weight, too many unlabeled toolbar glyphs, and no custom marks for the product's own concepts. The result feels generated even when every individual icon is well drawn.

An icon system becomes deliberate when it has all of the following:

- Optical weight matched to the typeface and rendering size, not the package default copied everywhere.
- A chosen grid and stroke rule that survives dark mode, disabled states, and dense rows.
- Restraint. If a screen already has labels, counts, thumbnails, and status chips, fewer icons are better.
- A small set of custom marks for product-specific ideas rather than forcing generic stock metaphors.
- State represented by shape, label, and accessibility text, not color alone.

Phosphor should replace Lucide because it gives the implementation team more weight control while avoiding the exact visual signature the user rejected. This does not make Phosphor magic. If used at one default size everywhere, it can still become slop. The selection only works with the rules below.

## App-specific icon inventory

Use Phosphor icon component names from `@phosphor-icons/react`. `CUSTOM` means draw a product mark instead of forcing a generic metaphor.

### Artifact types

| Concept | Icon | Notes |
|---|---|---|
| Image or render | `Image` | Use for a single raster or render output. |
| Gallery | `ImagesSquare` | Use only for multi-artifact groups. |
| HTML report | `Article` | Better than a browser icon because the unit is reviewable report content. |
| Code artifact | `FileCode` | Use for source, diffs, snippets, and generated code. |
| Text artifact | `FileText` | Use for markdown, logs, and plain text. |

### Review states

| Concept | Icon | Notes |
|---|---|---|
| Open | `Circle` | Pair with `Open` text. Do not rely on hollow circle alone. |
| Resolved | `CheckCircle` | Pair with `Resolved`. |
| Needs check | `WarningCircle` | Pair with `Needs check`. Use amber only as a supplement. |
| Approved | `SealCheck` | For artifact-level approval, not individual resolved threads. |
| Blocked | `Prohibit` | Pair with `Blocked`. |
| Stale | `CUSTOM` | Stock clock icons imply ordinary time, not stale agent context. Use custom mark below. |

### Actions

| Concept | Icon | Notes |
|---|---|---|
| Comment | `ChatCircle` | Primary placement must say `Add comment` or `Comment`. |
| Reply | `ArrowBendUpLeft` | Use with text in thread actions. |
| Resolve | `Check` | Text label required. |
| Reopen | `ArrowCounterClockwise` | Text label required. |
| Next | `ArrowRight` | Icon-only allowed only in stable viewer navigation. |
| Previous | `ArrowLeft` | Icon-only allowed only in stable viewer navigation. |
| Fit to view | `FrameCorners` | Stable viewer toolbar control, icon-only allowed with label and tooltip. |
| Zoom in | `MagnifyingGlassPlus` | Stable viewer toolbar control. |
| Zoom out | `MagnifyingGlassMinus` | Stable viewer toolbar control. |
| Compare | `GitDiff` | Acceptable for side-by-side or before-after. If compare means visual overlay, consider custom later. |
| Filter | `FunnelSimple` | Pair with filter count when active. |
| Sort | `SortAscending` | Use `SortDescending` only when the direction itself is the control. |
| Search | `MagnifyingGlass` | Icon-only acceptable inside a search field if the input has a visible or programmatic label. |
| Download | `DownloadSimple` | Text label required in primary placement. |
| Copy link | `LinkSimple` | Text label required unless inside a compact repeated row menu. |
| Open raw | `FileMagnifyingGlass` | Text label required. Avoid external-link icon because raw may be same-origin. |

### System states

| Concept | Icon | Notes |
|---|---|---|
| Loading | `CircleNotch` | Animate only if reduced motion allows it. Also expose `Loading` text to assistive tech. |
| Empty | `FileText` | Empty states should be copy-led. No special empty glyph needed. |
| Error | `WarningOctagon` | Pair with `Error` or the exact failed operation. |
| Offline | `WifiSlash` | Pair with `Offline` and retry state. |
| Agent authored | `CUSTOM` | Stock robot is too cute or too literal for provenance. Use custom mark below. |
| Human authored | `User` | Use only where authorship matters. Do not decorate every human comment. |

### Annotation objects

| Concept | Icon | Notes |
|---|---|---|
| Point annotation pin | `CUSTOM` | The core product mark. Do not use a generic map pin. |
| Region annotation | `CUSTOM` | Use rectangle corners plus anchor dot, matching the pin stroke. |
| Hidden annotations | `EyeSlash` | Pair with text where state matters. |

## Rules of use

### Sizes and stroke

| Use | Icon size | Container | Weight |
|---|---:|---:|---|
| Inline metadata, chips, dense rows | `16px` | Text line or `24px` chip | Phosphor `regular`, switch to `bold` only if dark-mode contrast looks thin. |
| Standard buttons and toolbar controls | `20px` | `36px` minimum desktop target | `regular`. |
| Touch toolbar controls | `24px` | `44px` minimum target | `regular`. |
| Empty states | `32px` maximum | Copy-led block | `regular`, low contrast, never hero art. |
| Product badges | `12px` to `16px` | Beside author or state text | Custom filled or Phosphor `fill` only when shape must survive color loss. |

Use only these sizes unless a component document records an exception. Stroke or weight changes must be deliberate: raising weight at small sizes is acceptable; mixing weights for decoration is not.

### Labels and accessibility

Icons may appear without visible text only when all of these are true:

- The control is in a persistent, repeated toolbar with stable placement.
- The action is common viewer navigation or viewport control, such as next, previous, zoom, fit, close, or panel toggle.
- The button has an accessible name through `aria-label`.
- The button has a tooltip on hover and keyboard focus.
- The touch target is at least `44px` by `44px` for coarse pointers.

Visible labels are required for primary actions, destructive actions, recovery actions, export actions, resolve, reopen, approve, block, download, copy feedback, and open raw. Decorative icons inside labeled buttons must use `aria-hidden="true"`.

State must remain understandable without color. Pair every status icon with text, use different shapes for error, warning, approved, blocked, and resolved, and expose the same state in accessible text. Selected state uses border, focus ring, `aria-selected`, and panel position, not a special icon.

### Density limit

A single screen should not show more than **nine distinct icon meanings** at once outside the artifact itself. Repeated instances of the same meaning count once. If a toolbar, thread list, and gallery together need more than nine, remove icons from secondary row actions and keep labels. More than nine turns the UI into a hieroglyphics puzzle.

## Implementation for React and TypeScript

Use per-icon React components, not a remote icon font. This gives tree shaking, no external requests, and predictable accessible markup. An SVG sprite is useful for static HTML or server-rendered documents, but it adds an indirection layer the React app does not need.

Recommended structure:

```text
src/design-system/icons/Icon.tsx
src/design-system/icons/phosphor.ts
src/design-system/icons/custom/AnnotationPin.tsx
src/design-system/icons/custom/AgentAuthoredMark.tsx
src/design-system/icons/custom/StaleThreadMark.tsx
src/design-system/icons/README.md
```

`phosphor.ts` should import and re-export only the approved inventory. Product code should not import directly from `@phosphor-icons/react`; it should import from the local icon module so weight, size, title behavior, and `aria-hidden` rules stay centralized. The wrapper should accept a semantic size token such as `inline`, `control`, or `touch`, not arbitrary pixels.

Keep custom marks as local React SVG components using `currentColor`. They should inherit the same size tokens as Phosphor, align to the same visible box, and receive accessible names only when the mark carries meaning by itself. Do not bundle the whole icon library. Do not use Google Fonts, CDN CSS, or runtime icon downloads.

## Custom marks worth drawing

### Annotation pin

Draw a `24px` visible mark with an invisible `44px` hit target. Shape: a small filled circle or dot at the exact image coordinate, connected to a short teardrop or bracket stem that does not hide the underlying pixel. It should be more like a review pin than a map pin. Use a strong outline or halo in dark mode so it remains visible on bright renders.

### Agent authored badge

Draw a compact provenance mark, not a robot face. Shape: a small hexagonal spark or node badge with one internal dot, `12px` to `16px`, filled or semi-filled. It should say machine-authored without making the UI playful. Pair with text `Agent` where space allows.

### Stale thread mark

Draw a small clock-like ring with a broken segment and one offset dot. Avoid `Clock` alone because stale means the underlying artifact or agent output changed since the thread was written, not merely old. Pair with text `Stale` in lists and filters.

### Region annotation mark

Draw four rectangle corners with one anchor dot, using the same stroke cap and optical weight as the annotation pin. It appears in toolbars and legends only; actual regions on the canvas are drawn as overlays, not icons.

## Sources checked

- Lucide project page: <https://lucide.dev/>
- Lucide license: <https://github.com/lucide-icons/lucide/blob/main/LICENSE>
- Phosphor core repository and license: <https://github.com/phosphor-icons/core>
- Phosphor license: <https://github.com/phosphor-icons/core/blob/main/LICENSE>
- Phosphor React npm package: <https://www.npmjs.com/package/@phosphor-icons/react>
- Tabler Icons project page: <https://tabler.io/icons>
- Remix Icon project page and license: <https://remixicon.com/> and <https://github.com/Remix-Design/RemixIcon/blob/master/License>
- Iconoir project page: <https://iconoir.com/>
- Material Symbols page: <https://fonts.google.com/icons>
- Material Design Icons repository: <https://github.com/google/material-design-icons>
- IBM Carbon icons library and license: <https://carbondesignsystem.com/elements/icons/library/> and <https://github.com/carbon-design-system/carbon/blob/main/LICENSE>
- Microsoft Fluent UI System Icons repository and license: <https://github.com/microsoft/fluentui-system-icons> and <https://github.com/microsoft/fluentui-system-icons/blob/main/LICENSE>
- Bootstrap Icons project page and license: <https://icons.getbootstrap.com/> and <https://github.com/twbs/icons/blob/main/LICENSE>
- Radix Icons project page and license: <https://www.radix-ui.com/icons> and <https://github.com/radix-ui/icons/blob/main/LICENSE>
- Feather project page and license: <https://feathericons.com/> and <https://github.com/feathericons/feather/blob/main/LICENSE>
- Primer Octicons repository and license: <https://github.com/primer/octicons> and <https://github.com/primer/octicons/blob/main/LICENSE>
- Teenyicons repository: <https://github.com/teenyicons/teenyicons>
- Heroicons project page: <https://heroicons.com/>
- Apple SF Symbols page: <https://developer.apple.com/sf-symbols/>
