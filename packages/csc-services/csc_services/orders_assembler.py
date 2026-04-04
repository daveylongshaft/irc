"""OrdersAssembler: Reads orders.md-template and resolves @include directives."""

import logging
from pathlib import Path

log = logging.getLogger(__name__)


class OrdersAssembler:
    """Reads orders.md-template and resolves @include directives into final orders.md.

    Template format:
        @include role://_shared/README.md
        @include role://<role>/*.md
        @include file://irc/docs/tools/INDEX.txt
        @include wip://<workorder_filename>
        Literal text with <placeholder> substitution

    Directive schemes:
        role://   -> ops/roles/<path>
        file://   -> relative to project root
        wip://    -> ops/wo/wip/<path>, wrapped in ## TASK header

    Placeholders resolved at assembly time:
        <role>, <agent>, <agent_name>, <workorder_filename>,
        <wip_file_rel_path>, <wip_file_abs_path>

    Placeholders left for queue-worker at spawn time:
        <clone_rel_path>, <agent_repo_rel_path>
    """

    def __init__(self, project_root):
        self.project_root = Path(project_root)

    def assemble(self, agent_name, workorder_filename, role="worker", template_path=None):
        """Read template, resolve all @include directives, return assembled string."""
        if template_path is None:
            template_path = self._find_template(agent_name)

        if not template_path.exists():
            log.warning("Template not found: %s", template_path)
            return ""

        template = template_path.read_text(encoding='utf-8', errors='replace')
        wip_rel = f"ops/wo/wip/{workorder_filename}"
        wip_abs = str(self.project_root / "ops" / "wo" / "wip" / workorder_filename)

        placeholders = {
            "<role>": role,
            "<agent>": agent_name,
            "<agent_name>": agent_name,
            "<workorder_filename>": workorder_filename,
            "<wip_file_rel_path>": wip_rel,
            "<wip_file_abs_path>": wip_abs,
        }

        parts = []
        for line in template.splitlines():
            stripped = line.strip()
            if stripped.startswith("@include "):
                uri = stripped[len("@include "):]
                uri = self._substitute(uri, placeholders)
                content = self._resolve_include(uri, agent_name, role, workorder_filename)
                if content:
                    parts.append(content)
            else:
                parts.append(self._substitute(line, placeholders))

        return "\n".join(parts).replace('\0', '')

    def _find_template(self, agent_name):
        """Find template: agent-specific first, then global fallback."""
        agents_dir = self.project_root / "ops" / "agents"
        agent_template = agents_dir / agent_name / "orders.md-template"
        if agent_template.exists():
            return agent_template
        return agents_dir / "templates" / "orders.md-template"

    def _resolve_include(self, uri, agent_name, role, workorder_filename):
        """Resolve an @include URI to file content."""
        if uri.startswith("role://"):
            path_part = uri[len("role://"):]
            base = self.project_root / "ops" / "roles"
            return self._read_glob(base, path_part)

        elif uri.startswith("file://"):
            path_part = uri[len("file://"):]
            full = self.project_root / path_part
            return self._read_file(full)

        elif uri.startswith("wip://"):
            path_part = uri[len("wip://"):]
            full = self.project_root / "ops" / "wo" / "wip" / path_part
            content = self._read_file(full)
            if content:
                return f"## TASK: {path_part}\n\n{content}"
            return ""

        else:
            log.warning("Unknown @include scheme: %s", uri)
            return ""

    def _read_glob(self, base, pattern):
        """Expand glob pattern, sort results (README.md first), concatenate."""
        full_pattern = base / pattern
        parent = full_pattern.parent
        glob_part = full_pattern.name

        if not parent.exists():
            return ""

        if "*" in glob_part:
            files = sorted(parent.glob(glob_part))
        else:
            target = parent / glob_part
            files = [target] if target.exists() else []

        if not files:
            return ""

        parts = []
        readme_files = [f for f in files if f.name == "README.md"]
        other_files = [f for f in files if f.name != "README.md"]

        for f in readme_files + other_files:
            if f.is_file():
                content = self._read_file(f)
                if content:
                    parts.append(content)

        return "\n\n".join(parts)

    def _read_file(self, path):
        """Read a single file, return content or empty string."""
        try:
            if path.exists() and path.is_file():
                return path.read_text(encoding='utf-8', errors='replace').rstrip()
        except Exception as e:
            log.warning("Failed to read %s: %s", path, e)
        return ""

    def _substitute(self, text, placeholders):
        """Replace placeholder tags in text."""
        for key, value in placeholders.items():
            text = text.replace(key, value)
        return text

    @staticmethod
    def extract_role(wip_path):
        """Read role from workorder YAML front-matter. Default: 'worker'."""
        try:
            text = Path(wip_path).read_text(encoding='utf-8', errors='replace')
            if text.startswith('---'):
                end = text.find('---', 3)
                if end > 0:
                    for line in text[3:end].splitlines():
                        if line.strip().startswith('role:'):
                            return line.split(':', 1)[1].strip()
        except Exception:
            import logging
            logging.getLogger(__name__).debug('Ignored exception', exc_info=True)
        return 'worker'
