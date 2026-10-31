"""Permission engine: base risk + argument context -> final RiskLevel."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from mitraa.security.sandbox import SandboxViolation, is_executable
from mitraa.tools.base import RiskLevel, Tool, ToolContext


@dataclass
class Assessment:
    level: RiskLevel
    reasons: list[str] = field(default_factory=list)
    error: str | None = None  # malformed arguments (not a policy decision)

    @property
    def needs_approval(self) -> bool:
        return self.level == RiskLevel.HIGH and self.error is None


def evaluate(tool: Tool, args: BaseModel, ctx: ToolContext) -> Assessment:
    try:
        impact = tool.impact(args, ctx)
    except SandboxViolation as exc:
        if exc.kind == "invalid":
            return Assessment(tool.base_risk, error=exc.reason)
        return Assessment(RiskLevel.BLOCKED, [exc.reason])

    if tool.mutates:
        for path in impact.paths:
            if is_executable(path):
                return Assessment(RiskLevel.BLOCKED, [f"{path.name} is an executable or script; Mitraa won't modify those."])
        for path in impact.sources:
            if ctx.sandbox.is_root(path):
                return Assessment(RiskLevel.BLOCKED, [f"{path} is a protected top-level folder."])

    level = tool.risk(args, ctx)
    reasons: list[str] = []
    if tool.name=='write_text_file' and impact.paths:
        reasons.append(f'Save to: {impact.paths[-1]}')
    if level >= RiskLevel.HIGH:
        reasons.append(f"{tool.name} always requires approval.")
    if impact.overwrites:
        level = max(level, RiskLevel.HIGH)
        names = ", ".join(p.name for p in impact.overwrites[:5])
        reasons.append(f"Would replace existing item(s): {names} (the old version goes to the Recycle Bin).")
    threshold = ctx.settings.mitraa_bulk_threshold
    if impact.count > threshold:
        level = max(level, RiskLevel.HIGH)
        reasons.append(f"Affects {impact.count} files (more than {threshold}).")
    return Assessment(level, reasons)
