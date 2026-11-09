# dbd-overlay

Dead by Daylight helper for Linux (Hyprland) and later Windows: automatic map
overlay and a per-killer / survivor winstreak HUD.

**Anti-cheat safety:** this tool only takes screenshots of the game window and
draws its own separate windows. It never reads or writes game memory, injects
anything, or touches game files.

> Status: milestone 3. Map detection works (tray notification + picker);
> the overlay window and streaks are not built yet.

## Install / run

System tools: `sudo pacman -S tesseract tesseract-data-eng grim`

```sh
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
```

Classic `hyprland.conf`:

```ini
bind = SUPER, M, exec, dbd-overlay ctl toggle-overlay
bind = SUPER SHIFT, M, exec, dbd-overlay ctl pick-map
```

The map picker window has class `dbd-overlay`; make it float:

```lua
hl.window_rule({ match = { class = "^(dbd-overlay)$" }, float = true, pin = true })
```

The tray icon needs a StatusNotifier host, e.g. waybar's `tray` module.

## Map detection

At match start the game shows a title card bottom-left: map name (bright),
a thin teal line, realm name (dim) below. The app finds the line (cheap, no
OCR), OCRs both lines with Tesseract, and fuzzy-matches them against
`src/dbd_overlay/data/maps.json`:

- map matched (confirmed by the realm) -> notification (M4: overlay shows);
- realm matched, map unclear -> picker with only that realm's maps;
- teal line but nothing readable -> full picker, frame saved to
  `~/.local/share/dbd-overlay/debug/` so detection can be improved.

Only the bottom-left strip of the window is captured (~1% of one CPU core at 1 fps).
Detection pauses while the game's workspace isn't visible.

### Replay (no game needed)

```sh
uv run dbd-overlay replay ~/dbd-samples                       # what does it see?
uv run dbd-overlay replay tests/fixtures/screens \
    --manifest tests/fixtures/screens/manifest.json           # regression check
```

## Development

```sh
uv run pytest
```

Layout: `core/` (events, config, models, commands: no Qt), `detection/`
(no UI imports), `features/`, `storage/`, `platform/` (Protocols + Hyprland /
Windows adapters), `ui/` (Qt). See the project spec for the full design.
