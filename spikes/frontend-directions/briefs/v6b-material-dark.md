# Round 6b: swap the dark theme to proper Material dark colors (unified-app)

Scoped worker in an isolated git worktree. Do exactly this one mechanical edit, commit, stop. Do NOT merge, do NOT remove the worktree, do NOT touch any other file.

## Output discipline

Narration: caveman-ultra terse, under 4 lines, outcome first. No em-dashes. This is a CSS token swap only, no other change.

## The problem

In `spikes/frontend-directions/direction-unified-app.html`, the current `[data-theme="dark"]` block is a muddy warm-brown palette (hue 70, near-zero chroma) that reads as a dimmed light theme, not a real dark mode. Replace it with a proper Material-Design dark palette: neutral dark-grey surfaces with elevation (higher surfaces are LIGHTER), high-emphasis on-surface text, and accent/semantic tones lightened + desaturated for dark per Material guidance.

## Exact edit (find-and-replace ONE block, change nothing else)

Find this exact block (lines ~29-37):

```css
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

Replace it with exactly this:

```css
[data-theme="dark"]{
  --paper-0:oklch(27% .006 60); --paper-1:oklch(23% .005 60); --paper-2:oklch(19% .004 60); --paper-3:oklch(36% .008 60); --paper-4:oklch(46% .010 60);
  --ink-0:oklch(94% .004 60); --ink-1:oklch(84% .005 60); --ink-2:oklch(70% .006 60); --ink-3:oklch(58% .007 60);
  --accent:oklch(72% .13 32); --accent-soft:oklch(34% .07 32); --accent-rule:oklch(66% .13 32);
  --open:oklch(75% .13 36); --open-soft:oklch(33% .07 36);
  --resolved:oklch(80% .13 152); --resolved-soft:oklch(33% .06 152);
  --draft:oklch(82% .11 92); --draft-soft:oklch(34% .06 92);
  --focus:oklch(80% .13 50);
}
```

Do NOT change the `:root` light block, the HTML, the script, or anything else. Only this one block changes.

## When done

Commit ONLY `spikes/frontend-directions/direction-unified-app.html` with a clear message. Do NOT merge, do NOT remove the worktree, do NOT stage anything else. Stop after commit. Return one line confirming the block was replaced.
