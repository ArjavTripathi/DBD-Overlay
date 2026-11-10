# dbd-overlay

Dead by Daylight helper for Linux (Hyprland) and later Windows: automatic map
overlay and a per-killer / survivor winstreak HUD.

**Anti-cheat safety:** this tool only takes screenshots of the game window and
draws its own separate windows. It never reads or writes game memory, injects
anything, or touches game files.

> Status: milestone 7. Map overlay, match/role/killer detection, per-survivor
> results and the winstreak HUD work; win rules are set in a settings window.

## Install / run

System packages (Arch/CachyOS):

```sh
sudo pacman -S tesseract tesseract-data-eng grim pyside6 layer-shell-qt
```

PySide6 comes from the distro on Linux, not from pip: the overlay uses the
`layer-shell-qt` plugin, which must be built against the same Qt as PySide6.
So the venv needs access to system packages (one-time):

```sh
uv venv --system-site-packages
uv sync
uv run dbd-overlay            # run the app (tray icon + control socket)
uv run dbd-overlay run --debug
uv run dbd-overlay ctl --list # commands you can send to the running app
```

Files:

| What   | Where                                    |
|--------|------------------------------------------|
| config | `~/.config/dbd-overlay/config.toml` (created with defaults on first run) |
| data   | `~/.local/share/dbd-overlay/matches.db`  |
| log    | `~/.local/share/dbd-overlay/dbd-overlay.log` |
| socket | `$XDG_RUNTIME_DIR/dbd-overlay.sock`      |
| map images | `~/.local/share/dbd-overlay/assets/maps/<realm>/<map>.png` (or set `overlay.assets_dir`) |

## Map images

You supply them (the art belongs to Behaviour Interactive; nothing is bundled
or downloaded). Layout: `assets/maps/<realm>/<map>.<png|webp|jpg>`, e.g.
`assets/maps/Backwater Swamp/The Pale Rose.webp`. Names are matched loosely
(case, apostrophes, accents, a leading "The", small typos), so
`Temple of Purgation.webp` works for "The Temple of Purgation".

Point the app at an existing folder with

```toml
[overlay]
assets_dir = "~/Programming/DBD/OverlayApp/assets"
```

## The overlay window

On Wayland the overlay is a **layer-shell surface** on the `overlay` layer
(the protocol bars and notification daemons use), not a normal window. That
means: drawn above the fullscreen game, never takes keyboard focus,
click-through, positioned exactly, and **no window rules needed**. Layer
surfaces appear on every workspace, so the app hides the overlay whenever the
game's workspace isn't the one on screen.

Why not a normal or XWayland window: tested on Hyprland 0.57, both get managed
by the compositor (your float/center rules apply, the requested position is
ignored), even XWayland override-redirect windows.

- `dbd-overlay ctl toggle-overlay`: show/hide
- `dbd-overlay ctl edit-hud`: edit mode: drag to move, bottom-right grip to
  resize; Esc or `edit-hud` again locks it and saves position/size to the config
- `[overlay] opacity` (0.05-1) and `auto_show` in the config
- `dbd-overlay ctl set-map pale rose`: set the map by name (handy with rofi/wofi)

## Hotkeys on Hyprland

Wayland doesn't let apps grab global hotkeys, so Hyprland binds run the CLI,
which forwards the command over the socket. Use the absolute path to the
installed `dbd-overlay` if it isn't on your `PATH` (e.g. after `uv tool install .`).

Lua config (`hyprland.lua`, Hyprland 0.53+):

```lua
local dbd = "dbd-overlay ctl "
hl.bind(mainMod .. " + M",         hl.dsp.exec_cmd(dbd .. "toggle-overlay"))
hl.bind(mainMod .. " + SHIFT + M", hl.dsp.exec_cmd(dbd .. "pick-map"))
hl.bind(mainMod .. " + W",         hl.dsp.exec_cmd(dbd .. "streak-win"))
hl.bind(mainMod .. " + L",         hl.dsp.exec_cmd(dbd .. "streak-loss"))
hl.bind(mainMod .. " + I",         hl.dsp.exec_cmd(dbd .. "streak-ignore"))
hl.bind(mainMod .. " + Z",         hl.dsp.exec_cmd(dbd .. "streak-undo"))
hl.bind(mainMod .. " + H",         hl.dsp.exec_cmd(dbd .. "toggle-hud"))
hl.bind(mainMod .. " + T",         hl.dsp.exec_cmd(dbd .. "streak-toggle"))
hl.bind(mainMod .. " + O",         hl.dsp.exec_cmd(dbd .. "edit-hud"))
```

Classic `hyprland.conf`:

```ini
bind = SUPER, M, exec, dbd-overlay ctl toggle-overlay
bind = SUPER SHIFT, M, exec, dbd-overlay ctl pick-map
```

The map picker (a normal window, class `dbd-overlay`) should float:

```lua
hl.window_rule({ match = { class = "^(dbd-overlay)$" }, float = true, pin = true })
```

The tray icon (a red "D") needs a StatusNotifier host: waybar's `tray` module,
Noctalia's tray, etc. Left-click opens settings, right-click shows the menu.

## Map detection

At match start the game shows a title card bottom-left: map name (bright),
a thin teal line, realm name (dim) below. The app finds the line (cheap, no
OCR), OCRs both lines with Tesseract, and fuzzy-matches them against
`src/dbd_overlay/data/maps.json`:

- map matched (confirmed by the realm) -> overlay shows;
- realm matched, map unclear -> picker with only that realm's maps;
- teal line but nothing readable -> full picker, frame saved to
  `~/.local/share/dbd-overlay/debug/` so detection can be improved.

Only the bottom-left strip of the window is captured (~1% of one CPU core at 1 fps).
Detection pauses while the game's workspace isn't visible.

## Match end, role and killer

The end-of-match screens (result banner, bloodpoints, scoreboard) all show a
big red title top-left; the app watches a small box there (red-pixel count
first, OCR only when it's red). The first one ends the match (the overlay
hides). On the scoreboard it reads:

- each row's `CHARACTER  player name` line: the row whose character is a
  killer (`data/killers.json`) gives **the killer**;
- **your player name**, top-right under the currencies;
- **your role**: killer if your name is on the killer row, else survivor.

Nothing about your account is configured: it works for anyone. If something
can't be read, a picker asks (killer), and the frame is saved to `debug/`.
If the lobby's PLAY/READY/CANCEL button shows up mid-match (disconnect,
crash), the match is ended too.

**In the lobby** (checked every 4 s) the role is known before the match, so the
HUD switches to the right streak as soon as you queue:

- killer lobbies print your killer under the READY/CANCEL button
  (`THE HILLBILLY  1:04`), and lobby sub-pages show it top-left
  (`THE SLASHER / CHARACTERS`): killer + which one;
- queued or ready with nothing under the button: survivor (needs two checks
  in a row, since it's inferred from something missing);
- plain PLAY with no killer name: unknown, nothing changes.

Your killer is remembered across restarts (`state.json`, last killer you
played, never the opponent's). Manual override:

- `dbd-overlay ctl pick-killer`: searchable list
- `dbd-overlay ctl set-killer trapper`: by name (aliases like `billy`, `ghostface` work)

## Winstreaks

One **survivor** streak and one streak **per killer**. Each match is stored
with its raw facts (role, killer, map, each survivor's outcome, hatch,
auto/manual); streak numbers are computed from that history, never stored.

| Number | Meaning |
|---|---|
| streak | consecutive wins since the last reset |
| attempt | "Attempt #N": losses since the last reset + 1 |
| best | longest streak ever (a reset doesn't erase it) |

### Which streaks are on

Not every game is a streak. Each streak (survivor, each killer) is switched
**on or off**; only matches played while their streak is on count. Matches
are always saved either way, so pausing a streak and resuming later continues
where you left off, and switching one off never erases counted wins.

- New streaks start **off**. (After upgrading, streaks you already had matches in stay on.)
- `streak-toggle` switches your current streak (the killer you're on, or
  survivor). Pressed **right after a match** (within 10 min) while off, it
  also counts the match you just played, for when you forgot to turn it on.
- The settings window lists every streak with a checkbox.
- The HUD shows `(off)` with dimmed numbers for a streak that isn't on, and
  doesn't ask "win or loss?" for it.

### Win rules (`[streaks]` in the config)

Killer presets (`killer_preset`). "Removed" = killed/sacrificed/mori'd,
surrendered (always), or disconnected (if `dc_counts_as_kill = true`):

| Preset | Win when |
|---|---|
| `4k` | all 4 survivors removed |
| `3k_hatch` (default) | all 4 removed, **or** 3 removed and the last one escaped through the **hatch** (a gate escape is a loss) |
| `3k_any` | at least 3 removed; the 4th may escape any way |
| `custom` | `custom_killer_required` removed; `custom_killer_count_hatch = true` counts a hatch escape as removed |

Survivor presets (`survivor_preset`):

| Preset | Win when |
|---|---|
| `i_escape` (default) | you escape (gate or hatch) |
| `3_out` | at least 3 survivors escape, you or not (SWF) |
| `4_out` | all 4 escape |
| `custom` | `custom_survivor_self_escape` and/or at least `custom_survivor_min_escapes` out |

If the facts can't decide (e.g. `3k_hatch` with one escape: hatch and gate
look identical on the scoreboard), the match is marked **"win or loss?"** on
the HUD instead of guessing. Each match keeps the verdict it got when it was
recorded, so a rule change applies from now on; `ctl streak-recompute`
re-applies the current rules to the whole history (undoable).

**Settings window** (`ctl settings` or the tray menu): presets, custom
rules, DC option and HUD mode, with a plain-English description of the
active rule. "Save" applies from now on; "Save & apply to history" re-judges
past matches. Changes take effect immediately.

### What is read automatically

At the scoreboard each survivor's **status icon** is classified by shape:

| Icon | Recorded as |
|---|---|
| exit door | escaped (gate and hatch look the same) |
| skull | killed / sacrificed |
| white flag | surrendered (always counts as a kill) |
| person silhouette | still in the trial when you left (you died early): unknown |
| anything else (e.g. a disconnect: no sample yet) | unknown, frame saved to `debug/` |

Your own outcome as survivor comes from the result banner (ESCAPED / SACRIFICED).

**Hatch vs gate** isn't visible on the scoreboard, so it's inferred: opening
a gate always starts the **End Game Collapse** (the bar across the top). If
the app watched the match from the title card to the end (no gap over 30 s)
and never saw the EGC, every escape was through the hatch. If the EGC
appeared, both were possible, so a `3k_hatch` match with one escape asks you.

### Recording

- **Automatic**: at the scoreboard the match is recorded and judged. If the
  rules can't decide from what was read, the HUD asks **win or loss?**.
- `streak-win` / `streak-loss`: fill in or correct the match that was just
  auto-recorded (within 10 min, once); otherwise record a new match for your
  current role/killer (for games detection missed).
- `streak-toggle`: switch the current streak on/off (see above).
- `streak-ignore`: the last match doesn't count (DC, bugged game); again to un-ignore.
- `streak-undo`: undo the last streak action (record, win/loss, ignore, reset, recompute).
- `streak-reset`: start the current streak over (attempt #1).
- `set-role killer|survivor`, `set-killer <name>`: choose the streak manually.
- `toggle-hud`: show/hide the HUD (`[hud] show = "match_end" | "always" | "hotkey"`).
- `dbd-overlay export history.csv` / `.json`, `dbd-overlay import history.json`.

### Settings window

Left-click the tray icon (or `dbd-overlay ctl settings`). Pages:

- **Streaks**: switch each streak on/off, with its current numbers.
- **Win rules**: killer/survivor presets or custom rules; "Save & re-judge
  history" applies them to past matches too.
- **HUD**: when it shows, layout (card or compact), which parts to show,
  icon size, size, opacity, colours, border, corner radius, font and the
  titles (`{killer}` = killer name). The HUD stays on screen while this page
  is open and every change previews live; Cancel reverts. "Move it on
  screen…" = `edit-hud`.
- **Icons**: pick a picture for Survivor or any killer.

Everything is saved to the config (`[hud]`, `[icons]`), so it can be edited by
hand too.

### Icons

Two ways, the first wins: pick one in Settings > Icons (stored as a path in
`[icons]`), or drop files in `assets/icons/killers/<killer>.png` (e.g.
`The Trapper.png` or just `Trapper.webp`) and `assets/icons/survivor.png`.
Without either the HUD shows text only.

### Replay (no game needed)

```sh
uv run dbd-overlay replay ~/dbd-samples                       # what does it see?
uv run dbd-overlay replay tests/fixtures/screens \
    --manifest tests/fixtures/screens/manifest.json           # regression check
```

Replay runs the same detector as the live app and prints the events it would
publish. The manifest lists per-file expectations (`map`, `end`, `lobby`,
`lobby_role`, `lobby_killer`); see
`detection/replay.py`.

## Discord status (optional)

Shows where you are as your Discord status: menus, lobby / searching, in a
match (as which killer, or "Survivor"; map; elapsed time) and the result
afterwards ("Escaped · vs The Pig"). Off by default.

"In a match" starts when you leave a lobby you queued from. The map comes
from the title card at the start of the match; if the game's workspace wasn't
on screen then, the map stays blank (fix it with `ctl set-map`), and the
timer counts from the end of the lobby instead of the real start.

1. Create an application at <https://discord.com/developers/applications>.
   Its **name** is what Discord shows after "Playing", e.g. "Dead by Daylight".
2. Settings > Discord: paste its Application ID, switch it on, Save.
   (Or `[discord] enabled = true` + `client_id = "..."` in the config.)
3. `dbd-overlay ctl toggle-discord` (or the tray menu) switches it on/off.

Talks to the local Discord app over its IPC socket (`discord-ipc-0`); works
with the official client and with arRPC (Vesktop). If Discord also lists the
game by itself, turn that off under Registered Games to avoid two entries.
Survivor names aren't detected (the lobby doesn't show them), so survivors
show as "Survivor".

## Development

```sh
uv run pytest
```

Layout: `core/` (events, config, models, commands: no Qt), `detection/`
(no UI imports), `features/`, `storage/`, `platform/` (Protocols + Hyprland /
Windows adapters), `ui/` (Qt). See the project spec for the full design.
