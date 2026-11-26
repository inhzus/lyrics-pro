# Template for Casks/lyrics-pro.rb in inhzus/homebrew-tap. The release workflow fills in
# version and sha256 and pushes it there.
cask "lyrics-pro" do
  version "0.9.0"
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"

  url "https://github.com/inhzus/lyrics-pro/releases/download/v#{version}/Lyrics-Pro-#{version}-macOS-arm64.zip"
  name "Lyrics Pro"
  desc "Synced lyrics with Cantonese and Hokkien pronunciation for Apple Music"
  homepage "https://github.com/inhzus/lyrics-pro"

  depends_on arch: :arm64
  depends_on macos: :tahoe

  app "Lyrics-Pro-#{version}-macOS-arm64/Lyrics Pro.app"

  # Builds are ad-hoc signed, not notarized, so Gatekeeper would block the first launch.
  # Remove this once releases are notarized.
  postflight_steps do
    run "/usr/bin/xattr",
        args:           ["-dr", "com.apple.quarantine", "{{appdir}}/Lyrics Pro.app"],
        writable_paths: ["{{appdir}}/Lyrics Pro.app"]
  end

  uninstall quit: "io.zunish.lyrics"

  zap trash: [
    "~/Library/Application Support/Lyrics Pro",
    "~/Library/Preferences/com.lyricspro.local.plist",
    "~/Library/Preferences/io.zunish.lyrics.plist",
  ]

  caveats <<~EOS
    Open Apple Music, play a song, and allow Lyrics Pro to control Music when macOS asks.
  EOS
end
