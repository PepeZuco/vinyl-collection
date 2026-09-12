---
name: vinyl-note
description: Use when the user gives raw text about a record in their vinyl collection - a story about the day they found it, a memory, a link, or a few observations about how it sounds - to be turned into a note they paste into the app.
---

# Vinyl Note

## Overview

The user writes the note. This skill only adds the markdown their words already imply, then hands it back raw to be copied and pasted.

**Core principle: a note is the user's text with markdown applied to it, never a document built around it.** Every heading, field, or section added is text the user did not write.

## Output contract

Reply with exactly one fenced code block, containing only the note. No preamble, no "here's your note", no explanation of choices. Nothing after the block unless something in the input was genuinely ambiguous - then one short line, after the block.

## What a note is

One of two shapes, chosen by the input:

**A story** (they found it, someone gave it, something happened) - prose paragraphs, no heading, no title, no first line that names the moment. It opens on the first thing the user said.

**Observations** (how it sounds, when to play it) - a `-` bullet list, one observation per bullet, no intro line.

Nothing else is a shape. A note has no heading, no `**Onde:**`/`**Quando:**` field block, no section per topic, no horizontal rule, no table, no closing sentence, no date as a title - the app stores the date in its own field, beside the text.

## Paragraph breaks

The app renders with `marked` and GFM line breaks off, so **a single newline renders as a space**. Separate thoughts with a blank line or they run together on screen. A line break the user typed is a thought boundary: promote it to a blank line, never merge that line into the sentence before it. Inside a bullet list, one line per bullet is correct.

## The three marks

| Mark | Rule |
|---|---|
| **Bold** | At most one per paragraph, on the place, person, or record the memory hangs on. Never on a price, a number, or a feeling. Usually zero. |
| Links | Wrap words already in the sentence. Never add words to hang a link on, never append a bare URL. |
| Italics | Never. |

## Their words

Fix spelling, accents, and punctuation. `musicas` becomes `músicas`, a missing final period is added.

Change nothing else. Not word order, not register, not a word for a better word: `o cara queria 80` stays `o cara queria 80`, never `o vendedor pediu R$80`. Add no fact the text does not contain - no currency symbol, no inferred detail, no summary at the end. Reply in the language the user wrote in. Keep any unusual character they used verbatim.

## More than one occasion

The app stores one note per date. If the text covers separate occasions, emit one code block per occasion, each preceded by its date on its own line, in the order they happened.

## Common mistakes

Input: `achei esse disco na feira da benedito calixto sabado, o cara queria 80 mas deixou por 45 ... achei no youtube https://youtu.be/abc123 ... fui com a jenni`

| Wrong | Why |
|---|---|
| `## Notas` | A note is not a document. It has no title. |
| `**Onde:** Feira ... **Quando:** Sábado` | Their story got filed into fields nobody asked for. |
| `### Lado B` | Four sentences do not need sections. |
| `fechei por **R$45**` | Reworded, invented `R$`, bolded a price. |
| `*muito melhor*` | Italics. |
| `[ouvi no YouTube](url)` | "ouvi no" is not in their text. Wrap `achei no youtube`. |

Right:

```
Achei esse disco na **Feira da Benedito Calixto** sábado, o cara queria 80 mas deixou por 45. Fui com a Jenni.

O lado B tem uma versão ao vivo que eu não conhecia, [achei no YouTube](https://youtu.be/abc123) e é muito melhor que a de estúdio.
```
