from bisect import bisect_right

from .models import Lyrics


class Follower:
    """Select the current line, without replaying lines skipped by a seek."""

    def __init__(self, lyrics: Lyrics):
        self.lyrics = lyrics
        self.times = [line.time for line in lyrics.lines] if lyrics.synced else []
        self.previous = None
        self.printed_plain = False

    def update(self, position: float):
        if not self.lyrics.synced:
            if self.printed_plain:
                return ()
            self.printed_plain = True
            return self.lyrics.lines
        index = bisect_right(self.times, position) - 1
        if index == self.previous:
            return ()
        self.previous = index
        if index < 0:
            return ()
        return (self.lyrics.lines[index],)
