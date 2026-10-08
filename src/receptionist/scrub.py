"""Remove account identifiers and emails from ElevenLabs API payloads before saving them to the repo."""

import re

DROP = {"ran_by_user_email", "workspace_id", "user_id", "system__user_id", "user_identifier",
        "authorization_method", "branch_id", "version_id"}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def scrub(o):
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items() if k not in DROP}
    if isinstance(o, list):
        return [scrub(x) for x in o]
    if isinstance(o, str):
        return EMAIL.sub("[email removed]", o)
    return o
