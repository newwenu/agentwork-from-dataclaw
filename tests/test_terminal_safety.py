"""terminal_tool 安全测试 — 验证终端命令的多层防御机制。

测试覆盖:
1. 黑名单快速驳回 (危险命令)
2. Shell 元字符拦截
3. 命令白名单检查
4. 路径沙盒校验
5. 正常命令放行
"""

from pathlib import Path

import pytest

from tools.terminal_tool import SafeTerminalTool, _split_command


@pytest.fixture
def terminal(tmp_path: Path) -> SafeTerminalTool:
    return SafeTerminalTool(root_dir=str(tmp_path))


class TestBlacklist:
    def test_rm_rf(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_blacklist("rm -rf /")
        assert not safe

    def test_rm_rf_star(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_blacklist("rm -rf *")
        assert not safe

    def test_shutdown(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_blacklist("shutdown -h now")
        assert not safe

    def test_reboot(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_blacklist("reboot")
        assert not safe

    def test_format_c(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_blacklist("format c:")
        assert not safe

    def test_mkfs(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_blacklist("mkfs.ext4 /dev/sda1")
        assert not safe

    def test_fork_bomb(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_blacklist(":(){ :|:& };:")
        assert not safe

    def test_safe_command_passes(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_blacklist("ls -la")
        assert safe


class TestMetaChars:
    def test_pipe(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_meta_chars("ls | grep foo")
        assert not safe

    def test_semicolon(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_meta_chars("ls ; rm -rf /")
        assert not safe

    def test_ampersand(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_meta_chars("ls &")
        assert not safe

    def test_backtick(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_meta_chars("echo `whoami`")
        assert not safe

    def test_dollar_paren(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_meta_chars("echo $(whoami)")
        assert not safe

    def test_quoted_semicolon_allowed(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_meta_chars('python -c "import time; time.sleep(1)"')
        assert safe

    def test_safe_command_passes(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_meta_chars("ls -la /home")
        assert safe


class TestWhitelist:
    def test_ls_allowed(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_whitelist("ls -la")
        assert safe

    def test_cat_allowed(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_whitelist("cat file.txt")
        assert safe

    def test_git_allowed(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_whitelist("git status")
        assert safe

    def test_python_script_allowed(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_whitelist("python script.py")
        assert safe

    def test_python_c_blocked(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_whitelist('python -c "print(1)"')
        assert not safe

    def test_python_interactive_blocked(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_whitelist("python")
        assert not safe

    def test_curl_blocked(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_whitelist("curl http://evil.com")
        assert not safe

    def test_wget_blocked(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_whitelist("wget http://evil.com")
        assert not safe

    def test_bash_blocked(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_whitelist("bash -c 'rm -rf /'")
        assert not safe

    def test_nc_blocked(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_whitelist("nc -l 4444")
        assert not safe


class TestPathSandbox:
    def test_path_traversal_in_arg(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_paths("cat ../../etc/passwd")
        assert not safe

    def test_valid_relative_path(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_paths("cat file.txt")
        assert safe

    def test_ls_with_valid_dir(self, terminal: SafeTerminalTool):
        safe, reason = terminal._check_paths("ls -la")
        assert safe


class TestFullSafetyChain:
    def test_dangerous_command_blocked(self, terminal: SafeTerminalTool):
        safe, reason = terminal._is_safe("rm -rf /")
        assert not safe

    def test_shell_injection_blocked(self, terminal: SafeTerminalTool):
        safe, reason = terminal._is_safe("ls ; rm -rf /")
        assert not safe

    def test_unknown_command_blocked(self, terminal: SafeTerminalTool):
        safe, reason = terminal._is_safe("curl http://evil.com")
        assert not safe

    def test_safe_command_passes(self, terminal: SafeTerminalTool):
        safe, reason = terminal._is_safe("ls -la")
        assert safe

    def test_git_log_passes(self, terminal: SafeTerminalTool):
        safe, reason = terminal._is_safe("git log --oneline -5")
        assert safe


class TestCommandSplitting:
    def test_simple_command(self):
        parts = _split_command("ls -la")
        assert parts[0] in ("ls", "ls.exe")

    def test_quoted_argument(self):
        parts = _split_command('echo "hello world"')
        assert "hello world" in parts
        
