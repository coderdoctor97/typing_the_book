# ponytail-review: typing_the_book

Skill: `skills/ponytail-review` (repo-wide, audit mode). Scope: over-engineering only.
Ranked biggest cut first. Lists findings, applies nothing.

## Findings

- `src/session.js:1-7: delete: 9 never-called exports — canStart, canPause, canResume, canRestart, canEnd, isComplete, end, reset, handlePasteAttempt. main.js and test/tests.js check `session.state === SessionState.X` directly; nothing imports these. Nothing replaces them.`
- `src/session.js:2-6: delete: session state written, never read — `paragraphs` (filled only by splitParagraphs), `sessionMistakes` (only `.add()`, never queried), `lastEvent` (7 writes, 0 reads), and handleKey's `recordError` option (no caller overrides it). Keep `charStates`, `mistakeCount`, and the timing fields.`
- `src/parsers/parseTxt.js, parseMd.js, parseDocx.js: delete: parser metadata — wordCount/charCount/paragraphCount/messages. Nothing consumes them; the preview in main.js recomputes the count from `doc.text` inline. parse* returns `{html, text}`; the app already counts. Adjust the one smoke-test assertion (`p.wordCount===2`) to assert on `p.text` instead.`
- `src/errors.js, src/storage.js: delete: export/import dead surface — exportData/importData/exportHistory/importHistory. There is no export/import UI and no caller anywhere. getErrorWords is a second alias of getLibrary, also uncalled.`
- `src/storage.js:5, src/errors.js:2: delete: `context` field on mistake records — written on every record, never read or rendered.`
- `src/parsers/index.js:2: delete: parserFor — a third copy of the extension→parser mapping; main.js hand-rolls the same ternary, nothing else calls it.`
- `src/main.js, src/parsers/parseTxt.js, parseMd.js, parseDocx.js, src/selection.js: shrink: the Unicode word regex `[\p{L}\p{N}']+(?:-[\p{L}\p{N}']+)*/gu` is re-implemented 5× across five files. Define it once in one module and import (or, once the parser metadata above is cut, only main.js + selection.js still need it — one shared export).`
- `src/audio.js:4: delete: isReady — never called; playClick already guards on `buffer && prefs.enabled`.`
- `src/stats.js:5: yagni: sessionSummary's `elapsed` fallback (`ms ?? elapsed ?? 0`) — every caller passes `elapsedMs`; and `progress: computeProgress(totalChars, totalChars)` is a constant (100 or 0) the results view never shows. Drop both.`
- `src/parsers/parseMd.js:3: yagni: `typeof document !== 'undefined'` branch — nothing runs parseMd outside the browser; speculative env shim.`
- `package.json: delete: `generate-fixtures` script — points at generate-fixtures.js, which does not exist. devDependencies jsdom and jszip are never imported (mammoth ships its own zip support); both are dead weight.`

## Out of scope (correctness — routed to a normal review pass, not scored)

- `src/main.js: library() renders a "Clear history" button (`data-a="clear"`) but action() has no `clear` branch — the button does nothing and clearAll is unreachable. That's a bug, not complexity: wire the one-line branch or cut the button.`

## Net

`net: -55 lines, -2 deps possible.`

Leanest parts, no action: vanilla SPA (no framework), `esc()`/DOMPurify/`valid()` trust-boundary handling, the one-file smoke test, `generate-click.js`. Already in ponytail shape.
