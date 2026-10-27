"""TEST time is a piecewise-affine function of monotonic time, not tick counts."""
class PlaybackClock:
    def __init__(self, duration_ms, now):
        self.duration = duration_ms
        self.anchor_time = now
        self.anchor_offset = 0.0
        self.speed = 1.0
        self.running = False

    def value(self, now):
        elapsed = max(0, now-self.anchor_time)*1000*self.speed if self.running else 0
        return min(self.duration, self.anchor_offset+elapsed)

    def control(self, now, running=None, speed=None):
        self.anchor_offset = self.value(now)
        self.anchor_time = now
        if running is not None:
            self.running = running
        if speed is not None:
            self.speed = speed
