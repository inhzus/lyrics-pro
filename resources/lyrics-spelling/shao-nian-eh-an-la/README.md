# 少年吔，安啦 — bundled proofread candidate

The original user-supplied transcription is [preserved here](../少年吔，安啦-伍佰).
`proofread.json` records its paired blocks and four explicitly split column pairs.
`timed.json` freezes the previously selected NetEase 5237870 cache snapshot;
it is not a new network lookup. Artist and album identify the reference recording,
but only normalized title and duration (413.786 ±2 seconds) gate the app asset.

[Listen with this timestamped preview](timed-proofread.md). The 49 sung rows use
supplied text/spelling, with repeated choruses expanded along the online timeline.
Six gap events and three source credit events are retained in the runtime asset.
This is not audio verification: 13 approximate matches, three backing-vocal
omissions, and the `叫我` boundary around 05:22.08–05:28.58 remain documented.

To reproduce, extract `align_proofread.py` as described in the
[alignment guide](../../../docs/proofread-lyrics-alignment.md), then run it with
this directory's `proofread.json` and `timed.json` into a new temporary directory.
The bundled JSON under `src/lyrics_pro/data/proofread/` wraps its alignment report
with asset ID, revision, language, attribution, and recording metadata. Its report
also hashes the original user file. Revisions must preserve source timestamps and
paired spelling; bump the asset revision after a reviewed edit.

Revision 2 collapses tabs, full-width spaces, and repeated whitespace to single
ordinary spaces when loading display rows. Source text, spelling, timing inputs,
and the listening preview retain their original transcription layout.

Revision 3 gives the resource its independent `proofread:shao-nian-eh-an-la`
identity. NetEase 5237870 remains timestamp provenance only. Automatic prefers
this resource when title and duration match; it is also separately selectable
in Recording → Lyrics source. Explicit online choices use their own content.

Words: 伍佰 / 陳世杰. Music: 伍佰. Supplied romanization: 關德樂.
Transcription reference: <https://taikegui.wordpress.com/2017/04/28/少年吔，安啦/>.
Timing reference: <https://music.163.com/song?id=5237870>.
These content assets are separate from the application's MIT-licensed code.
