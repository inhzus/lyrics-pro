# PyInstaller directory bundle, with macOS code/resources separation for signing.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
data = collect_data_files("ToJyutping") + collect_data_files("taibun")
data += [(str(root / "src/lyrics_pro/data/proofread"), "lyrics_pro/data/proofread")]
for package in ("ToJyutping", "taibun", "msgpack"):
    data += copy_metadata(package)

a = Analysis(
    [str(root / "packaging/worker.py")],
    pathex=[str(root / "src")],
    datas=data,
    hiddenimports=["msgpack._cmsgpack"],
    excludes=["pytest", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [("u", None, "OPTION")],
    exclude_binaries=True, name="lyrics-pro-worker", console=True,
    target_arch="arm64", codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LyricsBackend")
app = BUNDLE(
    coll, name="LyricsBackend.app", bundle_identifier="com.lyricspro.local.worker",
    info_plist={"LSBackgroundOnly": True, "LSMinimumSystemVersion": "15.0",
                "NSAppleEventsUsageDescription": "Lyrics Pro reads and controls playback in Music."},
)
