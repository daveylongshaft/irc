# PR #29: Implement Stub Methods and Replace Silent Exception Passes

**Branch**: `feature/implement-stubs-fix-exceptions`
**Issue**: 161 `pass` statements in exception handlers and stub methods
**Priority**: High
**Type**: Code quality, reliability, debugging

## Problem

Silent exception handlers (`except Exception: pass`) hide errors and make debugging difficult. Stub methods that do nothing waste time during development.

**Examples**:
```python
# Silent swallowing of errors
except Exception:
    pass

# Stub methods that do nothing
def set_platform_log_dir(cls, log_dir):
    pass
```

## Categories

### 1. Silent Exception Handlers (Most Critical)
Replace `except Exception: pass` with:
- Proper error logging
- Specific exception types
- Meaningful error messages

### 2. Stub Methods
Implement or document:
- Methods that should do something
- Methods that are intentionally no-ops (add docstring)
- Methods waiting for implementation

### 3. Empty Try Blocks
Review and restructure:
- Remove if not needed
- Add proper error handling if needed
- Document intent

## Implementation Strategy

### Phase 1: Map & Categorize
- [x] Find all 161 pass statements
- [ ] Categorize by type (exception handler, stub, etc.)
- [ ] Prioritize by impact (core services vs utilities)

### Phase 2: Fix Critical Paths
Priority files:
- `csc-log/log.py` - Logging infrastructure
- `csc-platform/platform.py` - Platform initialization
- `csc-data/data/__init__.py` - Data persistence
- `csc-service/infra/*.py` - Core services

### Phase 3: Document Intentional Passes
- Add `# Intentional no-op` comments
- Document why error is caught but ignored
- Add issue links if work is pending

## Success Criteria

- [ ] All silent exception handlers replaced with proper logging
- [ ] Stub methods either implemented or clearly documented
- [ ] Test coverage for error paths
- [ ] No silent failures in core services
- [ ] Debugging now possible when issues occur

## Files Changed (Expected)

```
packages/csc-log/csc_log/log.py
packages/csc-platform/csc_platform/platform.py
packages/csc-data/csc_data/data/__init__.py
packages/csc-data/csc_data/old_data/__init__.py
packages/csc-service/csc_service/infra/*.py
packages/csc-service/csc_service/server/service.py
packages/csc-service/csc_service/server/handlers/*.py
bin/*.py
```

---

## Fixes Applied

### 1. csc-log/log.py

**Before**:
```python
except Exception:
    pass
```

**After**:
```python
except Exception as e:
    # Fallback: continue if env var lookup fails
    print(f"[WARN] Could not use CSC_LOGS_DIR env var: {e}", file=sys.stderr)
```

### 2. csc-platform/platform.py

Replace all `except OSError: pass` with proper logging:
```python
except OSError as e:
    self.log(f"Path resolution failed for {path}: {e}")
```

### 3. Service Exception Handlers

Add logging to service dispatch errors:
```python
except Exception as e:
    self.data.log(f"Service invocation failed: {e}")
    raise  # Re-raise if critical
```

---

Status: Ready for implementation
