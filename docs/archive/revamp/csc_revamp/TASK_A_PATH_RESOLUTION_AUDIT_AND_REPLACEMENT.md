# TASK A: Path Resolution Audit & Replacement via Platform() Object

**Assigned To**: ChatGPT (or agent without command execution)
**Effort**: 2-3 hours
**Outcome**: All hardcoded paths in `/csc/irc/` replaced with Platform-resolved paths

---

## Objective

Audit `irc/*` and related code for hardcoded paths like `/c/csc/workorders` and `/c/csc/agents`, then systematically replace them with **Platform-resolved paths using `os.sep`** so paths work correctly across systems and directory structures.

**Key Principle**: Use `Platform()` object from `csc_service.shared.platform` to resolve all paths dynamically, not hardcoded strings. see csc/irc/tools/INDEX.txt for code map and insight.  Platform() writes platform.json, you may examine it but use the methods of the object to build paths as different os and fs will be differ paths as well.  extend Platform() as needed to provide any needed system specific data.

---

## PHASE 1: Audit - Find All Hardcoded Paths

### Step 1.1: Search for Hardcoded Path Patterns

Filter the entire codebase with tools like grep and identify ALL instances of:
- Absolute paths like `/c/csc/workorders`, `/c/csc/agents`, `C:\csc\workorders`
- Relative path constructions like `Path(__file__).parent.parent`
- String concatenations with path separators like `"workorders"` or `"agents"`

**Files to audit (minimum):**
- `irc/* ` all files in the codebase.  
- `bin/*` check these scripts especially.  
-     some of the scripts may no longer be relevant,  if so move them to bin/depreciated/ - 
-     ALL paths need to be resolved properly based on the OS and FS type.  
-     platform() should resolve this, if not please make it do so when it inits and save the properly formed 
-     path strings to its platform.json file as well as the correct dir seperator character and the project root and temp
-     dir path which should now be /tmp in the csc project root, however it should not be versioned so add entire tmp 
-     tree to git ignore as well.

**For each path string found, note:**
If it is resolved using the platform() objects properties or methods verify it will resolve to a logical reasonable path and if so assume its correct and go to next.  if it is not platform() resolved:
1. File path
2. Line number
3. Current path string (exact text)
4. Current path value (what it resolves to)
And then convert it to platform() path. Note you must adapt the path to the new dir structure as well as resolve it from the platform() module.  if the platform module provides the irc/ops prefix the rest of the path would be the same between repo versions so check how its done but make sure when complete that all paths exist in the new repo structure.

NOTE:  the Log() object for log file is initialized before the platform object so it must use a default value until the log file path can be set after the platform object is available.  a workaround there to read the platform.json file directly if it exists is permitted however it must not crash if no platform.json is available.  default to log.log in project root (no path)


### Step 1.2: Audit Result Format

Create a spreadsheet or table in this document with columns:
| File | Line | Current Code | Issue | Replacement Needed |
|------|------|--------------|-------|-------------------|
| agent_service.py | 33 | `PROJECT_ROOT / "workorders"` | Should be `ops/wo` not `workorders` | `PROJECT_ROOT / "ops" / "wo"` |
| ... | ... | ... | ... | ... |

---

Replace as you go.  One pass and be done with it if you can.

Understanding the Platform object is critical. Use the tools\ dir but here is a quickstart:

The `Platform()` class (in `csc_service.shared.platform`) provides:
- `Platform().PROJECT_ROOT` - Base directory (will be `/c/csc/` after swap)
- `Platform().get_abs_root_path([components])` - Return absolute path from PROJECT_ROOT
- `Platform().get_abs_tmp_path([components])` - Return absolute path from TMP directory
- `Platform().store_path(name, type, [components])` - Store a path reference
- `Platform().load_path(name)` - Retrieve a stored path reference
- `Platform().has_tool()` - Check for tools
- `os.sep` - Proper path separator (/ on Unix, \\ on Windows)

**Pattern to use (preferred methods):**
```python
from csc_service.shared.platform import Platform

platform = Platform()

# Get absolute paths for common directories
workorders_dir = platform.get_abs_root_path(['ops', 'wo'])
agents_dir = platform.get_abs_root_path(['ops', 'agents'])
logs_dir = platform.get_abs_root_path(['logs'])
tmp_dir = platform.get_abs_tmp_path([])

# Store paths for later retrieval
platform.store_path('wo_ready', 'root', ['ops', 'wo', 'ready'])
platform.store_path('agent_work', 'tmp', ['agent-123', 'work'])

# Retrieve stored paths
ready_path = platform.load_path('wo_ready')
```

**Alternative (still valid):**
```python
from pathlib import Path
from csc_service.shared.platform import Platform

platform = Platform()
workorders_dir = Path(platform.PROJECT_ROOT) / "ops" / "wo"
agents_dir = Path(platform.PROJECT_ROOT) / "ops" / "agents"
```

**NOT:**
```python
workorders_dir = "/c/csc/workorders"  # WRONG - hardcoded
workorders_dir = "C:\\csc\\workorders"  # WRONG - hardcoded for Windows
```

### Step 2.2: Replacement Rules

**For every hardcoded path found:**

1. **If it references `/c/csc/workorders` or `/c/csc/ops/wo`**:
   - Replace with: `platform.get_abs_root_path(['ops', 'wo'])`
   - Or: `Path(Platform().PROJECT_ROOT) / "ops" / "wo"`
   - Reason: Workorders moved to `ops/wo/` in new structure

2. **If it references `/c/csc/agents` or `/c/csc/ops/agents`**:
   - Replace with: `platform.get_abs_root_path(['ops', 'agents'])`
   - Or: `Path(Platform().PROJECT_ROOT) / "ops" / "agents"`
   - Reason: Agents moved to `ops/agents/` in new structure

3. **If it references `/c/csc/logs` or `logs` directory**:
   - Replace with: `platform.get_abs_root_path(['logs'])`
   - Reason: Logs now at project root in `logs/` directory

4. **If it references temporary files**:
   - Replace with: `platform.get_abs_tmp_path(['your', 'temp', 'subdir'])`
   - Reason: All temp files should go to `tmp/` directory at project root

5. **If it uses relative path like `Path(__file__).parent.parent`**:
   - Calculate from new location (likely need 3 levels up now: `file` → `module` → `package` → `irc` → root)
   - Or replace with: `Path(Platform().PROJECT_ROOT)`
   - Reason: Files moved to `irc/` subdirectory, parent calculations change

6. **If it's in a config file (JSON, YAML, TOML)**:
   - Replace literal paths with placeholders like `${PROJECT_ROOT}/ops/wo`
   - Document placeholder substitution logic

7. **If it's a script or batch file**:
   - Use environment variables exported by `platform.export_env_paths()`
   - Available env vars: `$CSC_ROOT`, `$CSC_OPS_WO`, `$CSC_LOGS`, `$CSC_TMP`, `$CSC_DOCS`, `$CSC_DOCS_TOOLS`, `$CSC_BIN`
   - Example (bash): `cd "$CSC_OPS_WO/ready"`
   - Example (batch): `cd %CSC_OPS_WO%\ready`

5. **Always use `Path()` and `/` operator, never string concatenation with `os.sep`**:
   - Good: `Path(root) / "ops" / "wo"`
   - Bad: `root + os.sep + "ops" + os.sep + "wo"`

---

## PHASE 3: Implementation

### Step 3.1: For Each File in Audit Results

**Read** the file completely and understand its context.

**Identify** all instances of the hardcoded path.

**Replace** with the Platform-resolved equivalent:
- Add import if needed: `from csc_service.shared.platform import Platform`
- Create Platform instance if not exists: `platform = Platform()`
- Replace path: `old_path = "/c/csc/workorders"` → `path = Path(platform.PROJECT_ROOT) / "ops" / "wo"`

**Verify** the replacement:
- The new code should work regardless of installation location
- It should work if `/c/csc_new` is renamed to `/c/csc` (or any other location)
- Use `Path()` semantics, not string manipulation

### Step 3.2: Special Case - bin/agent Script

If `bin/agent` has path calculations:
- **Old logic**: `Path(__file__).parent.parent` (assumes: bin/ → root)
- **New logic**: Likely `Path(__file__).parent.parent.parent` (bin/ → irc/ → root)
- **Better**: Replace with `Path(Platform().PROJECT_ROOT)`

### Step 3.3: Special Case - CLAUDE.md

**Find** all path examples in CLAUDE.md:
- `/c/csc/workorders` → `/c/csc/ops/wo`
- `/c/csc/agents` → `/c/csc/ops/agents`
- `/opt/csc/` → `/c/csc/` (Windows location)

**Update** examples to reflect new paths.

---

## PHASE 4: Verification

### Step 4.1: For Each Replacement Made

**Verify** the code passes these checks:
1. **Import check**: All new imports (`Platform`, `Path`, `os`) exist and are correct
2. **Logic check**: Path construction is correct (`Path() / "dir"`, not string concat)
3. **Semantics check**: Path resolves to correct location after swap
   - When `/c/csc_new/irc` becomes `/c/csc/irc`, paths should still work
   - Platform().PROJECT_ROOT should resolve to `/c/csc/` after swap
4. **No hardcoded check**: No remaining literal `/c/csc/`, `C:\csc`, or `/opt/csc` strings (except in comments/docs)

### Step 4.2: Verification Report

Create a final report:
```
TASK A COMPLETION CHECKLIST:

[ ] All hardcoded paths audited (list count: ___ files, ___ instances)
[ ] All instances logged in audit table above
[ ] Replacements use Platform().PROJECT_ROOT
[ ] Replacements use Path() and / operator
[ ] All imports added (Platform, Path, os where needed)
[ ] No remaining hardcoded paths found on re-audit
[ ] CLAUDE.md examples updated
[ ] Code logic verified for post-swap locations
[ ] Cross-system compatibility verified (works from any location)

Files Modified: ___
Replacements Made: ___
Imports Added: ___
Status: [ ] READY FOR PHASE 4 INSTALL
```

---

## DELIVERABLES

1. **Updated Code Files**: All Python files with paths replaced
2. **Updated CLAUDE.md**: Examples reflect new paths
3. **Audit Table**: (Above) Complete list of all changes
4. **Verification Report**: (Above) Confirmation checklist
5. **Summary**: Brief note of what was changed and why

---

## CRITICAL NOTES

- **NO command execution tools** - just read and edit files
- **Platform() resolution, not hardcoding** - every path must be dynamic
- **os.sep and Path() semantics** - use modern Python path handling
- **Cross-system compatibility** - code must work on Windows, Linux, macOS
- **Post-swap verification** - all paths must resolve correctly when `/c/csc_new` → `/c/csc`

---

## SUCCESS CRITERIA

✅ All hardcoded paths replaced with Platform-resolved paths
✅ Code works regardless of installation directory
✅ No remaining hardcoded `/c/csc`, `C:\csc`, or `/opt/csc` literals (except comments)
✅ All imports correct and available
✅ Verification report complete and passing all checks
✅ Ready for Phase 4 package installation
