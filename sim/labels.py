"""Labels. SIMULATED marks population output. LOCAL marks stand-in output. Never merged."""
SIMULATED = "SIMULATED"
LOCAL = "LOCAL"
LOCAL_SCRIPTED = "LOCAL-SCRIPTED"
LOCAL_MODEL = "LOCAL-MODEL"
LOCAL_FIXTURE = "LOCAL-FIXTURE"
RUNTIME = "RUNTIME"

LOCAL_FAMILY = {LOCAL, LOCAL_SCRIPTED, LOCAL_MODEL, LOCAL_FIXTURE}


def is_local(label: str) -> bool:
    return label in LOCAL_FAMILY
