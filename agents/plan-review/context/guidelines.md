# Plan Review Approval Guidelines

## CSC Coding Standards

Plans must adhere to the following CSC project conventions:

### Architecture Rules
- One class per file
- Use `Platform()` for all path construction (no hardcoded paths)
- Inherit from the correct base class: `Root -> Log -> Data -> Version -> Platform -> Network -> Service`
- New services extend `Data` and call `self.init_data()`

### Code Quality Rules
- All public methods must have docstrings
- All function signatures must include type hints and return type annotations
- Use `self.log()` instead of `print()` for output
- No bare `except:` clauses — catch specific exceptions

### Change Management Rules
- Removals or breaking changes must include a backward compatibility note
- New files should be created only when strictly necessary
- Prefer editing existing files over creating new ones

### Scope Rules
- A plan should be completable in under 2 hours of implementation
- If a plan touches more than 5 files, it may be overscoped
- Refactoring and feature work should not be combined in one plan

## Automatic DENY Triggers

Deny any plan that:
- Proposes hardcoded file system paths
- Skips docstrings or type hints across multiple new functions
- Uses `print()` for runtime output
- Has no clear success criteria
- Proposes deleting existing functionality without justification

## Automatic APPROVE Triggers

Approve plans that:
- Fix a single well-defined bug with targeted changes
- Add a new method to an existing class following existing patterns
- Update configuration or documentation files only
- Score 0 issues against all coding standard checks above
