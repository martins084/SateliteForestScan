import pandas as pd

from s2forest.viz import monthly_availability


def test_monthly_availability_uses_analysis_times():
    acq = pd.DataFrame({
        "datetime": ["2026-05-02T09:40:00Z", "2026-05-12T09:40:00Z", "2026-06-01T09:40:00Z",
                     "2026-06-11T09:40:00Z"],
        "status": ["accepted", "accepted", "rejected", "accepted"],
    })
    a = monthly_availability(acq).set_index("month")
    assert a.loc[5, "accepted"] == 2 and a.loc[5, "total"] == 2 and a.loc[6, "accepted"] == 1
    # the May 12 scene was dropped by the haze test -> not in the analysis times
    u = monthly_availability(acq, pd.to_datetime(["2026-05-02 09:40", "2026-06-11 09:40"]))
    u = u.set_index("month")
    assert u.loc[5, "accepted"] == 1 and u.loc[5, "total"] == 2 and u.loc[6, "accepted"] == 1
