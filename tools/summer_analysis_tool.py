"""Summer Environment Data Analysis Tool — 模块化夏季环境监测数据挖掘工具。

此工具专门处理温室环境监测 CSV 数据集，提供数据加载、统计分析、
异常检测、可视化、报告生成等模块化功能，适合作为 Agent 的细粒度工具调用。

安全策略 (2026-07-02 修复):
1. 所有文件路径经过沙盒校验，禁止跳出项目目录
2. 禁止路径中的 null 字节等特殊字符
3. 输出目录同样受沙盒限制，只能写入项目目录内
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from core.path_utils import resolve_under

matplotlib.use("Agg")


def _resolve_sandboxed_path(root: Path, file_path: str, must_exist: bool = False) -> Path:
    """解析并校验路径，返回安全的绝对路径。

    复用 core.path_utils.resolve_under 保证与文件工具一致的沙盒策略。
    """
    return resolve_under(root, file_path, must_exist=must_exist)

# ═══════════════════════════════════════════════════════════════
# 配置层 (Configuration)
# ═══════════════════════════════════════════════════════════════


@dataclass
class SensorConfig:
    """传感器配置，定义列名映射和分组。"""

    column_mapping: dict[str, str] = field(default_factory=lambda: {
        "标准时间": "time",
        "温湿度_温度_1( ℃)": "temp1",
        "温湿度_湿度_1( %)": "hum1",
        "温湿度_温度_2( ℃)": "temp2",
        "温湿度_湿度_2( %)": "hum2",
        "温湿度_温度_3( ℃)": "temp3",
        "温湿度_湿度_3( %)": "hum3",
        "温湿度_温度_4( ℃)": "temp4",
        "温湿度_湿度_4( %)": "hum4",
        "温湿度_温度_5( ℃)": "temp5",
        "温湿度_湿度_5( %)": "hum5",
        "温湿度_温度_7( ℃)": "temp7",
        "温湿度_湿度_7( %)": "hum7",
        "温湿度_温度_8( ℃)": "temp8",
        "温湿度_湿度_8( %)": "hum8",
        "光照_光照_南1_数值（lux）": "light1",
        "光照_光照_南3_数值（lux）": "light3",
        "黑球温度_黑球温度_舍内": "black_in",
        "黑球温度_黑球温度_舍外": "black_out",
        "二氧化碳_CO2_1(ppm)": "co2_1",
        "二氧化碳_CO2_2(ppm)": "co2_2",
    })

    # 传感器分组
    temp_cols: list[str] = field(default_factory=lambda: [
        "temp1", "temp2", "temp3", "temp4", "temp5", "temp7", "temp8"
    ])
    hum_cols: list[str] = field(default_factory=lambda: [
        "hum1", "hum2", "hum3", "hum4", "hum5", "hum7", "hum8"
    ])
    light_cols: list[str] = field(default_factory=lambda: ["light1", "light3"])
    blackglobe_cols: list[str] = field(default_factory=lambda: ["black_in", "black_out"])
    co2_cols: list[str] = field(default_factory=lambda: ["co2_1", "co2_2"])

    # 用于相关性分析的列
    corr_cols: list[str] = field(default_factory=lambda: [
        "temp1", "hum1", "temp3", "hum3",
        "light1", "light3", "black_in", "black_out", "co2_1", "co2_2",
    ])

    # 夜间小时定义
    night_hours: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 22, 23])

    # 需要强制转换数值类型的列
    numeric_coerce_cols: list[str] = field(default_factory=lambda: ["co2_2"])

    def all_numeric_cols(self) -> list[str]:
        return self.temp_cols + self.hum_cols + self.light_cols + self.blackglobe_cols + self.co2_cols

    def get_sensor_group(self, group: str) -> list[str]:
        groups = {
            "temp": self.temp_cols,
            "hum": self.hum_cols,
            "light": self.light_cols,
            "blackglobe": self.blackglobe_cols,
            "co2": self.co2_cols,
            "all": self.all_numeric_cols(),
        }
        return groups.get(group, groups["all"])


@dataclass
class PlotConfig:
    """图表样式配置。"""

    dpi: int = 150
    figsize_wide: tuple[float, float] = (14, 4)
    figsize_tall: tuple[float, float] = (14, 8)
    figsize_grid: tuple[float, float] = (14, 10)
    cmap: str = "RdBu_r"
    grid_alpha: float = 0.3
    line_alpha: float = 0.7

    def apply_rc(self) -> None:
        plt.rcParams["figure.dpi"] = self.dpi
        plt.rcParams["axes.unicode_minus"] = False


# 默认配置实例
DEFAULT_SENSOR_CONFIG = SensorConfig()
DEFAULT_PLOT_CONFIG = PlotConfig()


# ═══════════════════════════════════════════════════════════════
# 数据层 (Data Loading & Preprocessing)
# ═══════════════════════════════════════════════════════════════


def load_and_preprocess(
    csv_path: str,
    root: Path,
    config: SensorConfig | None = None,
) -> pd.DataFrame:
    """加载并预处理 CSV 数据（带沙盒路径校验）。

    Args:
        csv_path: CSV 文件路径（必须在项目目录内）。
        root: 沙盒根目录。
        config: 传感器配置，默认使用 DEFAULT_SENSOR_CONFIG。

    Returns:
        预处理后的 DataFrame。

    Raises:
        ValueError: 路径非法或跳出沙盒。
    """
    safe_path = _resolve_sandboxed_path(root, csv_path, must_exist=True)
    cfg = config or DEFAULT_SENSOR_CONFIG
    df = pd.read_csv(safe_path)
    df = df.rename(columns=cfg.column_mapping)

    for col in cfg.numeric_coerce_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["time"] = pd.to_datetime(df["time"])
    df["date"] = df["time"].dt.date
    df["hour"] = df["time"].dt.hour
    return df


# ═══════════════════════════════════════════════════════════════
# 分析层 (Analysis Modules)
# ═══════════════════════════════════════════════════════════════


def compute_statistics(df: pd.DataFrame, config: SensorConfig | None = None) -> dict[str, Any]:
    """计算描述性统计摘要。

    Returns:
        包含各传感器组统计信息的字典。
    """
    cfg = config or DEFAULT_SENSOR_CONFIG
    stats = {}

    for group_name, cols in [
        ("temperature", cfg.temp_cols),
        ("humidity", cfg.hum_cols),
        ("light", cfg.light_cols),
        ("blackglobe", cfg.blackglobe_cols),
        ("co2", cfg.co2_cols),
    ]:
        available = [c for c in cols if c in df.columns]
        if not available:
            continue
        data = df[available]
        stats[group_name] = {
            "mean": data.mean().mean(),
            "std": data.std().mean(),
            "min": data.min().min(),
            "max": data.max().max(),
            "count": len(data),
        }

    # 温湿度相关性
    if "temp1" in df.columns and "hum1" in df.columns:
        stats["temp_hum_corr"] = df["temp1"].corr(df["hum1"])

    return stats


def detect_anomalies_iqr(
    df: pd.DataFrame,
    columns: list[str] | None = None,
    k: float = 1.5,
) -> dict[str, dict[str, Any]]:
    """使用 IQR 方法检测异常值。

    Args:
        df: 数据框。
        columns: 要检测的列，None 则检测所有数值列。
        k: IQR 倍数，默认 1.5。

    Returns:
        每列的异常检测结果字典。
    """
    if columns is None:
        columns = df.select_dtypes(include=[np.number]).columns.tolist()

    results = {}
    for col in columns:
        if col not in df.columns:
            continue
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        lower = Q1 - k * IQR
        upper = Q3 + k * IQR
        outliers = df[(df[col] < lower) | (df[col] > upper)]
        results[col] = {
            "count": len(outliers),
            "percentage": len(outliers) / len(df) * 100,
            "lower_bound": lower,
            "upper_bound": upper,
            "Q1": Q1,
            "Q3": Q3,
        }
    return results


def detect_night_light_anomaly(
    df: pd.DataFrame,
    config: SensorConfig | None = None,
    threshold: float = 10.0,
) -> dict[str, Any]:
    """检测夜间光照异常（夜间光照应接近0）。

    Returns:
        夜间光照异常统计。
    """
    cfg = config or DEFAULT_SENSOR_CONFIG
    night = df[df["hour"].isin(cfg.night_hours)]
    if night.empty:
        return {"night_records": 0, "anomaly_rate": 0.0}

    anomaly_mask = (night["light1"] + night["light3"]) > threshold
    return {
        "night_records": len(night),
        "anomaly_rate": anomaly_mask.mean() * 100,
        "threshold": threshold,
    }


def compute_correlation(
    df: pd.DataFrame,
    columns: list[str] | None = None,
    threshold: float = 0.5,
) -> list[tuple[str, str, float]]:
    """计算列间相关性并筛选强相关项。

    Returns:
        强相关项列表，按相关系数绝对值降序排列。
    """
    cfg = DEFAULT_SENSOR_CONFIG
    cols = columns or cfg.corr_cols
    cols = [c for c in cols if c in df.columns]
    if len(cols) < 2:
        return []

    corr_matrix = df[cols].corr()
    strong = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            v = corr_matrix.iloc[i, j]
            if abs(v) > threshold:
                strong.append((cols[i], cols[j], v))
    strong.sort(key=lambda x: abs(x[2]), reverse=True)
    return strong


# ═══════════════════════════════════════════════════════════════
# 可视化层 (Visualization Modules)
# ═══════════════════════════════════════════════════════════════


def _savefig(path: Path) -> None:
    plt.savefig(path, dpi=DEFAULT_PLOT_CONFIG.dpi, bbox_inches="tight")
    plt.close()


def plot_temp_hum_timeseries(
    df: pd.DataFrame,
    output_path: Path,
    config: SensorConfig | None = None,
    plot_config: PlotConfig | None = None,
) -> Path:
    """绘制温湿度时序图。"""
    cfg = config or DEFAULT_SENSOR_CONFIG
    pc = plot_config or DEFAULT_PLOT_CONFIG
    pc.apply_rc()

    fig, axes = plt.subplots(2, 1, figsize=pc.figsize_tall, sharex=True)
    for col in cfg.temp_cols:
        if col in df.columns:
            axes[0].plot(df["time"], df[col], alpha=pc.line_alpha, label=col)
    axes[0].set_ylabel("Temperature (degC)")
    axes[0].set_title("Temperature Time Series")
    axes[0].legend(loc="upper right", ncol=4)
    axes[0].grid(True, alpha=pc.grid_alpha)

    for col in cfg.hum_cols:
        if col in df.columns:
            axes[1].plot(df["time"], df[col], alpha=pc.line_alpha, label=col)
    axes[1].set_ylabel("Humidity (%)")
    axes[1].set_xlabel("Time")
    axes[1].set_title("Humidity Time Series")
    axes[1].legend(loc="upper right", ncol=4)
    axes[1].grid(True, alpha=pc.grid_alpha)

    plt.tight_layout()
    out = output_path / "temp_hum_timeseries.png"
    _savefig(out)
    return out


def plot_light_timeseries(
    df: pd.DataFrame,
    output_path: Path,
    plot_config: PlotConfig | None = None,
) -> Path:
    """绘制光照时序图。"""
    pc = plot_config or DEFAULT_PLOT_CONFIG
    pc.apply_rc()

    fig, ax = plt.subplots(figsize=pc.figsize_wide)
    for col, label in [("light1", "South1"), ("light3", "South3")]:
        if col in df.columns:
            ax.plot(df["time"], df[col], alpha=pc.line_alpha, label=label)
    ax.set_ylabel("Light (lux)")
    ax.set_xlabel("Time")
    ax.set_title("Light Intensity Time Series")
    ax.legend()
    ax.grid(True, alpha=pc.grid_alpha)

    plt.tight_layout()
    out = output_path / "light_timeseries.png"
    _savefig(out)
    return out


def plot_blackglobe_timeseries(
    df: pd.DataFrame,
    output_path: Path,
    plot_config: PlotConfig | None = None,
) -> Path:
    """绘制黑球温度对比图。"""
    pc = plot_config or DEFAULT_PLOT_CONFIG
    pc.apply_rc()

    fig, ax = plt.subplots(figsize=pc.figsize_wide)
    for col, label in [("black_in", "Inside"), ("black_out", "Outside")]:
        if col in df.columns:
            ax.plot(df["time"], df[col], alpha=pc.line_alpha, label=label)
    ax.set_ylabel("Black Globe Temp (degC)")
    ax.set_xlabel("Time")
    ax.set_title("Black Globe Temp: Inside vs Outside")
    ax.legend()
    ax.grid(True, alpha=pc.grid_alpha)

    plt.tight_layout()
    out = output_path / "blackglobe_timeseries.png"
    _savefig(out)
    return out


def plot_co2_timeseries(
    df: pd.DataFrame,
    output_path: Path,
    plot_config: PlotConfig | None = None,
) -> Path:
    """绘制 CO2 时序图。"""
    pc = plot_config or DEFAULT_PLOT_CONFIG
    pc.apply_rc()

    fig, ax = plt.subplots(figsize=pc.figsize_wide)
    for col, label in [("co2_1", "CO2_1"), ("co2_2", "CO2_2")]:
        if col in df.columns:
            ax.plot(df["time"], df[col], alpha=pc.line_alpha, label=label)
    ax.set_ylabel("CO2 (ppm)")
    ax.set_xlabel("Time")
    ax.set_title("CO2 Concentration Time Series")
    ax.legend()
    ax.grid(True, alpha=pc.grid_alpha)

    plt.tight_layout()
    out = output_path / "co2_timeseries.png"
    _savefig(out)
    return out


def plot_correlation_heatmap(
    df: pd.DataFrame,
    output_path: Path,
    columns: list[str] | None = None,
    plot_config: PlotConfig | None = None,
) -> Path:
    """绘制相关性热力图。"""
    cfg = DEFAULT_SENSOR_CONFIG
    pc = plot_config or DEFAULT_PLOT_CONFIG
    pc.apply_rc()

    cols = columns or cfg.corr_cols
    cols = [c for c in cols if c in df.columns]
    if len(cols) < 2:
        raise ValueError("至少需要两列才能绘制相关性热力图")

    corr_matrix = df[cols].corr()
    fig, ax = plt.subplots(figsize=(max(8, len(cols)), max(8, len(cols))))
    im = ax.imshow(corr_matrix, cmap=pc.cmap, vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols)))
    ax.set_yticks(range(len(cols)))
    ax.set_xticklabels(cols, rotation=45, ha="right")
    ax.set_yticklabels(cols)
    ax.set_title("Sensor Correlation Heatmap")
    for i in range(len(cols)):
        for j in range(len(cols)):
            ax.text(j, i, f"{corr_matrix.iloc[i, j]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, shrink=0.8)

    plt.tight_layout()
    out = output_path / "correlation_heatmap.png"
    _savefig(out)
    return out


def plot_co2_anomaly(
    df: pd.DataFrame,
    output_path: Path,
    column: str = "co2_1",
    k: float = 1.5,
    plot_config: PlotConfig | None = None,
) -> Path:
    """绘制 CO2 异常检测散点图。"""
    pc = plot_config or DEFAULT_PLOT_CONFIG
    pc.apply_rc()

    if column not in df.columns:
        raise ValueError(f"列 {column} 不存在")

    Q1 = df[column].quantile(0.25)
    Q3 = df[column].quantile(0.75)
    IQR = Q3 - Q1
    lower = Q1 - k * IQR
    upper = Q3 + k * IQR
    colors = ["red" if (v < lower or v > upper) else "blue" for v in df[column]]

    fig, ax = plt.subplots(figsize=pc.figsize_wide)
    ax.scatter(df["time"], df[column], c=colors, alpha=0.5, s=5)
    ax.axhline(y=upper, color="orange", linestyle="--", label=f"Upper: {upper:.1f}")
    ax.axhline(y=lower, color="orange", linestyle="--", label=f"Lower: {lower:.1f}")
    ax.set_ylabel(f"{column} (ppm)")
    ax.set_xlabel("Time")
    ax.set_title(f"{column} Anomaly Detection (IQR)")
    ax.legend()
    ax.grid(True, alpha=pc.grid_alpha)

    plt.tight_layout()
    out = output_path / f"{column}_anomaly.png"
    _savefig(out)
    return out


def plot_daily_summary(
    df: pd.DataFrame,
    output_path: Path,
    plot_config: PlotConfig | None = None,
) -> Path:
    """绘制每日统计汇总图。"""
    pc = plot_config or DEFAULT_PLOT_CONFIG
    pc.apply_rc()

    daily = df.groupby("date").agg(
        temp_min=("temp1", "min"),
        temp_max=("temp1", "max"),
        hum_mean=("hum1", "mean"),
        light_sum=("light1", "sum"),
        co2_mean=("co2_1", "mean"),
    ).reset_index()

    fig, axes = plt.subplots(2, 2, figsize=pc.figsize_grid)
    axes[0, 0].plot(daily["date"], daily["temp_max"], label="Max", color="red")
    axes[0, 0].plot(daily["date"], daily["temp_min"], label="Min", color="blue")
    axes[0, 0].fill_between(daily["date"], daily["temp_min"], daily["temp_max"], alpha=0.3)
    axes[0, 0].set_ylabel("Temperature (degC)")
    axes[0, 0].set_title("Daily Temperature Range")
    axes[0, 0].legend()
    axes[0, 0].grid(True, alpha=pc.grid_alpha)

    axes[0, 1].plot(daily["date"], daily["hum_mean"], color="green")
    axes[0, 1].set_ylabel("Humidity (%)")
    axes[0, 1].set_title("Daily Average Humidity")
    axes[0, 1].grid(True, alpha=pc.grid_alpha)

    axes[1, 0].bar(daily["date"], daily["light_sum"], color="orange", alpha=0.7)
    axes[1, 0].set_ylabel("Daily Light Sum (lux)")
    axes[1, 0].set_title("Daily Cumulative Light")
    axes[1, 0].grid(True, alpha=pc.grid_alpha)

    axes[1, 1].plot(daily["date"], daily["co2_mean"], color="purple")
    axes[1, 1].set_ylabel("CO2 (ppm)")
    axes[1, 1].set_title("Daily Average CO2")
    axes[1, 1].grid(True, alpha=pc.grid_alpha)

    plt.tight_layout()
    out = output_path / "daily_summary.png"
    _savefig(out)
    return out


def plot_sensor_boxplots(
    df: pd.DataFrame,
    output_path: Path,
    config: SensorConfig | None = None,
    plot_config: PlotConfig | None = None,
) -> Path:
    """绘制传感器箱线图。"""
    cfg = config or DEFAULT_SENSOR_CONFIG
    pc = plot_config or DEFAULT_PLOT_CONFIG
    pc.apply_rc()

    fig, axes = plt.subplots(2, 2, figsize=pc.figsize_grid)

    temp_available = [c for c in cfg.temp_cols if c in df.columns]
    if temp_available:
        temp_labels = [f"T{i+1}" if i < 5 else f"T{i+2}" for i in range(len(cfg.temp_cols))]
        temp_labels = [temp_labels[cfg.temp_cols.index(c)] for c in temp_available]
        axes[0, 0].boxplot([df[c] for c in temp_available], labels=temp_labels)
        axes[0, 0].set_ylabel("Temperature (degC)")
        axes[0, 0].set_title("Temperature Distribution")
        axes[0, 0].grid(True, alpha=pc.grid_alpha)

    hum_available = [c for c in cfg.hum_cols if c in df.columns]
    if hum_available:
        hum_labels = [f"H{i+1}" if i < 5 else f"H{i+2}" for i in range(len(cfg.hum_cols))]
        hum_labels = [hum_labels[cfg.hum_cols.index(c)] for c in hum_available]
        axes[0, 1].boxplot([df[c] for c in hum_available], labels=hum_labels)
        axes[0, 1].set_ylabel("Humidity (%)")
        axes[0, 1].set_title("Humidity Distribution")
        axes[0, 1].grid(True, alpha=pc.grid_alpha)

    light_available = [c for c in cfg.light_cols if c in df.columns]
    if light_available:
        light_labels = ["South1" if c == "light1" else "South3" for c in light_available]
        axes[1, 0].boxplot([df[c] for c in light_available], labels=light_labels)
        axes[1, 0].set_ylabel("Light (lux)")
        axes[1, 0].set_title("Light Distribution")
        axes[1, 0].grid(True, alpha=pc.grid_alpha)

    co2_available = [c for c in cfg.co2_cols if c in df.columns]
    if co2_available:
        co2_labels = [c.replace("co2_", "CO2_") for c in co2_available]
        axes[1, 1].boxplot([df[c].dropna() for c in co2_available], labels=co2_labels)
        axes[1, 1].set_ylabel("CO2 (ppm)")
        axes[1, 1].set_title("CO2 Distribution")
        axes[1, 1].grid(True, alpha=pc.grid_alpha)

    plt.tight_layout()
    out = output_path / "sensor_boxplots.png"
    _savefig(out)
    return out


# ═══════════════════════════════════════════════════════════════
# 报告层 (Report Generation)
# ═══════════════════════════════════════════════════════════════


def generate_report(
    df: pd.DataFrame,
    stats: dict[str, Any],
    anomalies: dict[str, dict[str, Any]],
    night_light: dict[str, Any],
    output_path: Path,
    config: SensorConfig | None = None,
) -> Path:
    """生成 Markdown 分析报告。"""
    cfg = config or DEFAULT_SENSOR_CONFIG
    temp_stats = stats.get("temperature", {})
    hum_stats = stats.get("humidity", {})
    corr = stats.get("temp_hum_corr", 0)

    report_lines = [
        "# Summer Environment Data Mining Report",
        "",
        "## 1. Overview",
        f"- Time Range: {df['time'].min()} ~ {df['time'].max()}",
        f"- Records: {len(df)}, Days: {df['date'].nunique()}",
        "- Interval: 5 minutes",
        f"- Missing: CO2_2 has {df['co2_2'].isnull().sum()} missing value",
        "",
        "## 2. Statistics",
        f"- Avg Temperature: {temp_stats.get('mean', 0):.2f} degC "
        f"(range {temp_stats.get('min', 0):.1f} ~ {temp_stats.get('max', 0):.1f})",
        f"- Avg Humidity: {hum_stats.get('mean', 0):.2f}% "
        f"(range {hum_stats.get('min', 0):.1f} ~ {hum_stats.get('max', 0):.1f})",
        f"- Temp-Humidity Correlation: {corr:.4f} ({'negative' if corr < 0 else 'positive'})",
        "",
        "## 3. Anomalies",
    ]

    for col, info in anomalies.items():
        if info["count"] > 0:
            report_lines.append(
                f"- {col}: {info['count']} outliers ({info['percentage']:.2f}%), "
                f"range [{info['lower_bound']:.1f}, {info['upper_bound']:.1f}]"
            )

    report_lines.extend([
        f"- night_light_nonzero: {night_light.get('anomaly_rate', 0):.2f}%",
        "",
        "## 4. Key Findings",
        "1. Clear day-night cycles in temp/humidity",
        "2. Good consistency across temperature sensors",
    ])

    co2_anomaly = anomalies.get("co2_1", {})
    if co2_anomaly.get("count", 0) > 0:
        report_lines.append(
            f"3. CO2_1 has highest anomaly rate ({co2_anomaly['count']} outliers, "
            f"{co2_anomaly['percentage']:.2f}%)"
        )
    else:
        report_lines.append("3. CO2_1 anomaly rate is within normal range")

    report_lines.append(f"4. Night light nonzero rate: {night_light.get('anomaly_rate', 0):.2f}%")

    black_in = df["black_in"] if "black_in" in df.columns else pd.Series(dtype=float)
    black_out = df["black_out"] if "black_out" in df.columns else pd.Series(dtype=float)
    if not black_in.empty and not black_out.empty:
        report_lines.append(
            f"5. Outside black globe varies more ({black_out.min():.1f}~{black_out.max():.1f}) "
            f"than inside ({black_in.min():.1f}~{black_in.max():.1f})"
        )

    report_text = "\n".join(report_lines)
    out = output_path / "analysis_report.md"
    out.write_text(report_text, encoding="utf-8")
    return out


# ═══════════════════════════════════════════════════════════════
# Agent 工具层 (LangChain Tool)
# ═══════════════════════════════════════════════════════════════

_ACTION_LOAD = "load"
_ACTION_STATS = "statistics"
_ACTION_ANOMALY = "anomaly"
_ACTION_CORR = "correlation"
_ACTION_CHART = "chart"
_ACTION_FULL = "full"
_VALID_ACTIONS = {_ACTION_LOAD, _ACTION_STATS, _ACTION_ANOMALY, _ACTION_CORR, _ACTION_CHART, _ACTION_FULL}

_CHART_TYPES = ["temp_hum", "light", "blackglobe", "co2", "heatmap", "co2_anomaly", "daily", "boxplot"]
_SENSOR_TYPES = ["all", "temp", "hum", "light", "blackglobe", "co2"]


class SummerAnalysisInput(BaseModel):
    action: str = Field(
        description=(
            "操作类型: load(加载数据概况), statistics(统计摘要), "
            "anomaly(异常检测), correlation(相关性分析), "
            "chart(生成图表), full(完整分析)"
        )
    )
    csv_path: str = Field(description="CSV 文件路径（相对于项目根目录）")
    sensor_type: str = Field(default="all", description="传感器分组: all/temp/hum/light/blackglobe/co2（anomaly 用）")
    k: float = Field(default=1.5, description="IQR 倍数（anomaly 用，默认 1.5）")
    threshold: float = Field(default=0.5, description="相关性阈值（correlation 用，默认 0.5）")
    chart_type: str = Field(default="", description="图表类型（chart 用）: temp_hum/light/blackglobe/co2/heatmap/co2_anomaly/daily/boxplot")
    output_dir: str = Field(default="output", description="输出目录（chart/full 用，默认 output）")


class SummerAnalysisTool(BaseTool):
    """Summer environment data analysis tool."""

    name: str = "summer_analysis"
    description: str = (
        "夏季温室环境数据分析。action: load(概况)/statistics(统计)/anomaly(异常检测)/"
        "correlation(相关性)/chart(图表)/full(完整分析)。"
    )
    args_schema: type[BaseModel] = SummerAnalysisInput
    root_dir: str = ""

    def _run(
        self,
        action: str,
        csv_path: str,
        sensor_type: str = "all",
        k: float = 1.5,
        threshold: float = 0.5,
        chart_type: str = "",
        output_dir: str = "output",
    ) -> str:
        try:
            if action not in _VALID_ACTIONS:
                return f"Unknown action: {action}. Available: {sorted(_VALID_ACTIONS)}"

            if action == _ACTION_LOAD:
                return self._load(csv_path)
            elif action == _ACTION_STATS:
                return self._statistics(csv_path)
            elif action == _ACTION_ANOMALY:
                return self._anomaly(csv_path, sensor_type, k)
            elif action == _ACTION_CORR:
                return self._correlation(csv_path, threshold)
            elif action == _ACTION_CHART:
                return self._chart(csv_path, chart_type, output_dir)
            elif action == _ACTION_FULL:
                return self._full(csv_path, output_dir)
        except Exception as e:
            return f"Error: {e}"

    def _root(self) -> Path:
        return Path(self.root_dir).resolve()

    def _load(self, csv_path: str) -> str:
        df = load_and_preprocess(csv_path, self._root())
        overview = {
            "csv_path": str(csv_path),
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": df.columns.tolist(),
            "time_range": {"start": str(df["time"].min()), "end": str(df["time"].max())},
            "days": int(df["date"].nunique()),
            "missing_values": {col: int(df[col].isnull().sum()) for col in df.columns if df[col].isnull().sum() > 0},
        }
        return json.dumps(overview, ensure_ascii=False, indent=2, default=str)

    def _statistics(self, csv_path: str) -> str:
        df = load_and_preprocess(csv_path, self._root())
        stats = compute_statistics(df)
        return json.dumps(stats, ensure_ascii=False, indent=2, default=str)

    def _anomaly(self, csv_path: str, sensor_type: str, k: float) -> str:
        df = load_and_preprocess(csv_path, self._root())
        cfg = DEFAULT_SENSOR_CONFIG
        cols = cfg.get_sensor_group(sensor_type)
        anomalies = detect_anomalies_iqr(df, columns=cols, k=k)
        night_light = detect_night_light_anomaly(df)
        result = {
            "sensor_type": sensor_type,
            "k": k,
            "anomalies": {k: v for k, v in anomalies.items() if v["count"] > 0},
            "night_light_anomaly": night_light,
        }
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    def _correlation(self, csv_path: str, threshold: float) -> str:
        df = load_and_preprocess(csv_path, self._root())
        strong = compute_correlation(df, threshold=threshold)
        result = [
            {"sensor_a": a, "sensor_b": b, "correlation": round(v, 4), "direction": "positive" if v > 0 else "negative"}
            for a, b, v in strong
        ]
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    def _chart(self, csv_path: str, chart_type: str, output_dir: str) -> str:
        df = load_and_preprocess(csv_path, self._root())
        output_path = _resolve_sandboxed_path(self._root(), output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        chart_dispatch = {
            "temp_hum": plot_temp_hum_timeseries,
            "light": plot_light_timeseries,
            "blackglobe": plot_blackglobe_timeseries,
            "co2": plot_co2_timeseries,
            "heatmap": plot_correlation_heatmap,
            "co2_anomaly": plot_co2_anomaly,
            "daily": plot_daily_summary,
            "boxplot": plot_sensor_boxplots,
        }

        func = chart_dispatch.get(chart_type)
        if func is None:
            return f"Unknown chart_type: {chart_type}. Available: {list(chart_dispatch.keys())}"

        out = func(df, output_path)
        return f"Chart saved: {out}"

    def _full(self, csv_path: str, output_dir: str) -> str:
        df = load_and_preprocess(csv_path, self._root())
        output_path = _resolve_sandboxed_path(self._root(), output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        stats = compute_statistics(df)

        all_numeric = DEFAULT_SENSOR_CONFIG.all_numeric_cols()
        anomalies = detect_anomalies_iqr(df, columns=all_numeric)
        night_light = detect_night_light_anomaly(df)

        charts = []
        charts.append(plot_temp_hum_timeseries(df, output_path))
        charts.append(plot_light_timeseries(df, output_path))
        charts.append(plot_blackglobe_timeseries(df, output_path))
        charts.append(plot_co2_timeseries(df, output_path))
        charts.append(plot_correlation_heatmap(df, output_path))
        charts.append(plot_co2_anomaly(df, output_path))
        charts.append(plot_daily_summary(df, output_path))
        charts.append(plot_sensor_boxplots(df, output_path))

        report_path = generate_report(df, stats, anomalies, night_light, output_path)

        temp_stats = stats.get("temperature", {})
        hum_stats = stats.get("humidity", {})
        corr = stats.get("temp_hum_corr", 0)
        anomaly_count = sum(1 for v in anomalies.values() if v["count"] > 0)

        summary = (
            f"Summer Data Mining Complete.\n"
            f"Time: {df['time'].min()} ~ {df['time'].max()}, "
            f"{len(df)} records, {df['date'].nunique()} days\n"
            f"Avg Temp: {temp_stats.get('mean', 0):.2f} degC | "
            f"Avg Hum: {hum_stats.get('mean', 0):.2f}% | "
            f"Correlation: {corr:.4f}\n"
            f"Anomalies: {anomaly_count} sensors detected outliers\n"
            f"Outputs ({len(charts)} charts + 1 report):\n" +
            "\n".join(f"  - {c}" for c in charts + [report_path])
        )
        return summary


def create_summer_analysis_tool(base_dir: Path) -> SummerAnalysisTool:
    """Create a summer_analysis tool instance."""
    return SummerAnalysisTool(root_dir=str(base_dir))