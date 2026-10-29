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


def test_method_text_follows_config(tmp_path):
    from s2forest.config import Config, TimeConfig
    from s2forest.report import method_lines

    cfg = Config(run_name="x", aoi=tmp_path / "a.geojson", time=TimeConfig(monitor_year=2026))
    text = " ".join(method_lines(cfg))
    assert "harmonisks" in text and "±30" not in text and "OSM ceļiem" in text
    cfg.anomaly.baseline_method = "window"
    cfg.linear_features.enabled = False
    text = " ".join(method_lines(cfg))
    assert "±30 dienu logā" in text and "harmonisks" not in text and "ceļu maska izslēgta" in text


def test_monthly_availability_mixed_datetime_formats():
    # STAC times with and without fractional seconds in one table (2020 scenes)
    acq = pd.DataFrame({
        "datetime": ["2019-05-02 09:30:41.024000+00:00", "2020-07-13 09:44:34+00:00",
                     "2020-07-18T09:40:31Z"],
        "status": ["accepted", "accepted", "rejected"],
    })
    a = monthly_availability(acq).set_index(["year", "month"])
    assert a.loc[(2019, 5), "accepted"] == 1
    assert a.loc[(2020, 7), "total"] == 2 and a.loc[(2020, 7), "accepted"] == 1
