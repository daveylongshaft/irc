import os
import re
from csc_service.server.service import Service


class patch( Service ):
    """
    Fuzzy patch service for applying code changes to service modules.

    Supports two formats:
      1. Loose anchor format (designed for IRC):
           <patch file=service_name>
           42 def old_method
           - def old_method(self):
           + def new_method(self):
           </patch>
      2. Standard unified diff (best-effort fuzzy apply)

    Commands:
      apply <filename>             - Apply a patch file from patches/ directory.
      revert <service_name> [ver]  - Revert a service file to a previous version.
      history <service_name>       - Show version history for a service file.
    """

    SEARCH_WINDOW = 10  # ±lines to search for anchor text

    def __init__(self, server_instance):
        super().__init__( server_instance )
        self.name = "patch"
        self.init_data()

        self.project_root = str( self.server.project_root_dir )
        self.patches_dir = os.path.abspath( os.path.join( self.project_root, "patches" ) )
        self.services_dir = os.path.abspath( os.path.join( self.project_root, "services" ) )
        os.makedirs( self.patches_dir, exist_ok=True )

        self.log( f"Patch service initialized. Patches dir: {self.patches_dir}" )

    # ------------------------------------------------------------------
    # Core: fuzzy anchor matcher
    # ------------------------------------------------------------------

    @staticmethod
    def _find_anchor(lines, line_hint, text_fragment):
        """Find a line containing text_fragment near line_hint.

        Args:
            lines: list of file lines (strings)
            line_hint: 0-based line index hint
            text_fragment: substring to search for

        Returns:
            0-based line index, or None if not found.
        """
        fragment = text_fragment.strip()
        if not fragment:
            return None

        # Try exact hint first
        if 0 <= line_hint < len( lines ):
            if fragment in lines[line_hint]:
                return line_hint

        # Search ±1..SEARCH_WINDOW
        for offset in range( 1, patch.SEARCH_WINDOW + 1 ):
            for candidate in (line_hint - offset, line_hint + offset):
                if 0 <= candidate < len( lines ):
                    if fragment in lines[candidate]:
                        return candidate

        return None

    # ------------------------------------------------------------------
    # Loose-format parser
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_loose_patch(content):
        """Parse loose anchor-format patch content.

        Returns list of dicts:
          [{
            "file": "service_name",
            "anchor_line": int (0-based),
            "anchor_text": str,
            "removes": [str, ...],   # lines to remove (without leading -)
            "adds": [str, ...],      # lines to insert (without leading +)
          }, ...]
        """
        hunks = []
        current_file = None
        current_hunk = None

        for raw_line in content.splitlines():
            line = raw_line

            # Detect <patch file=...>
            m = re.match( r'<patch\s+file=(["\']?)(\S+?)\1\s*>', line.strip() )
            if m:
                current_file = m.group( 2 )
                current_hunk = None
                continue

            # Detect </patch>
            if line.strip() == '</patch>':
                current_file = None
                current_hunk = None
                continue

            if current_file is None:
                continue

            # Anchor line: starts with number + space + text
            anchor_match = re.match( r'^(\d+)\s+(.+)$', line )
            if anchor_match and not line.startswith( '-' ) and not line.startswith( '+' ):
                # Save any previous hunk
                current_hunk = {
                    "file": current_file,
                    "anchor_line": int( anchor_match.group( 1 ) ) - 1,  # convert to 0-based
                    "anchor_text": anchor_match.group( 2 ),
                    "removes": [],
                    "adds": [],
                }
                hunks.append( current_hunk )
                continue

            # Remove line
            if line.startswith( '-' ) and current_hunk is not None:
                # Strip the leading '- ' or '-'
                text = line[1:]
                if text.startswith( ' ' ):
                    text = text[1:]
                current_hunk["removes"].append( text )
                continue

            # Add line
            if line.startswith( '+' ) and current_hunk is not None:
                text = line[1:]
                if text.startswith( ' ' ):
                    text = text[1:]
                current_hunk["adds"].append( text )
                continue

        return hunks

    # ------------------------------------------------------------------
    # Hunk applier
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_hunks(lines, hunks):
        """Apply parsed hunks to a list of lines.

        Args:
            lines: list of file lines (with newlines)
            hunks: list of hunk dicts from _parse_loose_patch

        Returns:
            (modified_lines, report_str)
        """
        result = list( lines )
        offset = 0
        applied = 0
        skipped = 0
        details = []

        for hunk in hunks:
            anchor_idx = patch._find_anchor(
                result,
                hunk["anchor_line"] + offset,
                hunk["anchor_text"]
            )

            if anchor_idx is None:
                skipped += 1
                details.append( f"  SKIP: anchor '{hunk['anchor_text']}' not found near line {hunk['anchor_line'] + 1}" )
                continue

            # Verify and remove '-' lines starting at anchor
            remove_count = len( hunk["removes"] )
            remove_ok = True
            if remove_count > 0:
                for i, rm_text in enumerate( hunk["removes"] ):
                    check_idx = anchor_idx + i
                    if check_idx >= len( result ):
                        remove_ok = False
                        break
                    if rm_text.strip() not in result[check_idx]:
                        # Fuzzy: try stripped comparison
                        if rm_text.strip() != result[check_idx].strip():
                            remove_ok = False
                            break

                if remove_ok:
                    del result[anchor_idx:anchor_idx + remove_count]
                else:
                    skipped += 1
                    details.append(
                        f"  SKIP: remove lines don't match at anchor line {anchor_idx + 1} "
                        f"for '{hunk['anchor_text']}'"
                    )
                    continue

            # Insert '+' lines at anchor position
            insert_pos = anchor_idx
            for i, add_text in enumerate( hunk["adds"] ):
                # Ensure line ends with newline
                if not add_text.endswith( '\n' ):
                    add_text += '\n'
                result.insert( insert_pos + i, add_text )

            net = len( hunk["adds"] ) - remove_count
            offset += net
            applied += 1
            details.append( f"  OK: applied at line {anchor_idx + 1} ({'+' if net >= 0 else ''}{net} lines)" )

        report = f"Applied {applied}/{applied + skipped} hunks, {skipped} skipped"
        if details:
            report += "\n" + "\n".join( details )

        return result, report

    # ------------------------------------------------------------------
    # Unified diff fallback (fuzzy)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_unified_diff(content):
        """Parse unified diff into hunks using fuzzy anchor matching.

        Returns list of dicts:
          [{
            "file": "target_path",
            "anchor_line": int (0-based),
            "anchor_text": str (first context line),
            "removes": [str, ...],
            "adds": [str, ...],
          }, ...]
        """
        hunks = []
        lines = content.splitlines()
        current_file = None
        i = 0

        while i < len( lines ):
            # File header
            if lines[i].startswith( '--- ' ):
                if i + 1 < len( lines ) and lines[i + 1].startswith( '+++ ' ):
                    raw = lines[i + 1][4:].split( '\t' )[0].strip()
                    if raw.startswith( 'b/' ):
                        raw = raw[2:]
                    current_file = raw
                    i += 2
                    continue
            i += 1

        # Second pass: extract hunks
        i = 0
        current_file = None
        while i < len( lines ):
            if lines[i].startswith( '--- ' ):
                if i + 1 < len( lines ) and lines[i + 1].startswith( '+++ ' ):
                    raw = lines[i + 1][4:].split( '\t' )[0].strip()
                    if raw.startswith( 'b/' ):
                        raw = raw[2:]
                    current_file = raw
                    i += 2
                    continue

            if lines[i].startswith( '@@ ' ) and current_file:
                # Parse @@ -start,count +start,count @@
                m = re.match( r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', lines[i] )
                old_start = int( m.group( 1 ) ) - 1 if m else 0
                i += 1

                # Collect hunk body
                removes = []
                adds = []
                first_context = None
                context_offset = 0

                while i < len( lines ):
                    ln = lines[i]
                    if ln.startswith( '--- ' ) or ln.startswith( '+++ ' ) or ln.startswith( '@@ ' ):
                        break
                    if ln.startswith( ' ' ):
                        if first_context is None and not removes and not adds:
                            first_context = ln[1:]
                            context_offset += 1
                        elif removes or adds:
                            # Context after changes — end of this change block
                            # Save what we have and start fresh
                            if removes or adds:
                                anchor_text = first_context if first_context else (removes[0] if removes else "")
                                hunks.append({
                                    "file": current_file,
                                    "anchor_line": old_start + context_offset,
                                    "anchor_text": anchor_text.strip(),
                                    "removes": removes,
                                    "adds": adds,
                                })
                                old_start += context_offset + len( removes )
                                context_offset = 1
                                removes = []
                                adds = []
                                first_context = ln[1:]
                        else:
                            context_offset += 1
                    elif ln.startswith( '-' ):
                        if first_context is None:
                            first_context = ln[1:]
                        removes.append( ln[1:] )
                    elif ln.startswith( '+' ):
                        adds.append( ln[1:] )
                    elif ln.startswith( '\\' ):
                        pass  # "No newline at end of file"
                    else:
                        break
                    i += 1

                # Save remaining hunk
                if removes or adds:
                    anchor_text = first_context if first_context else (removes[0] if removes else "")
                    hunks.append({
                        "file": current_file,
                        "anchor_line": old_start + context_offset,
                        "anchor_text": anchor_text.strip(),
                        "removes": removes,
                        "adds": adds,
                    })
                continue

            i += 1

        return hunks

    # ------------------------------------------------------------------
    # Format detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_format(content):
        """Detect patch format. Returns 'loose', 'unified', or None."""
        stripped = content.strip()
        if '<patch ' in stripped and '</patch>' in stripped:
            return 'loose'
        if stripped.startswith( '--- ' ) or '\n--- ' in stripped:
            return 'unified'
        return None

    # ------------------------------------------------------------------
    # Resolve service file path
    # ------------------------------------------------------------------

    def _resolve_service_path(self, service_name):
        """Convert a service name to its file path.

        Accepts:
          - bare name: "builtin" -> services/builtin_service.py
          - name with _service suffix: "builtin_service" -> services/builtin_service.py
          - relative path: "services/builtin_service.py" -> as-is under project root
        """
        if service_name.endswith( '.py' ):
            return os.path.join( self.project_root, service_name )
        name = service_name
        if not name.endswith( '_service' ):
            name = name + '_service'
        return os.path.join( self.services_dir, name + '.py' )

    # ------------------------------------------------------------------
    # Service commands
    # ------------------------------------------------------------------

    def apply(self, patch_filename: str) -> str:
        """Version target files and apply a patch from patches/ directory."""
        patch_path = os.path.join( self.patches_dir, patch_filename )
        if not os.path.exists( patch_path ):
            return f"Error: Patch file not found: {patch_path}"

        try:
            with open( patch_path, 'r', encoding='utf-8' ) as f:
                content = f.read()
        except Exception as e:
            return f"Error reading patch file: {e}"

        return self._apply_content( content )

    def _apply_content(self, content):
        """Apply patch content (auto-detect format)."""
        fmt = self._detect_format( content )
        if fmt is None:
            return "Error: Unrecognized patch format. Expected <patch file=...> or unified diff."

        if fmt == 'loose':
            hunks = self._parse_loose_patch( content )
        else:
            hunks = self._parse_unified_diff( content )

        if not hunks:
            return "Error: No hunks found in patch content."

        # Group hunks by target file
        files = {}
        for h in hunks:
            files.setdefault( h["file"], [] ).append( h )

        reports = []
        for target_name, file_hunks in files.items():
            filepath = self._resolve_service_path( target_name )

            if not os.path.exists( filepath ):
                reports.append( f"{target_name}: Error — file not found ({filepath})" )
                continue

            # Version before modifying
            try:
                version_num = self.server.create_new_version( filepath )
                self.log( f"Versioned {filepath} as v{version_num}" )
            except Exception as e:
                self.log( f"Warning: could not version {filepath}: {e}" )

            # Read file
            with open( filepath, 'r', encoding='utf-8', errors='replace' ) as f:
                file_lines = f.readlines()

            # Apply
            modified, report = self._apply_hunks( file_lines, file_hunks )

            # Write back
            with open( filepath, 'w', encoding='utf-8', newline='' ) as f:
                f.writelines( modified )

            reports.append( f"{target_name}: {report}" )
            self.log( f"Patch applied to {filepath}: {report.splitlines()[0]}" )

        # Record history
        history = self.get_data( "patch_history" ) or {}
        for target_name in files:
            fp = self._resolve_service_path( target_name )
            if fp not in history:
                history[fp] = []
            history[fp].append( f"inline ({fmt})" )
        self.put_data( "patch_history", history )

        return "\n".join( reports )

    def revert(self, service_name: str, version: str = "latest") -> str:
        """Revert a service file to a previous version."""
        filepath = self._resolve_service_path( service_name )

        if not os.path.exists( filepath ) and version == "latest":
            return f"Error: File not found: {filepath}"

        result = self.server.restore_version( filepath, version )
        if result is None:
            return f"Error: Failed to revert '{service_name}' to version '{version}'."

        self.log( f"Reverted {filepath} to version {result}" )
        return f"Reverted '{service_name}' to version {result}."

    def history(self, service_name: str) -> str:
        """Show version/patch history for a service file."""
        filepath = self._resolve_service_path( service_name )

        # Patch history from our data store
        patch_hist = self.get_data( "patch_history" ) or {}
        patches_applied = patch_hist.get( filepath, [] )

        # Version history from server
        version_info_str = ""
        try:
            file_backup_dir = self.server.get_version_dir_for_file( filepath )
            version_info = self.server._get_version_info( file_backup_dir )
            ver_history = version_info.get( "history", {} )
            if ver_history:
                version_info_str = f"\n  Versions: {', '.join( 'v' + k for k in sorted( ver_history.keys(), key=int ) )}"
                version_info_str += f"\n  Active: v{version_info.get( 'active', '?' )}"
        except Exception:
            pass

        if not patches_applied and not version_info_str:
            return f"No history found for '{service_name}'."

        response = f"--- History for {service_name} ---"
        if patches_applied:
            response += "\n  Patches applied:"
            for i, p in enumerate( patches_applied ):
                response += f"\n    {i + 1}. {p}"
        if version_info_str:
            response += version_info_str

        return response

    def default(self, *args) -> str:
        """Show help and patch format examples."""
        return (
            "Patch Service — fuzzy line-anchored patcher\n"
            "Commands:\n"
            f"  apply <filename>            - Apply patch from {self.patches_dir}\n"
            "  revert <service> [version]  - Revert a service file.\n"
            "  history <service>           - Show patch/version history.\n"
            "\n"
            "Loose patch format:\n"
            "  <patch file=service_name>\n"
            "  42 def old_method\n"
            "  - def old_method(self):\n"
            "  + def new_method(self):\n"
            "  </patch>\n"
            "\n"
            "Rules:\n"
            "  - file= targets services/<name>_service.py\n"
            "  - Anchor: line_number + space + text fragment\n"
            "  - Number is a hint; searches ±10 lines for the text\n"
            "  - Lines starting with - are removed, + are inserted\n"
            "  - Also accepts standard unified diff format"
        )
