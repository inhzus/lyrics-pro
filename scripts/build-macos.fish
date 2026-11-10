#!/usr/bin/env fish
# Build a local Finder-launchable app without an Xcode project.
set -l root (path resolve (path dirname (status filename))/..)
set -l package "$root/macos"
set -l app "$root/dist/Lyrics Pro.app"

if not test -x "$root/.venv/bin/python"
    printf 'Missing Python environment. Run uv sync --locked in %s first.\n' "$root" >&2
    exit 1
end
swift build --package-path "$package" --configuration release; or exit $status
set -l bin (swift build --package-path "$package" --configuration release --show-bin-path)
or exit $status
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"; or exit $status
cp "$bin/LyricsPro" "$app/Contents/MacOS/LyricsPro"; or exit $status
cp "$package/Support/Info.plist" "$app/Contents/Info.plist"; or exit $status
"$root/.venv/bin/python" -c 'import json, pathlib, sys; root = pathlib.Path(sys.argv[1]); pathlib.Path(sys.argv[2]).write_text(json.dumps({"projectRoot": str(root), "python": str(root / ".venv/bin/python")}))' "$root" "$app/Contents/Resources/Backend.json"
or exit $status
codesign --force --sign - --entitlements "$package/Support/LyricsPro.entitlements" "$app"; or exit $status
printf '\nBuilt: %s\nOpen with: open "%s"\n' "$app" "$app"
