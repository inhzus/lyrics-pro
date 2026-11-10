import Foundation

/// Bundle-relative paths are valid after moving or renaming the app in Finder.
struct BackendLaunch {
    let executable: URL
    let workingDirectory: URL
    let environment: [String: String]

    init(bundleURL: URL, inheritedEnvironment: [String: String]) {
        executable = bundleURL.appendingPathComponent("Contents/Helpers/LyricsBackend.app/Contents/MacOS/lyrics-pro-worker")
        workingDirectory = bundleURL.appendingPathComponent("Contents/Resources", isDirectory: true)
        var clean = inheritedEnvironment.filter { key, _ in
            !key.hasPrefix("PYTHON") && !key.hasPrefix("_PYI") && !key.hasPrefix("PYINSTALLER") &&
            !key.hasPrefix("DYLD_") && key != "VIRTUAL_ENV" && key != "__PYVENV_LAUNCHER__"
        }
        clean["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        clean["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        environment = clean
    }
}
