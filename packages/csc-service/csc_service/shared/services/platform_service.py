"""Platform Service - System inventory and capability queries.

Exposes platform detection data to the IRC command system so AI agents
and humans can query system capabilities.

Commands (via IRC):
    AI do platform info          - Full system inventory
    AI do platform capabilities  - List available tools/features
    AI do platform can <tool>    - Check if a specific tool is available
    AI do platform hardware      - Hardware details
    AI do platform docker        - Docker status details
    AI do platform agents        - AI agent availability
    AI do platform refresh       - Re-detect and refresh platform data
"""

from csc_service.server.service import Service
from csc_service.shared.platform import Platform


class platform(Service):
    """Service for querying platform capabilities from IRC."""

    def __init__(self, server_instance):
        super().__init__(server_instance)
        self.name = "platform"

    def _load(self):
        """Load current platform data from disk."""
        return Platform.load_platform_json()

    def info(self, *args) -> str:
        """Full system inventory."""
        data = self._load()
        if not data:
            return "No platform data available. Server may need restart."

        hw = data.get("hardware", {})
        os_info = data.get("os", {})
        virt = data.get("virtualization", {})
        geo = data.get("geography", {})
        docker = data.get("docker", {})
        assessment = data.get("resource_assessment", {})

        lines = [
            "=== Platform Info ===",
            f"  Detected: {data.get('detected_at', '?')}",
            "",
            "  Hardware:",
            f"    Architecture: {hw.get('architecture', '?')}",
            f"    CPU cores: {hw.get('cpu_cores', '?')}",
            f"    RAM: {hw.get('ram_total_mb', '?')} MB total, {hw.get('ram_available_mb', '?')} MB available",
            f"    Disk: {hw.get('disk_total_gb', '?')} GB total, {hw.get('disk_free_gb', '?')} GB free",
            "",
            "  OS:",
            f"    System: {os_info.get('system', '?')} {os_info.get('release', '')}",
            f"    Distribution: {os_info.get('distribution', 'N/A')}",
            f"    Python: {os_info.get('python_version', '?')}",
            "",
            f"  Virtualization: {virt.get('type', '?')}",
            f"  Timezone: {geo.get('timezone', '?')} ({geo.get('utc_offset', '?')})",
            "",
            f"  Docker: {'usable' if docker.get('usable') else 'not available'}",
            f"  Resource level: {assessment.get('resource_level', '?')}",
        ]
        return "\n".join(lines)

    def capabilities(self, *args) -> str:
        """List available tools and features."""
        data = self._load()
        if not data:
            return "No platform data available."

        software = data.get("software", {})
        agents = data.get("ai_agents", {})
        docker = data.get("docker", {})

        lines = ["=== Available Capabilities ==="]

        # Installed tools
        installed = [name for name, info in software.items() if info.get("installed")]
        if installed:
            lines.append(f"  Tools: {', '.join(sorted(installed))}")
        else:
            lines.append("  Tools: none detected")

        # AI agents
        ai_installed = [name for name, info in agents.items() if info.get("installed")]
        if ai_installed:
            lines.append(f"  AI agents: {', '.join(sorted(ai_installed))}")
        else:
            lines.append("  AI agents: none detected")

        # Docker
        if docker.get("usable"):
            lines.append(f"  Docker: yes ({docker.get('version', 'unknown version')})")
        elif docker.get("installed"):
            lines.append("  Docker: installed but daemon not running")
        else:
            lines.append("  Docker: not installed")

        return "\n".join(lines)

    def can(self, tool_name: str = "", *args) -> str:
        """Check if a specific tool is available.

        Usage: platform can <tool>
        """
        if not tool_name:
            return "Usage: platform can <tool_name>"

        tool = tool_name.lower().strip()
        data = self._load()
        if not data:
            return "No platform data available."

        # Check Docker specifically
        if tool == "docker":
            docker = data.get("docker", {})
            if docker.get("usable"):
                return f"docker: YES — {docker.get('version', 'installed')}, daemon running"
            elif docker.get("installed"):
                return "docker: NO — installed but daemon not running"
            else:
                return "docker: NO — not installed"

        # Check software tools
        software = data.get("software", {})
        if tool in software:
            info = software[tool]
            if info.get("installed"):
                return f"{tool}: YES — {info.get('version', 'installed')}"
            else:
                return f"{tool}: NO — not installed"

        # Check AI agents
        agents = data.get("ai_agents", {})
        if tool in agents:
            info = agents[tool]
            if info.get("installed"):
                return f"{tool}: YES — path: {info.get('path', '?')}"
            else:
                return f"{tool}: NO — not installed"

        return f"{tool}: UNKNOWN — not in detection inventory"

    def hardware(self, *args) -> str:
        """Show hardware details."""
        data = self._load()
        if not data:
            return "No platform data available."

        hw = data.get("hardware", {})
        lines = [
            "=== Hardware ===",
            f"  Architecture: {hw.get('architecture', '?')}",
            f"  Processor: {hw.get('processor', '?')}",
            f"  CPU cores: {hw.get('cpu_cores', '?')}",
            f"  RAM total: {hw.get('ram_total_mb', '?')} MB",
            f"  RAM available: {hw.get('ram_available_mb', '?')} MB",
            f"  Disk total: {hw.get('disk_total_gb', '?')} GB",
            f"  Disk free: {hw.get('disk_free_gb', '?')} GB",
        ]
        return "\n".join(lines)

    def docker(self, *args) -> str:
        """Show Docker status details."""
        data = self._load()
        if not data:
            return "No platform data available."

        d = data.get("docker", {})
        lines = [
            "=== Docker ===",
            f"  Installed: {d.get('installed', False)}",
            f"  Daemon running: {d.get('daemon_running', False)}",
            f"  Usable: {d.get('usable', False)}",
            f"  Version: {d.get('version', 'N/A')}",
        ]
        if d.get("daemon_running"):
            lines.extend([
                f"  Running containers: {d.get('containers_running', '?')}",
                f"  Images: {d.get('images', '?')}",
                f"  Memory: {d.get('memory_mb', '?')} MB",
            ])
        return "\n".join(lines)

    def agents(self, *args) -> str:
        """Show AI agent availability."""
        data = self._load()
        if not data:
            return "No platform data available."

        agents = data.get("ai_agents", {})
        lines = ["=== AI Agents ==="]
        for name, info in sorted(agents.items()):
            status = "installed" if info.get("installed") else "not found"
            path = info.get("path", "")
            if path:
                lines.append(f"  {name}: {status} ({path})")
            else:
                lines.append(f"  {name}: {status}")
        return "\n".join(lines)

    def refresh(self, *args) -> str:
        """Re-detect and refresh platform data."""
        try:
            p = Platform()
            p.refresh_platform()
            return "Platform data refreshed. Use 'platform info' to view."
        except Exception as e:
            return f"Error refreshing platform data: {e}"

    def default(self, *args) -> str:
        """Show available commands."""
        return (
            "Platform Service — System Capability Queries:\n"
            "  info           - Full system inventory\n"
            "  capabilities   - List available tools/features\n"
            "  can <tool>     - Check if a tool is available\n"
            "  hardware       - Hardware details\n"
            "  docker         - Docker status\n"
            "  agents         - AI agent availability\n"
            "  refresh        - Re-detect platform capabilities"
        )
