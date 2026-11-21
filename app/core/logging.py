"""日志：统一格式，禁止输出密钥。"""

import logging
import sys

_CONFIGURED = False


class _SecretFilter(logging.Filter):
    """兜底：即使某处不小心打印了 token，也在日志落地前抹掉。"""

    PATTERNS = ("AAH", "sk-", "Bearer ")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        for p in self.PATTERNS:
            if p in msg:
                record.msg = msg.replace(p, "***")
                record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(_SecretFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    _CONFIGURED = True
