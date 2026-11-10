#!/usr/bin/env fish
# Some Command Line Tools builds omit automatic discovery of TestingMacros.
set -l root (path resolve (path dirname (status filename))/..)
set -l swift_path (xcrun --find swift)
or exit $status
set -l toolchain (path dirname (path dirname "$swift_path"))
set -l plugin "$toolchain/lib/swift/host/plugins/testing/libTestingMacros.dylib"
set -l flags
if test -f "$plugin"
    set flags -Xswiftc -load-plugin-library -Xswiftc "$plugin"
end
swift test --package-path "$root/macos" --configuration release --disable-xctest $flags $argv
