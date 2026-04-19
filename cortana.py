"""
Proxy entry point for compatibility with old Railway settings.
Redirects to main.py.
"""
import asyncio
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import main
    asyncio.run(main.main())
