## Output discipline (binding, all agents)

- Any narration you emit: caveman-ultra terse (clipped grammar, no filler, technical terms/paths/commands exact). Under 4 lines. Lead with outcome. No preamble.
- The DELIVERABLE is an HTML file: write it as NORMAL, clean, human-readable HTML/CSS, comments in normal English. No em-dashes anywhere.
- Keep the file compact (under ~800 lines).

## What this is

Self-hosted artifact review app. A reviewer opens an artifact (image, gallery, HTML report, or code/text) and drops threaded, resolvable comments anchored to a region/item/block/line, working a queue. This mockup is ONE of four approved information architectures (IAs). It is a static single-file HTML mockup for a human taste gate, not production code.

The LIGHT paper-document aesthetic is approved (see the reference file `spikes/frontend-directions/direction-content-first.html`, which already has it). Your two jobs: (1) put THIS direction's file into that SAME light paper-document aesthetic using the shared token system below, and (2) add a working light/dark theme toggle whose DARK theme is a warm-workbench feel, NOT the old cockpit look.

## Preserve the IA EXACTLY

Read your target file fully first. Preserve its information architecture, every panel, state, and behavior it shows, and its keyboard hints. This is a VISUAL re-skin plus a theme toggle, never an IA change. Keep all accessibility: `aria-label`s, `.sr-only`, visible focus outlines, and status that survives grayscale (icon + shape + text, never color alone). Keep the four artifact types represented (image region pins, gallery item state, HTML report block anchors, code/text line anchors) if the file shows them.

## SHARED theme token system (paste these EXACTLY, identical across all four directions)

Put this in a single `:root` (light default) plus a `[data-theme="dark"]` override on the root element. Map this direction's existing structural CSS onto these token NAMES (paper-* = surfaces, ink-* = text, accent/open/resolved/draft/focus = semantic marks, *-soft = filled tint backgrounds). Do NOT invent new palette variables; reuse these. This shared token set is intended now: divergence between the four directions comes from their STRUCTURE, not their palette.

```css
:root{
  --paper-0:oklch(98% .012 78); --paper-1:oklch(95% .014 78); --paper-2:oklch(91% .018 78); --paper-3:oklch(86% .020 78); --paper-4:oklch(76% .024 78);
  --ink-0:oklch(17% .028 64); --ink-1:oklch(27% .026 64); --ink-2:oklch(39% .024 64); --ink-3:oklch(52% .021 64);
  --accent:oklch(43% .078 34); --accent-soft:oklch(93% .035 34); --accent-rule:oklch(56% .065 34);
  --open:oklch(39% .090 38); --open-soft:oklch(94% .032 38);
  --resolved:oklch(36% .060 145); --resolved-soft:oklch(94% .030 145);
  --draft:oklch(42% .052 88); --draft-soft:oklch(95% .028 88);
  --focus:oklch(45% .090 42);
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px; --r1:2px; --r2:4px; --r3:7px;
  --section-height:900px; --viewer-height:calc(var(--section-height) - 132px);
  --sans:"Plex Local"; --mono:"JetBrains Local"; --serif:"Source Serif Local";
}
[data-theme="dark"]{
  --paper-0:oklch(25% .015 70); --paper-1:oklch(21% .014 70); --paper-2:oklch(18% .013 70); --paper-3:oklch(33% .016 70); --paper-4:oklch(43% .018 70);
  --ink-0:oklch(92% .014 76); --ink-1:oklch(82% .016 76); --ink-2:oklch(68% .017 76); --ink-3:oklch(56% .017 76);
  --accent:oklch(70% .11 34); --accent-soft:oklch(32% .055 34); --accent-rule:oklch(62% .10 34);
  --open:oklch(72% .12 38); --open-soft:oklch(31% .06 38);
  --resolved:oklch(70% .095 145); --resolved-soft:oklch(31% .05 145);
  --draft:oklch(74% .09 88); --draft-soft:oklch(31% .05 88);
  --focus:oklch(74% .12 42);
}
```

Dark theme intent: WARM WORKBENCH. Warm dark surfaces (paper/ink/wood), low chroma, material and calm. Same restrained red-pencil accent, brightened to read on dark. It must NOT read as a cockpit: no neon, no glow, no black-and-blue, no LED/meter/telemetry look. It is the light document, dimmed and warmed, not a different app.

## Theme toggle (add this)

Add ONE theme toggle control placed tastefully in THIS direction's existing top chrome (a top bar / header / toolbar), right-aligned, never overlapping content. Sun icon in light, moon icon in dark, plus a `T` key hint. Inline the two Phosphor symbols below into the file's shared `<svg>` symbol block (do NOT invent path data), and wire the toggle with this vanilla script near `</body>`:

```html
<symbol id="i-sun" viewBox="0 0 256 256"><path d="M120,40V16a8,8,0,0,1,16,0V40a8,8,0,0,1-16,0Zm72,88a64,64,0,1,1-64-64A64.07,64.07,0,0,1,192,128Zm-16,0a48,48,0,1,0-48,48A48.05,48.05,0,0,0,176,128ZM58.34,69.66A8,8,0,0,0,69.66,58.34l-16-16A8,8,0,0,0,42.34,53.66Zm0,116.68-16,16a8,8,0,0,0,11.32,11.32l16-16a8,8,0,0,0-11.32-11.32ZM192,72a8,8,0,0,0,5.66-2.34l16-16a8,8,0,0,0-11.32-11.32l-16,16A8,8,0,0,0,192,72Zm5.66,114.34a8,8,0,0,0-11.32,11.32l16,16a8,8,0,0,0,11.32-11.32ZM48,128a8,8,0,0,0-8-8H16a8,8,0,0,0,0,16H40A8,8,0,0,0,48,128Zm80,80a8,8,0,0,0-8,8v24a8,8,0,0,0,16,0V216A8,8,0,0,0,128,208Zm112-88H216a8,8,0,0,0,0,16h24a8,8,0,0,0,0-16Z"/></symbol>
<symbol id="i-moon" viewBox="0 0 256 256"><path d="M233.54,142.23a8,8,0,0,0-8-2,88.08,88.08,0,0,1-109.8-109.8,8,8,0,0,0-10-10,104.84,104.84,0,0,0-52.91,37A104,104,0,0,0,136,224a103.09,103.09,0,0,0,62.52-20.88,104.84,104.84,0,0,0,37-52.91A8,8,0,0,0,233.54,142.23ZM188.9,190.34A88,88,0,0,1,65.66,67.11a89,89,0,0,1,31.4-26A106,106,0,0,0,96,56,104.11,104.11,0,0,0,200,160a106,106,0,0,0,14.92-1.06A89,89,0,0,1,188.9,190.34Z"/></symbol>
```

```html
<button class="theme-toggle" aria-label="Toggle light and dark theme" title="Toggle theme"><svg class="ico"><use href="#i-sun"></use></svg><kbd>T</kbd></button>
<script>
(function(){
  var root=document.documentElement;
  function apply(t){root.setAttribute('data-theme',t);document.querySelectorAll('.theme-toggle use').forEach(function(u){u.setAttribute('href',t==='dark'?'#i-moon':'#i-sun');});}
  function toggle(){apply(root.getAttribute('data-theme')==='dark'?'light':'dark');}
  document.querySelectorAll('.theme-toggle').forEach(function(b){b.addEventListener('click',toggle);});
  document.addEventListener('keydown',function(e){if((e.key==='t'||e.key==='T')&&!/input|textarea/i.test(e.target.tagName)){toggle();}});
  apply('light');
})();
</script>
```

Style `.theme-toggle` to match the other chrome buttons in this direction (same button conventions, small, right-aligned in the top chrome).

## Hard ban list + anti-slop gate

Read `docs/design/avoiding-ai-generated-ui-tells.md` and run its pass/fail checklist against BOTH themes. Bans: no Tailwind slate ramp, no `#60A5FA` or any generic AI blue accent, no single uniform large radius, no gradient glow, no glassmorphism, no decorative shadows, no emoji icons, no cockpit vocabulary (no meters, scopes, telemetry strips, LED dots, dense readout headers, monospace-everywhere). Any metadata header must read as a quiet caption line, not a dashboard readout. Verify WCAG in BOTH themes: reading/body text and UI text at least 4.5:1 against their surface.

## Layout fix (do this, it matters for the screenshot)

If the file uses `min-height:100vh` or `height:calc(100vh - ...)`, replace the `100vh` usage with the fixed `--section-height:900px` (and `--viewer-height`) tokens above, so the taste-gate screenshot at a tall window does not balloon each section into dead space. Keep `body{min-width:1440px}` and the 1440px content width.

## Icon + asset rules

- REUSE the Phosphor `<symbol>` SVGs already inlined in the file (plus the sun/moon above). Do NOT invent new SVG path data. If you need another icon not already present, reuse an existing symbol instead of fabricating paths.
- Keep relative asset paths unchanged: `assets/fonts/*.woff2` and `assets/sample-artifact.png`. Those files are untracked and absent from this worktree but exist at render time. Do not change the paths, do not fetch or create the assets, keep the same three self-hosted font families.

## When done

- Commit ONLY your one target HTML file, with a clear message. Do NOT merge, do NOT remove the worktree, do NOT stage or commit anything else. Stop after the commit.
- Return a 3-line summary: confirm the light theme matches the shared tokens, the warm-workbench dark theme + toggle work, and the anti-slop checklist passed in both themes.
