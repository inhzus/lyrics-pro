"""Build-time bundle licensing, signing, and portability checks (stdlib only)."""
import argparse
from importlib.metadata import distribution, version
import json
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sysconfig


MACHO_MAGIC = {bytes.fromhex(value) for value in ("cffaedfe", "cefaedfe", "feedface", "feedfacf", "cafebabe", "bebafeca")}


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def binaries(app):
    for path in app.rglob("*"):
        if path.is_symlink():
            if not path.resolve().is_relative_to(app.resolve()):
                raise RuntimeError(f"External symlink in bundle: {path}")
        elif path.is_file():
            with path.open("rb") as stream:
                if stream.read(4) in MACHO_MAGIC:
                    yield path


def prepare(app):
    executable = app / "Contents/MacOS/LyricsPro"
    commands = run("/usr/bin/otool", "-l", str(executable))
    # SwiftPM adds a toolchain search path even though this target links only
    # system Swift libraries. Do not ship a dependency on the build machine.
    for rpath in re.findall(r"cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.*?) \(offset", commands):
        if rpath.startswith("/Library/Developer/") or ".app/Contents/Developer/" in rpath:
            run("/usr/bin/install_name_tool", "-delete_rpath", rpath, str(executable))
    licenses = app / "Contents/Resources/Licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(sysconfig.get_path("stdlib")) / "LICENSE.txt", licenses / "Python.txt")
    packages = ("ToJyutping", "taibun", "msgpack", "pyinstaller")
    for name in packages:
        package = distribution(name)
        files = [file for file in package.files or []
                 if "dist-info" in str(file) and any(word in file.name.lower() for word in ("license", "copying"))]
        if not files:
            raise RuntimeError(f"Missing license for {name}")
        for file in files:
            shutil.copyfile(package.locate_file(file), licenses / f"{name}-{file.name}")
    manifest = {"python": platform.python_version(),
                "packages": {name: version(name) for name in packages}, "architecture": "arm64"}
    (app / "Contents/Resources/BuildInfo.json").write_text(json.dumps(manifest, indent=2) + "\n")
    entitlements = Path(__file__).resolve().parent.parent / "macos/Support/LyricsPro.entitlements"
    for binary in sorted(binaries(app), key=lambda path: len(path.parts), reverse=True):
        # Signing a bundle's main executable implicitly signs its whole bundle.
        # Defer those until the nested libraries and helper app are complete.
        if binary.name not in ("LyricsPro", "lyrics-pro-worker"):
            run("/usr/bin/codesign", "--force", "--sign", "-", str(binary))
    for nested in sorted(app.rglob("*.app"), key=lambda path: len(path.parts), reverse=True):
        run("/usr/bin/codesign", "--force", "--sign", "-", "--entitlements", str(entitlements), str(nested))
    run("/usr/bin/codesign", "--force", "--sign", "-", "--entitlements", str(entitlements), str(app))


def verify(app):
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if info["LSMinimumSystemVersion"] != "15.0":
        raise RuntimeError("Expected macOS 15.0 deployment target")
    if (app / "Contents/Resources/Backend.json").exists():
        raise RuntimeError("Legacy repository-dependent Backend.json was packaged")
    count = 0
    for binary in binaries(app):
        count += 1
        if run("/usr/bin/lipo", "-archs", str(binary)) != "arm64":
            raise RuntimeError(f"Expected arm64 binary: {binary}")
        commands = run("/usr/bin/otool", "-l", str(binary))
        minimums = re.findall(r"\bminos (\d+)\.(\d+)", commands)
        minimums += re.findall(r"cmd LC_VERSION_MIN_MACOSX\n\s+cmdsize \d+\n\s+version (\d+)\.(\d+)", commands)
        if not minimums or any((int(major), int(minor)) > (15, 0) for major, minor in minimums):
            raise RuntimeError(f"Missing or incompatible macOS deployment minimum: {binary}")
        for dependency in run("/usr/bin/otool", "-L", str(binary)).splitlines()[1:]:
            library = dependency.strip().split(" (", 1)[0]
            if not library.startswith(("/usr/lib/", "/System/Library/", "@rpath/", "@loader_path/", "@executable_path/")):
                raise RuntimeError(f"External library in {binary}: {library}")
        for rpath in re.findall(r"cmd LC_RPATH\n\s+cmdsize \d+\n\s+path (.*?) \(offset", commands):
            if not rpath.startswith(("@loader_path", "@executable_path", "/usr/lib/", "/System/Library/")):
                raise RuntimeError(f"External runtime search path in {binary}: {rpath}")
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app))
    print(f"Verified {count} arm64 binaries, deployment targets, library paths, and bundle signature.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.app)
    verify(args.app)
