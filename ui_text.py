"""Small direction helpers for Persian text in Tk on Windows."""
import re


PERSIAN = re.compile(r'[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufefc]')
WINDOWS_PATH = re.compile(r'(?:[A-Za-z]:[\\/]|\\\\)')


def display(text):
    """Isolate Persian text as a right-to-left run without changing its letters."""
    value = str(text)
    if not PERSIAN.search(value):
        return value
    return '\u202b' + value + '\u202c'


def display_log(text):
    """Isolate ordinary messages but preserve full filesystem paths as typed."""
    value = str(text)
    return value if WINDOWS_PATH.search(value) else display(value)
