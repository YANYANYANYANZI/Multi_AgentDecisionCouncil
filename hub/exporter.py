from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hub.models import BrainstormSession


def sanitize_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in ("-", "_") else "_" for char in value.strip())
    return safe.strip("_") or "brainstorm_session"


def export_session_markdown(session: BrainstormSession, summary: dict[str, str]) -> Path:
    export_dir = Path(session.export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_name = sanitize_filename(session.project_name or "brainstorm_session")
    export_path = export_dir / f"{timestamp}_{project_name}.md"

    lines: list[str] = [
        f"# {session.project_name or 'Brainstorm Session'}",
        "",
        f"- 导出时间: {datetime.now().isoformat(timespec='seconds')}",
        f"- 总轮数: {len(session.rounds)}",
        "",
        "## 详细方案",
        "",
        summary["markdown"],
        "",
        "## Mermaid 架构图",
        "",
        "```mermaid",
        summary["mermaid"],
        "```",
        "",
        "## 对话记录",
        "",
    ]

    for idx, round_record in enumerate(session.rounds, start=1):
        lines.append(f"### 第 {idx} 轮")
        lines.append("")
        lines.append("**你**")
        lines.append("")
        lines.append(round_record.user_input)
        lines.append("")
        for reply in round_record.replies:
            lines.append(f"**{reply.agent_name}**")
            lines.append("")
            lines.append(f"- 致命漏洞: {reply.critical_flaw}")
            lines.append(f"- 核心破局点: {reply.key_pivot}")
            for item in reply.reasoning_summary:
                lines.append(f"- 推理摘要: {item}")
            for item in reply.actionable_blueprint:
                lines.append(f"- 可执行蓝图: {item}")
            lines.append("")

    export_path.write_text("\n".join(lines), encoding="utf-8")
    return export_path
