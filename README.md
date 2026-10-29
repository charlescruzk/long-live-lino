# Long Live Lino

An endless, slowly drifting sky of photos for Paulino "Lino" De Mateo Gomez
(June 24, 1985 – October 9, 2026).

Anyone who opens the page can touch the sky to leave a light for him, with a message,
signed or anonymous. Every light stays in the sky for everyone, and hovering (or tapping) a
star reads what was left there.

**Live:** https://charlescruzk.github.io/long-live-lino/

## Keys

| | |
|---|---|
| `F` | fullscreen |
| `Space` | pause |
| `←` `→` | previous / next photo |

Opening the page with `#12` starts at the 12th slide.

## The shared sky (Supabase)

The lights are kept in a free Supabase project.

1. In the Supabase dashboard open **SQL Editor → New query**, paste [`supabase/setup.sql`](supabase/setup.sql), and run it.
2. In **Project Settings → API Keys**, copy the project URL and the public key
   (the `anon` key or the `sb_publishable_…` key; never the secret / `service_role` key).
3. Put both in [`docs/lights-config.js`](docs/lights-config.js) and push.

The public key is meant to sit in a web page: row-level security only lets visitors read
visible lights and add new ones. They can't edit or delete anything, and a trigger caps
new lights at 40 a minute.

Without a config the page still works, but lights are only kept on the device that left them.

**Taking a light down:** Table Editor → `lights` → set `hidden` to `true` (or delete the row).

## Rebuilding the photos

The originals, renders and tools live only on Charles's machine (they're too heavy for git, and the
originals carry GPS metadata). After adding photos or editing `timeline.txt` / `quotes.txt`:

```sh
build/update.sh                 # new photos into timeline.txt
.venv/bin/python build/web.py   # re-export docs/photos and docs/data.js
```

`quotes.txt` holds a line per photo with a confidence score. Only lines at or above `quote_min` in
`build/config.json` appear.
