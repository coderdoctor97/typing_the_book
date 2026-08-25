# Typing the Book

A browser-only typing practice app. Import TXT, Markdown, or DOCX, select a passage, and practice it. Mistyped target words are stored locally for later review.

## Run

```sh
npm install
npm run generate-audio
npm run dev
```

Production verification: `npm test` and `npm run build`.

## Supported files and privacy

TXT preserves paragraphs and line breaks. Markdown supports headings, lists, emphasis, links, code, and tables via `marked`, sanitized with DOMPurify. DOCX is converted to readable HTML with Mammoth; this is not pixel-perfect Word layout. `.dox` is treated as `.docx`. Legacy binary `.doc` is intentionally rejected with conversion guidance. Files are read in the browser and are never uploaded. Only mistake history and sound preferences are stored in versioned localStorage; the full document is not persisted.

## Practice behavior

Start begins timing on the first evaluated keystroke. WPM is correctly typed target characters divided by five and elapsed minutes, with a one-second minimum for display. Accuracy is correct keystrokes divided by evaluated keystrokes. Progress is handled target characters divided by total characters. Backspace clears the character state but does not erase a recorded learning signal. Paste is blocked.

The Mistake Library supports weighted bounded practice, removal, and clearing. The bundled `click.wav` is an original generated asset; see `public/assets/audio/README.md`.
