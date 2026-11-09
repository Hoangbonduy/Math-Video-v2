"""One cumulative, nearest-frame clock for Cairo animations and frozen waits."""
import math


def frame_at(seconds, fps):
    """Nearest frame, with half-frame ties toward the later frame."""
    return math.floor(float(seconds) * float(fps) + .5 + 1e-9)


class FrameClock:
    def __init__(self, scene, fps):
        self.scene, self.fps = scene, float(fps)
        self.durations = []
        self.frames = 0

    @property
    def requested_time(self):
        return math.fsum(self.durations)

    def allocate(self, duration):
        self.durations.append(float(duration))
        end = frame_at(self.requested_time, self.fps)
        count = max(0, end - self.frames)
        self.frames += count
        return count

    def install(self):
        # Install after telemetry so its frozen-span count sees the exact grid
        # duration. Animated samples retain Manim's start-inclusive convention;
        # finish() supplies the endpoint at the next segment's first frame.
        original_freeze = self.scene.renderer.freeze_current_frame
        def freeze(duration):
            count = self.allocate(duration)
            if count:
                original_freeze(math.nextafter(count / self.fps, math.inf))
        self.scene.renderer.freeze_current_frame = freeze

        def progression(run_time, description, n_iterations=None, override_skip_animations=False):
            from tqdm import tqdm
            count = self.allocate(run_time)
            return tqdm((i * run_time / count for i in range(count)),
                        total=count, desc=description, disable=True)
        self.scene.get_time_progression = progression
        self.scene.frame_clock = self
