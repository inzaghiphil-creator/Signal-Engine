"""Signal Engine — Python backtester.

Faithful port of the Pine Script signal model (see docs/SIGNAL_SPEC.md):
same indicators, same weighted scoring, same gates, same trade management
order (STOP → TARGET → REVERSAL → TREND FLIP → new entry).
"""

__version__ = "2.1.0"
