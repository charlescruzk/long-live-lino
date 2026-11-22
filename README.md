# Long Live Lino

A slideshow for Paulino "Lino" De Mateo Gomez (June 24, 1985 – October 9, 2026). It plays on its
own and loops forever, made to run on a screen in the background during the ceremony.

It opens on a title card, then goes through his life in order (childhood, the 2000s, the 2010s,
2020 to 2023, recent years) and ends on "Long Live Lino" before starting again. One loop takes about
45 minutes. Photos drift slowly and dissolve into each other. Portrait photos are shown whole over
a soft blur of themselves. Short video clips play muted, and some photos carry a line of text.

**Live:** https://charlescruzk.github.io/long-live-lino/

## Playing it at the ceremony

1. Open the live link above, or double-click `docs/index.html` (it works offline from the folder).
2. Press **F** for full screen. The cursor hides itself after a few seconds.
3. Keep the computer awake: run `caffeinate -d` in Terminal (Ctrl-C stops it), or turn off sleep
   in System Settings. The page also asks the browser to keep the screen on.

| Key | |
|---|---|
| `F` or double-click | full screen |
| `Space` | pause / resume |
| `←` `→` | previous / next |

Opening the page with `#12` starts at the 12th photo.

## Adding or changing photos

The originals, tools and renders live only on Charles's machine. They're too heavy for git, and the
originals carry GPS metadata. Everything in `docs/` is re-encoded without it.

```sh
.venv/bin/python build/prepare.py       # new files in photos/ -> cache + face detection (duplicates skipped)
.venv/bin/python build/date_hints.py    # camera / file-name dates for photos not placed yet
# move the new lines out of the "NEW" chapter in timeline.txt
.venv/bin/python build/slideshow.py     # rebuild docs/media and docs/slides.js
```

- `timeline.txt` holds the order, chapters, which face is Lino (`focus=`), crops (`crop=`) and
  clip ranges (`clip=`). A `-` in front leaves a photo out. Notes starting with `?` are guesses.
- The title, name and dates on the cards come from `build/config.json`.

The music videos (`build/render.py`, `build/update.sh`) still work from the same timeline.
The earlier interactive "sky" is archived in [`archive/sky/`](archive/sky/).
