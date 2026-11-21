"""pytest 全局配置：使用独立临时数据库，绝不碰真实数据。"""

import os
import pathlib
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="zhiwei-test-"))

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:TEST-TOKEN-SHOULD-NOT-LEAK"
os.environ["TELEGRAM_USER_ID"] = "123456789"
os.environ["LLM_PROVIDER"] = "ollama"
