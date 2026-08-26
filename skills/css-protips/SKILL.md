---
name: css-protips
description: >
  A collection of CSS protips to help take your CSS skills pro. Use when
  writing, refactoring, or reviewing CSS: layout, the box model, flexbox,
  grid, selectors, specificity, responsive design, accessibility, and CSS-only
  tricks that replace JavaScript. Covers CSS resets, box-sizing inheritance,
  :not(), :is(), aspect-ratio, the lobotomized owl selector, comma-separated
  lists, SVG icons, vertical centering, and more. Also use when the user says
  "css protips", "css tips", "make this CSS cleaner", or asks to modernize or
  simplify a stylesheet.
license: CC0 1.0
---

# CSS Protips

A collection of tips to help take your CSS skills pro. Originally published as
[AllThingsSmitty/css-protips](https://github.com/AllThingsSmitty/css-protips)
(CC0 1.0).

## How to use

1. Read `reference/protips.md` — the full tip list with code examples.
2. Apply only the tips that fit the current code. Each tip is self-contained;
   read the entry, then use its technique in your CSS.
3. Prefer these platform-native CSS techniques over JavaScript, custom
   utility code, or libraries when they cover the need.

## Rules of thumb

- Reset or inherit `box-sizing` — don't repeat width/height math by hand.
- Modern selectors (`:not()`, `:is()`, `nth-child` variants) before extra
  classes or JS.
- Native CSS features (`aspect-ratio`, `flexbox`, `grid`, `clamp()`,
  `gap`, logical properties) before hacks.
- Keep specificity low: target with classes, not ID/!important chains.
