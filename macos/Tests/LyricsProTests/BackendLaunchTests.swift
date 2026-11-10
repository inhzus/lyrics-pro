import Foundation
import Testing
@testable import LyricsPro

struct BackendLaunchTests {
    @Test func relocatedBundleIgnoresDevelopmentEnvironment() {
        let bundle = URL(fileURLWithPath: "/Applications/Personal Apps/Renamed Lyrics.app")
        let launch = BackendLaunch(bundleURL: bundle, inheritedEnvironment: [
            "HOME": "/Users/recipient", "TMPDIR": "/tmp/recipient/", "LANG": "en_US.UTF-8",
            "PATH": "/opt/homebrew/bin", "PYTHONPATH": "/old/repo/src", "PYTHONHOME": "/old/python",
            "VIRTUAL_ENV": "/old/repo/.venv", "_PYI_APPLICATION_HOME_DIR": "/old/bundle",
            "PYINSTALLER_SUPPRESS_SPLASH_SCREEN": "0", "DYLD_LIBRARY_PATH": "/old/libraries",
            "__PYVENV_LAUNCHER__": "/old/python",
        ])
        #expect(launch.executable.path == bundle.path + "/Contents/Helpers/LyricsBackend.app/Contents/MacOS/lyrics-pro-worker")
        #expect(launch.workingDirectory.path == bundle.path + "/Contents/Resources")
        #expect(launch.environment == ["HOME": "/Users/recipient", "TMPDIR": "/tmp/recipient/",
            "LANG": "en_US.UTF-8", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "PYINSTALLER_RESET_ENVIRONMENT": "1"])
    }
}
