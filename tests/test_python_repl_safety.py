"""python_repl_tool 安全测试 — 验证代码黑名单的拦截能力。

测试覆盖:
1. 危险 import 拦截 (os, subprocess, sys, socket)
2. 危险函数拦截 (eval, exec, open)
3. 代码长度限制
4. 正常代码放行
"""

import pytest

from tools.python_repl_tool import GuardedPythonREPLTool


@pytest.fixture
def repl() -> GuardedPythonREPLTool:
    return GuardedPythonREPLTool()


class TestDangerousImports:
    def test_import_os(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("import os")
        assert not safe
        assert "os" in reason.lower() or "Forbidden" in reason

    def test_import_subprocess(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("import subprocess")
        assert not safe

    def test_import_sys(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("import sys")
        assert not safe

    def test_import_socket(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("import socket")
        assert not safe

    def test_import_requests(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("import requests")
        assert not safe

    def test_from_os_import(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("from os import system")
        assert not safe

    def test_from_subprocess_import(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("from subprocess import run")
        assert not safe

    def test_dunder_import(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("__import__('os')")
        assert not safe


class TestDangerousFunctions:
    def test_eval(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("eval('1+1')")
        assert not safe

    def test_exec(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("exec('print(1)')")
        assert not safe

    def test_compile(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("compile('1+1', '<string>', 'eval')")
        assert not safe

    def test_open_write(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("open('file.txt', 'w')")
        assert not safe

    def test_open_read(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("open('file.txt', 'r')")
        assert not safe

    def test_os_system(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("os.system('ls')")
        assert not safe

    def test_os_remove(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("os.remove('file.txt')")
        assert not safe

    def test_subprocess_call(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("subprocess.call(['ls'])")
        assert not safe


class TestCodeLengthLimit:
    def test_oversized_code(self, repl: GuardedPythonREPLTool):
        long_code = "x = 1\n" * 2000
        safe, reason = repl._check_code(long_code)
        assert not safe
        assert "length" in reason.lower() or "exceeds" in reason.lower()


class TestSafeCode:
    def test_simple_print(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("print('hello')")
        assert safe

    def test_math_calculation(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("result = sum(range(100))")
        assert safe

    def test_pandas_operation(self, repl: GuardedPythonREPLTool):
        code = "import pandas as pd\ndf = pd.DataFrame({'a': [1,2,3]})\ndf.mean()"
        safe, reason = repl._check_code(code)
        assert safe

    def test_numpy_operation(self, repl: GuardedPythonREPLTool):
        code = "import numpy as np\narr = np.array([1,2,3])\narr.sum()"
        safe, reason = repl._check_code(code)
        assert safe

    def test_matplotlib_savefig(self, repl: GuardedPythonREPLTool):
        code = (
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1,2,3])\n"
            "plt.savefig('output.png')"
        )
        safe, reason = repl._check_code(code)
        assert safe


class TestBypassAttempts:
    def test_string_concat_import(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("__import__('o' + 's')")
        assert not safe

    def test_importlib_abuse(self, repl: GuardedPythonREPLTool):
        safe, reason = repl._check_code("import importlib")
        assert safe

    def test_base64_encoded_payload(self, repl: GuardedPythonREPLTool):
        code = "import base64; exec(base64.b64decode('aW1wb3J0IG9z'))"
        safe, reason = repl._check_code(code)
        assert not safe
