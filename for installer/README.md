# SculptShelf

A brush, alpha and material browser for **ZBrush 2027 on Windows**. Point it at your brush, alpha and material folders and SculptShelf shows them in one fast, searchable thumbnail grid. Double-click to load straight into ZBrush.

## Requirements

- Windows 10 or 11, 64-bit
- ZBrush 2027 or later (uses ZBrush's Python plugin support)
- Nothing else: the companion app is self-contained

## After installing

1. Start ZBrush.
2. Choose **ZPlugin → SculptShelf → Open SculptShelf**. Tip: assign it a hotkey (for example Ctrl+Shift+X) with ZBrush's Preferences → Hotkeys.
3. In SculptShelf open **Settings** and click **Add Folder…** under *Brush Locations*, *Alpha Locations* or *Material Locations*.
4. Double-click any tile to load it.

## What gets installed

- `ZPlugs64\SculptShelf.py`: the ZBrush plugin (adds the ZPlugin → SculptShelf menu).
- `ZPlugs64\SculptShelfData\`: the companion app.

Your settings, favourites and thumbnail cache live in `Documents\ZBrush\SculptShelf` and are kept when you update or uninstall.

## Notes

- Loading a brush, alpha or material adds it to ZBrush's palette for the session, the same as loading it by hand.
- Loading a material replaces the active material slot, like ZBrush's Material → Load.
- If SculptShelf was installed earlier with its own Setup, uninstall that first so NexusTools can manage the files.

Made by Vibe Phoenix
