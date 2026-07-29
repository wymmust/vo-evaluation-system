from __future__ import annotations

from pathlib import Path

from setuptools import find_packages, setup


ROOT = Path(__file__).resolve().parent


def _runtime_requirements() -> list[str]:
    requirements_path = ROOT / "requirements.txt"
    if not requirements_path.exists():
        return ["numpy", "pandas", "plotly", "openpyxl"]
    requirements: list[str] = []
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "pytest":
            continue
        requirements.append(line)
    return requirements


def _package_data() -> list[str]:
    visualization_root = ROOT / "voeval" / "visualization"
    if not visualization_root.exists():
        return []
    return [
        path.relative_to(ROOT / "voeval").as_posix()
        for path in visualization_root.rglob("*")
        if path.is_file()
    ]


setup(
    name="voeval",
    version="0.1.0",
    description="SF VO/VLOC trajectory evaluation tools",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    packages=find_packages(include=["voeval", "voeval.*"]),
    python_requires=">=3.8",
    install_requires=_runtime_requirements(),
    entry_points={"console_scripts": ["voeval=voeval.__main__:main"]},
    include_package_data=True,
    package_data={"voeval": _package_data()},
)
