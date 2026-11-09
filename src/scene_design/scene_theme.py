"""Resolution-independent render settings; no external execution policy."""
import copy

FRAME_WIDTH, FRAME_HEIGHT = 9.0, 16.0
SAFE_X, SAFE_TOP, SAFE_BOTTOM = .55, .55, 1.5
SAFE_WIDTH, SAFE_HEIGHT, MIN_FONT_SIZE = 7.9, 13.95, 22
PREVIEW_RESOLUTION, FINAL_RESOLUTION, FPS = (360,640), (1080,1920), 30


def profile():
    return dict(frame_width=FRAME_WIDTH,frame_height=FRAME_HEIGHT,
        safe_width=SAFE_WIDTH,safe_height=SAFE_HEIGHT,safe_bounds=[-3.95,3.95,-6.5,7.45],
        min_font_size=MIN_FONT_SIZE,preview_resolution=list(PREVIEW_RESOLUTION),
        final_resolution=list(FINAL_RESOLUTION),fps=FPS,duration_tolerance_frames=2)


def render_profile(config, final=False):
    return dict(config,resolution=list(FINAL_RESOLUTION if final else PREVIEW_RESOLUTION),
                fps=FPS,frame_height=FRAME_HEIGHT)
