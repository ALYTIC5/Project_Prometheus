"""Session-wide test fixtures. Values here are arbitrary test sentinels,
not production risk limits — those come from real deployment env vars.
"""
import os

# Distinct, easy-to-spot-in-a-diff values so no one mistakes these for
# real limits.
#
# Assigned unconditionally, not via setdefault: a developer with real risk
# limits exported in their shell would otherwise silently run the law tests
# against those values instead of these sentinels, and the tests would still
# pass — which is exactly the kind of "green for the wrong reason" that
# tests/laws/ exists to prevent.
os.environ["MAX_POSITION_PCT"] = "11"
os.environ["MAX_GROSS_EXPOSURE_PCT"] = "22"
os.environ["MAX_LEVERAGE"] = "3"
os.environ["MAX_DAILY_LOSS_PCT"] = "4"
os.environ["MAX_DRAWDOWN_PCT"] = "15"
os.environ["KILL_SWITCH"] = "false"
