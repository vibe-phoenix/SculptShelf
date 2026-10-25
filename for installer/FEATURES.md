# SculptShelf features

## Library

- One searchable thumbnail grid per tab: **Brushes** (`.ZBP`), **Alphas** (`.PSD`, `.BMP`, `.JPG`, `.PNG`, `.TIF`) and **Materials** (`.ZMT`).
- Add as many folders as you like in Settings. Files stay where they are; nothing is copied or changed.
- Real previews: the icon stored inside each brush and material file, and the image itself for alphas. Sidecar images (`Name.png`, `Previews\Name.png`) are used when a file has no icon.
- Thumbnails are cached, so reopening is instant.
- Folders are watched: new, changed, renamed and deleted files show up automatically (Ctrl+R refreshes by hand).

## Loading

- Double-click a tile (or press Enter / Shift+E) to load it into ZBrush. Single-click loading can be switched on in Settings.
- Brushes are always loaded fresh from the file, so their own alpha and settings are reset. ZBrush's "already loaded" question is answered automatically.
- An alpha or material that is already loaded is simply selected again.
- Loading a material replaces the active material slot, exactly like ZBrush's own Material → Load.
- SculptShelf minimizes after loading so you can sculpt straight away. ZPlugin → SculptShelf → Open SculptShelf brings it back.

## Favourites

- Right-click a tile → Add to favourites / Remove from favourites.
- Favourite mode (Ctrl+F): confirm, click tiles to mark or unmark many at once, then Apply and confirm.
- Reorder favourites by dragging (right-click → Reorder favourites).
- Favourites show a gold star and are listed first (switchable).

## Shortcuts

| Key | Action |
|---|---|
| Ctrl+Space | Jump to the search box |
| Tab | From the search box: select the first result |
| W A S D / Arrows | Move between tiles |
| Enter / Shift+E | Load the selected tile |
| Shift+Tab | Back to the search box |
| X | Cycle Brushes → Alphas → Materials |
| Ctrl+F | Favourite mode |
| Ctrl+R | Refresh the library |
| Ctrl+Shift+X | Minimize SculptShelf (change it in Settings) |
| F1 / ? | Features & Shortcuts |
| Esc | Clear the search, or leave favourite / reorder mode |

## Settings and data

- Dark interface, adjustable tile size, always-on-top options, full-path tooltips.
- Settings, favourites and the thumbnail cache are kept in `Documents\ZBrush\SculptShelf`, so they survive reinstalls and updates.

Made by Vibe Phoenix
