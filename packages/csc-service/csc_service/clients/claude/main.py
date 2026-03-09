"""Entry point for the CSC Claude application.

- What it does: Initializes the application environment and runs Claude.
- What it calls: Claude class from csc_claude.claude module.
"""
import sys
import os

_claude_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_claude_dir)

_parent = os.path.dirname(_claude_dir)
# Prioritize local packages over system packages - but keep dependencies
if _parent in sys.path:
    sys.path.remove(_parent)
sys.path.insert(0, _parent)

def main():
    """Initialize and run Claude.

    - What it does: Instantiates the Claude class and runs it.
    - What calls it: The __main__ block.
    - What it calls: Claude().run().
    """
    # Import from local packages (sys.path already prioritizes /opt/csc/packages)
    from claude import Claude
    Claude().run()

if __name__ == "__main__":
    main()
