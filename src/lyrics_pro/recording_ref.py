"""Provider-qualified recording identities, including migration of old NetEase IDs."""
import re
from urllib.parse import urlparse, parse_qs


def recording_ref(value):
    if type(value) is int and value > 0:
        return f"netease:{value}"
    if isinstance(value, str) and len(value) <= 220:
        if re.fullmatch(r"netease:[1-9]\d*|(?:lrcapi|proofread):[A-Za-z0-9_-]{1,180}", value):
            return value
    return None


def source_ref(source):
    if source.startswith("NetEase https://music.163.com/song?"):
        value = parse_qs(urlparse(source.split(" ", 1)[1]).query).get("id", [""])[0]
        return recording_ref("netease:" + value)
    if source.startswith("LrcAPI https://api.lrc.cx/jsonapi?"):
        return recording_ref("lrcapi:" + urlparse(source.split(" ", 1)[1]).fragment)
    return None
