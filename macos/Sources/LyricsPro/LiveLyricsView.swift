import SwiftUI

private typealias FollowingStorage = State<LyricFollowingState>
private typealias ConversionStorage = State<ScriptConversionCache>

struct LiveLyricsView: View {
    @ObservedObject var connection: MusicConnection
    let accent: Color
    let fontSize: CGFloat
    @FollowingStorage private var following = LyricFollowingState()
    @ConversionStorage private var conversion = ScriptConversionCache()
    @AppStorage(ChineseScript.preferenceKey) private var script = ChineseScript.original
    @AppStorage(LyricTiming.preferenceKey) private var timingDelay = LyricTiming.setting.standard

    private var update: LyricUpdate? { connection.state.lyric }

    var body: some View {
        Group {
            if let update, (update.status == .ready || update.status == .plain), let lyrics = update.lyrics {
                FollowingLyricsView(lyrics: conversion.lyrics(lyrics, in: script), generation: connection.state.generation,
                                    requestID: update.requestID, recordingRevision: update.selectionRevision ?? 0,
                                    position: LyricTiming.lyricPosition(atAudio: connection.presentation.position,
                                                                        delay: timingDelay),
                                    accent: accent, fontSize: fontSize, following: $following,
                                    canSeek: connection.canSeek, followRevision: connection.controls.followRevision,
                                    seek: { [generation = connection.state.generation, timingDelay] position in
                                        let audio = LyricTiming.audioPosition(forLyric: position, delay: timingDelay)
                                        connection.control(.seek, position: audio, resumeFollowing: true,
                                                           expectedGeneration: generation)
                                    })
            } else {
                statusPanel
            }
        }
    }

    @ViewBuilder private var statusPanel: some View {
        let retry = StatusPanel.Action(title: "Try Again") { connection.retryLyrics() }
        switch update?.status {
        case .instrumental:
            StatusPanel(icon: "music.note", title: "Just the music",
                        detail: "The lyric provider marks this recording as instrumental.", accent: accent)
        case .unavailable:
            StatusPanel(icon: "text.quote", title: "No lyrics found",
                        detail: update?.message ?? "Try looking up this song again.", accent: accent, action: retry)
        case .error:
            StatusPanel(icon: "exclamationmark.circle", title: "Lyrics unavailable",
                        detail: update?.message ?? "Try looking up this song again.", accent: accent, action: retry)
        default:
            StatusPanel(icon: nil, title: "Finding lyrics…", accent: accent)
        }
    }
}

struct LyricSourceLabel: View {
    @ObservedObject var connection: MusicConnection

    var body: some View {
        if let lyrics = connection.state.lyric?.lyrics {
            HStack(spacing: 7) {
                if let url = lyrics.sourceURL {
                    Link(lyrics.sourceName, destination: url)
                        .help(lyrics.proofread.map { "\($0.attribution)\nOpen the timing source" } ?? "Open the lyric source")
                } else {
                    Text(lyrics.sourceName)
                }
                Text("·")
                Text(lyrics.instrumental ? "Instrumental" : (lyrics.synced ? "Timed lyrics" : "Untimed lyrics"))
                if let proofread = lyrics.proofread, lyrics.sourceName != "Proofread" {
                    Text("·")
                    Text("Proofread")
                        .help(proofread.attribution)
                }
            }
            .font(.system(size: 11))
            .foregroundStyle(.white.opacity(0.6))
            .lineLimit(1)
        }
    }
}

