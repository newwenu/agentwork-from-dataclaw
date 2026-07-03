"""Core Tools factory — returns all tools for the Agent."""

from pathlib import Path
from typing import List, Union

from langchain_core.tools import BaseTool

from .python_repl_tool import create_python_repl_tool
from .read_file_tool import (
    create_file_info_tool,
    create_read_file_tool,
    create_read_skill_tool,
)
from .summer_analysis_tool import (
    summer_detect_anomalies,
    summer_generate_chart,
    summer_get_correlation,
    summer_get_statistics,
    summer_load_data,
    summer_run_full_analysis,
)
from .terminal_tool import create_terminal_tool
from .write_memory_tool import create_write_memory_tool


def get_all_tools(base_dir: Union[Path, str]) -> List[BaseTool]:
    """Create and return all tools, sandboxed to base_dir."""
    base_dir = Path(base_dir) if isinstance(base_dir, str) else base_dir
    memory_dir = base_dir / "memory"
    skills_dir = base_dir / "skills"
    return [
        create_terminal_tool(base_dir),
        create_python_repl_tool(),
        create_file_info_tool(base_dir),
        create_read_file_tool(base_dir),
        create_read_skill_tool(skills_dir),
        create_write_memory_tool(memory_dir),
        # Summer environment analysis tools
        summer_load_data,
        summer_get_statistics,
        summer_detect_anomalies,
        summer_get_correlation,
        summer_generate_chart,
        summer_run_full_analysis,
    ]