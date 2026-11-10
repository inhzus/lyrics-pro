#!/usr/bin/env fish
# Self-contained Apple Silicon app and personal-sharing ZIP.
set -l root (path resolve (path dirname (status filename))/..)
set -l package "$root/macos"
set -l build "$root/.build"
set -l app "$root/dist/Lyrics Pro.app"

if test (uname -m) != arm64
    printf 'This release build requires an Apple Silicon Mac.\n' >&2
    exit 1
end
set -l python_version (string trim < "$root/packaging/.python-version")
env UV_PROJECT_ENVIRONMENT="$root/packaging/.venv" uv sync --project "$root/packaging" \
    --python "$python_version" --locked --no-dev --no-editable; or exit $status
set -l python "$root/packaging/.venv/bin/python"
mkdir -p "$build" "$root/dist"; or exit $status
"$python" -m PyInstaller --noconfirm --clean --distpath "$build/backend" \
    --workpath "$build/pyinstaller" "$root/packaging/worker.spec"; or exit $status

swift build --package-path "$package" --configuration release; or exit $status
set -l bin (swift build --package-path "$package" --configuration release --show-bin-path)
or exit $status
set -l stage (mktemp -d "$build/release-XXXXXX"); or exit $status
set -l app_version (/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$package/Support/Info.plist")
or exit $status
set -l name "Lyrics-Pro-$app_version-macOS-arm64"
set -l release "$stage/$name"
set -l staged_app "$release/Lyrics Pro.app"
mkdir -p "$staged_app/Contents/MacOS" "$staged_app/Contents/Resources" "$staged_app/Contents/Helpers"
or exit $status
cp "$bin/LyricsPro" "$staged_app/Contents/MacOS/LyricsPro"; or exit $status
cp "$package/Support/Info.plist" "$staged_app/Contents/Info.plist"; or exit $status
ditto "$build/backend/LyricsBackend.app" "$staged_app/Contents/Helpers/LyricsBackend.app"; or exit $status
set -l iconset "$package/.build/AppIcon.iconset"
swift "$root/scripts/render-icon.swift" "$iconset"; or exit $status
iconutil -c icns "$iconset" -o "$staged_app/Contents/Resources/AppIcon.icns"; or exit $status
"$python" "$root/packaging/bundle.py" prepare "$staged_app"; or exit $status
env -i PATH=/usr/bin:/bin HOME="$HOME" "$staged_app/Contents/Helpers/LyricsBackend.app/Contents/MacOS/lyrics-pro-worker" --self-check
or exit $status
cp "$root/packaging/Install.txt" "$release/Install.txt"; or exit $status
ditto -c -k --keepParent --norsrc "$release" "$stage/$name.zip"; or exit $status

# Keep the last successful app until the new bundle has passed its build checks.
if test -e "$app"
    mv "$app" "$stage/Previous Lyrics Pro.app"; or exit $status
end
mv "$staged_app" "$app"; or exit $status
mv "$stage/$name.zip" "$root/dist/$name.zip"; or exit $status
printf '\nBuilt: %s\nShare: %s\n' "$app" "$root/dist/$name.zip"
