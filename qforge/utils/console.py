"""
Console utilities for QForge - enables beautiful Unicode output on Windows.
"""

import sys
import os


def enable_unicode_console():
    """
    Enable UTF-8 encoding for beautiful Unicode output on Windows.
    
    This fixes the 'charmap' codec errors that prevent Unicode characters
    like ✓, π, μ, α from displaying in Windows PowerShell.
    """
    # Force UTF-8 for stdout and stderr
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            # Python < 3.7
            import codecs
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    
    if sys.stderr.encoding != 'utf-8':
        try:
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            import codecs
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    
    # On Windows, set the console code page to UTF-8
    if sys.platform == 'win32':
        try:
            import ctypes
            # Set console output code page to UTF-8 (65001)
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except:
            pass
    
    # Set environment variable for subprocess compatibility
    os.environ['PYTHONIOENCODING'] = 'utf-8'


def print_unicode(*args, **kwargs):
    """
    Print with Unicode support, falling back to ASCII if needed.
    
    This is a safety wrapper that handles encoding errors gracefully.
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        # Fallback: strip problematic characters
        safe_args = []
        for arg in args:
            if isinstance(arg, str):
                # Replace common Unicode with ASCII equivalents
                safe_str = arg.replace('✓', '[OK]').replace('•', '-')
                safe_str = safe_str.replace('π', 'pi').replace('μ', 'u')
                safe_str = safe_str.replace('α', 'alpha').replace('ω', 'w')
                safe_str = safe_str.replace('⟩', '>').replace('⟨', '<')
                safe_args.append(safe_str)
            else:
                safe_args.append(arg)
        print(*safe_args, **kwargs)
