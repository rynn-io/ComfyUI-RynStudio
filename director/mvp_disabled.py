"""No-op compatibility hooks for upstream features excluded from the R2V MVP.

The retained upstream executor references these extension points. This release keeps
the proven base R2V path while making every excluded branch unreachable.
"""


def selflift_enabled(_plan):
    return False


def selflift_will_run(_plan, _segment=None):
    return False


def sample_selflift_stage(*_args, **_kwargs):
    raise RuntimeError("SelfLift is outside the Ryn H3 Director MVP")


def confirm_first_pass_enabled(_plan):
    return False


def first_pass_sigmas_override(sigmas):
    return sigmas


def refine_needs_canvas(_pack):
    return False


def refine_passes_for(_pack):
    return 1


def refine_will_sample(_plan, _segment=None):
    return False


def apply_segment_refine(*_args, **_kwargs):
    raise RuntimeError("Refine is outside the Ryn H3 Director MVP")


def face_refine_enabled(_plan):
    return False


def apply_semantic_bridge(positive, _plan, *, task_key=""):
    del task_key
    return positive, None
