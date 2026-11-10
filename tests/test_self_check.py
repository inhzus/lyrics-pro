from lyrics_pro.self_check import self_check


def test_offline_packaging_self_check_has_real_dictionaries_and_metadata():
    result = self_check()
    assert result["ok"]
    assert result["packages"]["ToJyutping"] == "3.2.0"
    assert result["packages"]["taibun"] == "1.1.8"
    assert "missing" not in str(result["annotation_versions"])
