"""Resolution-independent portrait profile sourced from the system contract."""
from src.scene_design import system_contract as system


def configure(bundle):
    global FRAME_WIDTH, FRAME_HEIGHT, SAFE_X, SAFE_TOP, SAFE_BOTTOM
    global SAFE_WIDTH, SAFE_HEIGHT, MIN_FONT_SIZE, PREVIEW_RESOLUTION, FINAL_RESOLUTION, FPS
    p = system.profile(system.verify(bundle))
    FRAME_WIDTH, FRAME_HEIGHT = p['frame_width'], p['frame_height']
    SAFE_WIDTH, SAFE_HEIGHT, MIN_FONT_SIZE = p['safe_width'], p['safe_height'], p['min_font_size']
    SAFE_X = p['safe_bounds'][0] + FRAME_WIDTH/2
    SAFE_BOTTOM = p['safe_bounds'][2] + FRAME_HEIGHT/2
    SAFE_TOP = FRAME_HEIGHT/2 - p['safe_bounds'][3]
    PREVIEW_RESOLUTION, FINAL_RESOLUTION = tuple(p['preview_resolution']), tuple(p['final_resolution'])
    FPS = p['fps']


configure(system.load())


def profile(bundle=None):
    p = system.profile(bundle or system.load())
    p['rule'] = ('Same scene coordinates, fonts, strokes, timing and fixed camera in both renders; '
                 'only pixel density changes. Final is rendered from approved source, never upscaled.')
    return p


def render_profile(config, final=False, bundle=None):
    p = profile(bundle)
    return dict(config, resolution=list(p['final_resolution'] if final else p['preview_resolution']),
                fps=p['fps'], frame_height=p['frame_height'])
