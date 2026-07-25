# Vendored frontend assets

Prebuilt dist files only, fetched via curl from jsdelivr. No npm, no bundler,
no build step. Re-run the curl commands below to refresh a version.

## OpenSeadragon 4.1.1

Deep-zoom viewer. Used in simple-image (single full-res source) mode, no DZI
tiling build (see spikes/review-app/DESIGN.md section 4.4).

- `openseadragon/openseadragon.min.js`
- `openseadragon/images/*.png` (nav button sprites OSD needs at runtime:
  zoom in/out, home, fullpage, next/previous, plus generic button states)

Source:
```
https://cdn.jsdelivr.net/npm/openseadragon@4.1.1/build/openseadragon/openseadragon.min.js
https://cdn.jsdelivr.net/npm/openseadragon@4.1.1/build/openseadragon/images/<name>.png
```

## Annotorious (Recogito) OpenSeadragon build 2.7.19

Pin-to-region annotation overlay. Package
`@recogito/annotorious-openseadragon` ships one bundled JS file that
contains both the Annotorious core AND the OpenSeadragon plugin (there is
no separate core-only build in this package line), plus one CSS file.
Confirmed API surface in the minified bundle matches the design contract:
`OpenSeadragon.Annotorious(viewer, opts)`, `anno.setAnnotations(...)`,
W3C `FragmentSelector` / `SvgSelector` selector shapes.

- `annotorious/annotorious-openseadragon.min.js` (core + OSD plugin, one file)
- `annotorious/annotorious.min.css`

Source:
```
https://cdn.jsdelivr.net/npm/@recogito/annotorious-openseadragon@2.7.19/dist/openseadragon-annotorious.min.js
https://cdn.jsdelivr.net/npm/@recogito/annotorious-openseadragon@2.7.19/dist/annotorious.min.css
```

Note: DESIGN.md section 5's file tree names this
`annotorious-openseadragon.min.js` plus a separate `annotorious.min.js`
core file; the actual package ships one merged file for the OSD build, so
only two files (js + css) are vendored, not three. review-serve.py's
`ANNOTORIOUS_SCRIPT_URL` points at the merged file; there is no
`ANNOTORIOUS_CORE_URL` constant because no separate core file exists to
vendor.

## Verification performed

Each file downloaded and checked non-empty with the expected magic /
content type before use:
- `openseadragon.min.js`: starts with `//! openseadragon 4.1.1` comment
  header, 244 KB.
- `images/*.png`: all start with the PNG magic byte signature
  `89 50 4e 47`.
- `annotorious-openseadragon.min.js`: minified JS, 376 KB, contains
  `OpenSeadragon.Annotorious`, `setAnnotations`, `FragmentSelector` in its
  source (grepped to confirm the shipped build matches the API contract).
- `annotorious.min.css`: 12 KB, starts with real CSS rules
  (`.r6o-editor{...}`).
