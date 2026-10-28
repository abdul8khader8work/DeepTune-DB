"""Logging setup with credential redaction."""

import logging
import re

_DSN_PATTERN = re.compile(r"(postgres(?:ql)?://)[^@\s]+@")
_PASSWORD_PATTERN = re.compile(r"(password=)[^\s&]+", re.IGNORECASE)


def redact(text: str) -> str:
    text = _DSN_PATTERN.sub(r"\1***@", text)
    return _PASSWORD_PATTERN.sub(r"\1***", text)


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(
                redact(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("uvicorn.access").addFilter(RedactionFilter())
