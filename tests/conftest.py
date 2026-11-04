"""全局测试配置。"""

from __future__ import annotations

import os

# 测试默认不向 Langfuse 上报：observability 在 import 时读取开关、装饰器在 import 时绑定，
# 所以必须在任何 icecode 模块被导入之前设置，fixture 太晚。
# 需要真实 SDK 的用例自行 monkeypatch.delenv("ICECODE_ENABLE_LANGFUSE") 并 reload observability。
os.environ["ICECODE_ENABLE_LANGFUSE"] = "false"
