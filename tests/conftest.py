"""Session-wide test fixtures. Values here are arbitrary test sentinels,
not production risk limits — those come from real deployment env vars.
"""
import os

# Distinct, easy-to-spot-in-a-diff values so no one mistakes these for
# real limits.
os.environ.setdefault("MAX_POSITION_PCT", "11")
os.environ.setdefault("MAX_GROSS_EXPOSURE_PCT", "22")
os.environ.setdefault("MAX_LEVERAGE", "3")
os.environ.setdefault("MAX_DAILY_LOSS_PCT", "4")
os.environ.setdefault("MAX_DRAWDOWN_PCT", "15")
os.environ.setdefault("KILL_SWITCH", "false")
