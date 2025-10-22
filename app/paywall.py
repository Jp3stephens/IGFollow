from flask import current_app


def exceeds_free_limit(count: int) -> bool:
    max_free = current_app.config.get("MAX_FREE_EXPORT", 600)
    return count > max_free
