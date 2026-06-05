'''
Structured debug observability for the jsonsubschema pipeline.

Failure events (log_failure) are emitted by default to stderr at WARNING level.
Full pipeline tracing requires config.set_debug(True) — silent otherwise.
Two output formats: "human" (default) or "json".

To suppress failure output:
    import logging
    logging.getLogger("jsonsubschema.pipeline").setLevel(logging.ERROR)
'''

import json
import logging
import sys


_logger = logging.getLogger("jsonsubschema.pipeline")
_logger.propagate = False

_handler: logging.Handler = None       # debug handler (installed by enable_debug)
_warn_handler: logging.Handler = None  # default failure handler (always present unless debug active)


class _HumanFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "fields", {})
        parts = []
        for k, v in fields.items():
            if isinstance(v, (dict, list)):
                try:
                    v_str = json.dumps(v, default=str, allow_nan=True)
                except Exception:
                    v_str = repr(v)
            else:
                v_str = str(v)
            parts.append(f"{k}={v_str}")
        suffix = "  " + "  ".join(parts) if parts else ""
        return f"[jsonsubschema] {record.getMessage():<22}{suffix}"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "fields", {})
        payload = {"event": record.getMessage()}
        payload.update(fields)
        try:
            return json.dumps(payload, default=str, allow_nan=True)
        except Exception:
            return json.dumps({"event": record.getMessage(), "fields": repr(fields)})


def _install_warn_handler() -> None:
    global _warn_handler
    if _warn_handler is None:
        _warn_handler = logging.StreamHandler(sys.stderr)
        _warn_handler.setFormatter(_HumanFormatter())
        _logger.addHandler(_warn_handler)
    _logger.setLevel(logging.WARNING)


_install_warn_handler()  # active at module import — failure events always visible


def enable_debug(fmt: str = "human") -> None:
    global _handler, _warn_handler
    if _handler:
        return
    # Remove default handler to avoid double-printing failures during debug mode
    if _warn_handler:
        _logger.removeHandler(_warn_handler)
        _warn_handler = None
    _handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        _handler.setFormatter(_JsonFormatter())
    else:
        _handler.setFormatter(_HumanFormatter())
    _logger.setLevel(logging.DEBUG)
    _logger.addHandler(_handler)


def disable_debug() -> None:
    global _handler
    if _handler:
        _logger.removeHandler(_handler)
        _handler = None
    _install_warn_handler()  # reinstall default failure handler


def log_event(event: str, **fields) -> None:
    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug(event, extra={"fields": fields})


def log_failure(event: str, **fields) -> None:
    _logger.warning(event, extra={"fields": fields})
