"""COM initialization for background/request-handling threads.

docx2pdf drives MS Word via win32com, which requires CoInitialize() on
whichever OS thread calls it. The CLI never needed this — main.py always runs
_save_resume on the process's single main thread, where pywin32 initializes
COM implicitly. The web backend calls _save_resume from spawned worker threads
and from FastAPI's sync-route threadpool, neither of which is the main thread,
so PDF conversion silently fails with 'CoInitialize has not been called'
unless each thread initializes COM itself first.
"""
import sys
from contextlib import contextmanager


@contextmanager
def com_initialized():
    if sys.platform != "win32":
        yield
        return
    import pythoncom
    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()
