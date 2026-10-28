"""Generate architecture PNGs locally with SVG and headless Microsoft Edge."""

import html
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

COLORS = {
    "default": ("#f6f7fb", "#59636e"),
    "analyst": ("#e3f2fd", "#1565c0"),
    "action": ("#fce4ec", "#ad1457"),
    "decision": ("#fff2cc", "#b8860b"),
    "storage": ("#e8f5e9", "#2e7d32"),
}


class SvgDiagram:
    """Small dependency-free SVG diagram builder."""

    def __init__(self, width: int, height: int, title: str):
        self.width = width
        self.height = height
        self.items = [
            f'<text x="{width / 2}" y="42" class="title">{html.escape(title)}</text>'
        ]

    def box(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        label: str,
        style: str = "default",
    ) -> None:
        """Add a labeled process box."""
        fill, stroke = COLORS[style]
        self.items.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
            f'rx="12" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
        lines = label.split("\n")
        first_y = y + height / 2 - (len(lines) - 1) * 10
        for index, line in enumerate(lines):
            self.items.append(
                f'<text x="{x + width / 2}" y="{first_y + index * 21}" '
                f'class="label">{html.escape(line)}</text>'
            )

    def arrow(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        label: str = "",
        *,
        dashed: bool = False,
    ) -> None:
        """Add a directed connector and optional caption."""
        dash = ' stroke-dasharray="7 6"' if dashed else ""
        self.items.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="arrow"{dash}/>'
        )
        if label:
            self.items.append(
                f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2 - 8}" '
                f'class="edge">{html.escape(label)}</text>'
            )

    def group(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        label: str,
        style: str = "default",
    ) -> None:
        """Add a labeled dashed boundary behind related components."""
        fill, stroke = COLORS[style]
        self.items.insert(
            1,
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
            f'rx="18" fill="{fill}" fill-opacity="0.28" stroke="{stroke}" '
            'stroke-width="2" stroke-dasharray="9 7"/>',
        )
        self.items.append(
            f'<text x="{x + 18}" y="{y + 30}" class="group">{html.escape(label)}</text>'
        )

    def render(self) -> str:
        """Return the complete SVG document."""
        body = "\n".join(self.items)
        return f"""<svg xmlns="http://www.w3.org/2000/svg"
width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}">
<defs>
  <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5"
          orient="auto"><polygon points="0 0, 10 3.5, 0 7" fill="#59636e"/></marker>
  <style>
    text {{ font-family: Segoe UI, Arial, sans-serif; fill: #20242a; }}
    .title {{ font-size: 27px; font-weight: 700; text-anchor: middle; }}
    .label {{ font-size: 16px; font-weight: 600; text-anchor: middle; dominant-baseline: middle; }}
    .edge {{ font-size: 13px; text-anchor: middle; paint-order: stroke; stroke: white; stroke-width: 5px; }}
    .group {{ font-size: 18px; font-weight: 700; }}
    .arrow {{ stroke: #59636e; stroke-width: 2; marker-end: url(#arrowhead); }}
  </style>
</defs>
<rect width="100%" height="100%" fill="white"/>
{body}
</svg>"""


def workflow_diagram() -> SvgDiagram:
    """Describe the executable LangGraph topology."""
    diagram = SvgDiagram(1500, 1180, "AI Business Pilot — LangGraph workflow")
    diagram.box(635, 70, 230, 52, "Start")
    diagram.box(610, 155, 280, 64, "Load long-term memory", "storage")
    diagram.box(600, 260, 300, 72, "Planner\nsource + action intent", "decision")
    diagram.arrow(750, 122, 750, 155)
    diagram.arrow(750, 219, 750, 260)

    analysts = [
        (150, "DuckDB analyst"),
        (610, "Linear analyst"),
        (1070, "Combined analyst"),
    ]
    for x, label in analysts:
        diagram.box(x, 405, 280, 70, label, "analyst")
        diagram.arrow(750, 332, x + 140, 405, dashed=True)

    diagram.box(610, 520, 280, 64, "Analysis complete")
    for x, _ in analysts:
        diagram.arrow(x + 140, 475, 750, 520)

    diagram.box(610, 625, 280, 72, "Action requested?", "decision")
    diagram.arrow(750, 584, 750, 625)
    diagram.box(140, 760, 280, 70, "Analysis-only path")
    diagram.box(610, 750, 280, 86, "Draft issue from findings", "action")
    diagram.arrow(610, 661, 420, 795, "no", dashed=True)
    diagram.arrow(750, 697, 750, 750, "yes", dashed=True)

    diagram.box(1050, 755, 290, 76, "Human approval interrupt", "decision")
    diagram.arrow(610, 792, 420, 795, "existing initiative", dashed=True)
    diagram.arrow(890, 792, 1050, 792, "new issue")
    diagram.box(910, 900, 260, 66, "Record rejection", "action")
    diagram.box(1210, 888, 250, 88, "Duplicate check\n+ save_issue", "action")
    diagram.arrow(1130, 831, 1040, 900, "reject", dashed=True)
    diagram.arrow(1250, 831, 1335, 888, "approve", dashed=True)
    diagram.box(1060, 1020, 280, 66, "Verify with get_issue", "action")
    diagram.arrow(1335, 976, 1200, 1020)

    diagram.box(560, 1040, 300, 70, "Reporter")
    diagram.arrow(280, 830, 610, 1040)
    diagram.arrow(910, 933, 800, 1040)
    diagram.arrow(1060, 1053, 860, 1070)
    diagram.box(170, 1050, 250, 58, "End")
    diagram.arrow(560, 1075, 420, 1079)
    return diagram


def system_diagram() -> SvgDiagram:
    """Describe service, persistence, and security boundaries."""
    diagram = SvgDiagram(1800, 1050, "AI Business Pilot — system architecture")

    # Application core and local persistence.
    diagram.box(50, 435, 210, 70, "User / terminal")
    diagram.box(340, 400, 320, 110, "LangGraph workflow\nplanner · analysts · reporter")
    diagram.box(385, 120, 230, 65, "Local Ollama model", "analyst")
    diagram.box(260, 760, 250, 65, "Thread checkpoints", "storage")
    diagram.box(550, 760, 250, 65, "Long-term memory", "storage")
    diagram.arrow(260, 470, 340, 455)
    diagram.arrow(500, 400, 500, 185)
    diagram.arrow(440, 510, 385, 760)
    diagram.arrow(560, 510, 675, 760)

    # Read-only evidence retrieval.
    diagram.box(750, 250, 260, 72, "Read-only analysts", "analyst")
    diagram.arrow(660, 425, 750, 286)

    diagram.group(1060, 65, 680, 255, "DuckDB MCP integration", "analyst")
    diagram.box(1110, 155, 210, 65, "DuckDB MCP server", "analyst")
    diagram.box(1380, 155, 190, 65, "SQLGlot guard", "decision")
    diagram.box(1610, 155, 100, 65, "DuckDB", "storage")
    diagram.arrow(1010, 275, 1110, 188)
    diagram.arrow(1320, 188, 1380, 188)
    diagram.arrow(1570, 188, 1610, 188)

    # Linear is one integration boundary with separated capabilities.
    diagram.group(1060, 365, 680, 610, "Linear MCP integration", "analyst")
    diagram.box(1120, 440, 250, 68, "Read-only capability", "analyst")
    diagram.box(1480, 610, 210, 76, "Linear workspace", "analyst")
    diagram.arrow(1010, 295, 1120, 474)
    diagram.arrow(1370, 474, 1585, 610, "retrieve")

    # Human-approved write path.
    diagram.box(730, 570, 280, 72, "Validated issue draft", "action")
    diagram.box(730, 690, 280, 82, "Explicit human\napproval", "decision")
    diagram.arrow(610, 510, 730, 606)
    diagram.arrow(870, 642, 870, 690)
    diagram.box(1120, 740, 250, 76, "Guarded action nodes", "action")
    diagram.box(1435, 790, 270, 68, "Approved write capability", "action")
    diagram.arrow(1010, 731, 1120, 778, "approved fields")
    diagram.arrow(1370, 778, 1435, 824)
    diagram.arrow(1585, 790, 1585, 686, "create + verify")

    diagram.box(730, 895, 280, 62, "Rejection: no write", "action")
    diagram.arrow(820, 772, 820, 895, "reject", dashed=True)
    return diagram


def render_png(name: str, diagram: SvgDiagram, temporary_dir: Path) -> None:
    """Render one SVG through a local headless browser."""
    svg_path = temporary_dir / f"{Path(name).stem}.svg"
    svg_path.write_text(diagram.render(), encoding="utf-8")
    destination = (ARTIFACTS_DIR / name).resolve()
    profile = temporary_dir / f"edge-{Path(name).stem}"
    command = [
        str(EDGE),
        "--headless",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--user-data-dir={profile}",
        f"--window-size={diagram.width},{diagram.height}",
        f"--screenshot={destination}",
        svg_path.resolve().as_uri(),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    if not destination.exists():
        raise RuntimeError(f"Browser did not create {destination}")
    print(f"Created {destination}")


def main() -> None:
    """Generate both architecture images without an external service."""
    if not EDGE.exists():
        raise FileNotFoundError(f"Microsoft Edge was not found at {EDGE}")
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ai-business-pilot-diagrams-") as folder:
        temporary_dir = Path(folder)
        render_png("analysis_graph.png", workflow_diagram(), temporary_dir)
        render_png("system_architecture.png", system_diagram(), temporary_dir)


if __name__ == "__main__":
    main()
