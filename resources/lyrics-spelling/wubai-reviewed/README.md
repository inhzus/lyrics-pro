# Reviewed Wu Bai collection

53 distinct supplied songs: 51 newly adapted, 1 previously accepted, 1 awaiting reliable timing.
The three duplicate raw files remain accounted for in the original preparation manifest.

These are reviewed text alignments, not listening-verified pronunciation or onset corrections.
Original transcripts are unchanged. Each folder preserves the selected online timeline,
explicit phrase assignments, source-backed repairs, input hashes, and a listening preview.
Automatic playback requires a reviewed title/alias and duration within two seconds;
artist and album describe provenance. Explicit online recording choices remain online lyrics.

## Reproduce

Run from the repository root:

~~~fish
uv run --locked python -m scripts.prepare_wubai --check
uv run --locked python -m scripts.prepare_wubai --integrate
~~~

Both commands are offline. The first checks bundled outputs; the second recreates and
integrates reviewed outputs, refusing to overwrite a different existing asset.

## Outstanding timing

- **恨世生**: LRCLIB 18267561 and five other LRCLIB copies omit the supplied final 啊. NetEase 157321 contains 啊 at 169.24s but its lyric metadata says 夏夜晚風 while the catalog says 伍佰的Live; its events also disagree substantially with the LRCLIB timing. No fabricated vocalization timestamp or mixed timelines.

## Source spelling and version notes

- **來去夏威夷**: The file is labelled 伍佰, but the complete 204.033-second timing is the original 金門王與李炳輝 recording. It does not match the 201.192-second or 91.4-second Wu Bai live recordings.
- **厲害**: Source line 85 retains put ti hué-kái paired with 襯襯採採. This appears copied from 不知悔改; no replacement reading was invented. The source remix note is retained, but this asset uses the studio timeline only.
- **小姐免驚**: Source line 80 pairs 請你無免驚 with tshiánn lí án-tsuánn. Preserve that occurrence rather than silently replacing the supplied reading.
- **徘徊夜都市**: Source cguá and repeated too-tshī are retained; transcription needs pronunciation proofreading.
- **枉費青春**: The supplied sustained 啊 is reused for online vocalization events; no syllable onsets are inferred.
- **樹枝孤鳥**: Source line 49 pairs 戲弄著我…憨憨轉啊 with the earlier 欺騙著我…癡情花啊 reading. Preserved as supplied; needs pronunciation proofreading.

## Listening previews

| Song | Recording | Duration | Status |
|---|---|---:|---|
| [何時再見夢中人](supplied-bf15ce3460b283c3a0ee/timed-proofread.md) | netease:452614918 · 圣石传说 电影原声带 | 231.573s | ready |
| [衝衝衝](supplied-80000036c4b90146554d/timed-proofread.md) | netease:156708 · 爱你伍佰年 | 217.710s | ready |
| [殺手驪歌](supplied-dd3eec746ec23efbd44f/timed-proofread.md) | lrclib:29760563 · 順流逆流 | 280.000s | ready |
| [KISS ME (星星知我心)](supplied-cde4185c5607ccf1f24a/timed-proofread.md) | netease:156643 · 爱你伍佰年 | 257.555s | ready |
| [下港人在台北市](supplied-e690ee6a2bf5f096efee/timed-proofread.md) | netease:156520 · 双面人 | 273.200s | ready |
| [世界第一等](supplied-aa877b02e4f643c35279/timed-proofread.md) | netease:156868 · 冬之火 九重天演唱会特选录音专辑 | 238.468s | ready |
| [仝款的月娘](supplied-8ca6d9b80e01abd71bce/timed-proofread.md) | netease:449769019 · 钉子花 | 273.336s | ready |
| [來去夏威夷](supplied-a7a75ded38c39f487cfa/timed-proofread.md) | netease:361000 · 来去夏威夷 | 204.033s | ready |
| [厲害](supplied-7cfec46e7b59e36be4eb/timed-proofread.md) | netease:156501 · 双面人 | 221.306s | ready |
| [只要為你活一天](supplied-6f29e51a7ab9bc94bccf/timed-proofread.md) | lrclib:22685391 · 只要为你活一天 电影原声带 | 321.228s | ready |
| [台北孤兒](supplied-4a3a91defa0c8724fefc/timed-proofread.md) | lrclib:40160357 · 生命的现场LIVE | 269.000s | ready |
| [台灣製造](supplied-c3dd80fb75f4f253c5b3/timed-proofread.md) | netease:156513 · 双面人 | 218.373s | ready |
| [墓仔埔也敢去](supplied-e79110986bdaccc2c6c3/timed-proofread.md) | netease:156639 · 爱你伍佰年 | 220.408s | ready |
| [小姐免驚](supplied-d9c8c39216c8ac696ee9/timed-proofread.md) | lrclib:18535997 · 伍佰的Live | 197.907s | ready |
| [少女的心](supplied-1cbc34a98035a9027c38/timed-proofread.md) | netease:157168 · 树枝孤鸟 | 274.760s | ready |
| [少年吔，安啦!](../shao-nian-eh-an-la/timed-proofread.md) | — ·  | — | existing |
| [往事欲如何](supplied-408c2bdb4cfd97d1b4d4/timed-proofread.md) | netease:156372 · 忘情1015精选辑 | 263.053s | ready |
| [徘徊夜都市](supplied-0c8c4784e6efd68493d3/timed-proofread.md) | lrclib:17325984 · 树枝孤鸟 | 261.930s | ready |
| [心愛的再會啦](supplied-794b992d79807fc0f460/timed-proofread.md) | netease:157180 · 树枝孤鸟 | 335.389s | ready |
| [快樂的等待](supplied-6ddcb1b7f57be05b548e/timed-proofread.md) | netease:156523 · 双面人 | 261.040s | ready |
| [怨嗟嘆](supplied-ee5d055b9529662ea72e/timed-proofread.md) | netease:157197 · 树枝孤鸟 | 325.400s | ready |
| 恨世生 | — ·  | — | needs timing |
| [愛妳無目地](supplied-96ecffda262b750c1042/timed-proofread.md) | netease:2051740555 · 夏日告白情歌 | 218.420s | ready |
| [愛情限時批](supplied-99d12880f43b3fcf5c17/timed-proofread.md) | netease:297917 · One芳 新歌+精选 | 222.307s | ready |
| [放浪舞者](supplied-267a0c73afb0c278eeb6/timed-proofread.md) | netease:449769017 · 钉子花 | 271.000s | ready |
| [斷腸詩](supplied-04247bde48aaf44405d6/timed-proofread.md) | netease:156664 · 爱你伍佰年 | 215.706s | ready |
| [東石](supplied-a1d63214e4ffbfa8c97f/timed-proofread.md) | netease:449769015 · 钉子花 | 298.585s | ready |
| [枉費青春](supplied-2d97182b1b71050424e3/timed-proofread.md) | lrclib:21201274 · 伍佰的Live | 167.733s | ready |
| [樓仔厝](supplied-b3d0dd9906efa9010654/timed-proofread.md) | lrcapi:156207236 · 夏夜晚风 演唱会精选实录 - 摇滚·浪漫 (Live) | 326.333s | ready |
| [樹枝孤鳥](supplied-74b61c00999a39dd0c08/timed-proofread.md) | netease:157192 · 树枝孤鸟 | 297.360s | ready |
| [汝是我的心肝](supplied-986c502c66ae02629a09/timed-proofread.md) | lrclib:15303180 · 忘情1015精选辑 | 298.658s | ready |
| [海上的島](supplied-6b448a9ac6693ad0a4e4/timed-proofread.md) | netease:156509 · 双面人 | 388.466s | ready |
| [海底飛凌機](supplied-bd69d1a7c5671b04393c/timed-proofread.md) | netease:156515 · 双面人 | 315.226s | ready |
| [漂浪](supplied-9e39fa38d2424d4a8876/timed-proofread.md) | netease:157174 · 树枝孤鸟 | 245.360s | ready |
| [無聲的所在](supplied-b50a1dcdc27788c1d8e3/timed-proofread.md) | netease:156994 · 电影歌曲典藏1992-2000 | 267.933s | ready |
| [煞到妳](supplied-52cf388e768a2d06303f/timed-proofread.md) | netease:157186 · 树枝孤鸟 | 181.240s | ready |
| [熱淚暗班車](supplied-4e3ad661c72dc94ce064/timed-proofread.md) | netease:449769018 · 钉子花 | 291.178s | ready |
| [白鷺鷥](supplied-6213b5da555d236db815/timed-proofread.md) | netease:156292 · 诗情摇滚 | 293.360s | ready |
| [秋風夜雨](supplied-0d99e1e2673dcdf5d500/timed-proofread.md) | netease:156635 · 爱你伍佰年 | 259.259s | ready |
| [稀微的風中](supplied-ff59d0128bc9fe36575b/timed-proofread.md) | netease:452614917 · 圣石传说 电影原声带 | 229.266s | ready |
| [種子](supplied-f81396bc56aedc738c99/timed-proofread.md) | netease:449769021 · 钉子花 | 317.371s | ready |
| [空襲警報](supplied-66c3931786221442fdb2/timed-proofread.md) | netease:157189 · 树枝孤鸟 | 244.466s | ready |
| [素蘭小姐要出嫁](supplied-306250fc14604694b92d/timed-proofread.md) | netease:157406 · 爱上别人是快乐的事 | 198.344s | ready |
| [莎喲娜啦](supplied-1034a673a9e9a8941843/timed-proofread.md) | netease:156526 · 双面人 | 266.426s | ready |
| [萬丈深坑](supplied-893fcbba0b343b0ad07b/timed-proofread.md) | netease:157178 · 树枝孤鸟 | 248.533s | ready |
| [蹦孔](supplied-22d1886b6e92a99cc5f9/timed-proofread.md) | netease:449769014 · 钉子花 | 332.736s | ready |
| [返去故鄉](supplied-1c328ec625966857dd8f/timed-proofread.md) | netease:157176 · 树枝孤鸟 | 347.773s | ready |
| [釘子花](supplied-6a497c88b3811aae3105/timed-proofread.md) | netease:446875821 · 钉子花 | 373.701s | ready |
| [雙面人](supplied-97d3299cc8a386a03961/timed-proofread.md) | netease:156505 · 双面人 | 281.053s | ready |
| [風颱心情](supplied-35811cea5109bd26e617/timed-proofread.md) | netease:156517 · 双面人 | 244.653s | ready |
| [飛](supplied-eb79c3ec6c794433eca6/timed-proofread.md) | lrclib:16432589 · 伍佰的LIVE-枉費青春 | 299.493s | ready |
| [飛在風中的小雨](supplied-3be77a1c42c4c9032a8b/timed-proofread.md) | netease:156682 · 爱你伍佰年 | 251.489s | ready |
| [點煙](supplied-cbdd07883a98f319373b/timed-proofread.md) | netease:156594 · 爱你伍佰年 | 340.985s | ready |
