"""The sanctions index covers the US lists beyond the SDN.

The rows are excerpts of OpenSanctions targets.simple.csv for us_sanctions and us_fcc_covered_list (2026-11-20).
"""

from __future__ import annotations

from types import SimpleNamespace

from services.sanctions import ofac

US_SANCTIONS = (
    "id,schema,name,aliases,countries,program_ids,dataset,first_seen,last_seen\n"
    'NK-HYQpJVFfjnrATqKwpZpit7,Company,"Hangzhou Hikvision Digital Technology Co., Ltd.",'
    "Hangzhou Hikvision Digital Technology;Hangzhou Hikvision Digital Technology Company;Hikvision,cn,"
    "US-BIS-EL;US-DOD-1260H;US-MCCAIN-889;US-NS-CMIC,US DoD Chinese military companies;"
    "US OFAC Consolidated (non-SDN) List;US Special Legislative Exclusions;US Trade Consolidated Screening List (CSL),"
    "2023-04-20T10:56:14,2026-11-20T16:38:40\n"
    'NK-3TTjCXsbmB97w8Wh2kQD86,Company,"New Guomai Digital Culture Co., Ltd.",,,US-DOD-1260H,'
    "US DoD Chinese military companies,2026-06-09T15:38:03,2026-11-19T15:39:23\n"
    "NK-2HEWK3M5JNGwq9guVB46DJ,Company,Huyanghe Huafu Hongsheng Cotton Industry Co. Ltd.,,cn,US-UFLPA,"
    "US UFLPA Entity List,2025-01-14T21:57:03,2026-11-20T12:57:06\n"
)
FCC_COVERED = (
    "id,schema,name,aliases,countries,program_ids,dataset,first_seen,last_seen\n"
    "NK-HYQpJVFfjnrATqKwpZpit7,Company,Hangzhou Hikvision Digital Technology Company,,,US-FCC,US FCC Covered List,"
    "2024-04-22T00:00:00,2026-11-19T18:06:05\n"
    "NK-ccz32tYQsygbihggXDWSfd,Company,China Mobile International USA Inc,,,US-FCC,US FCC Covered List,"
    "2024-04-22T00:00:00,2026-11-19T18:06:05\n"
)


def test_index_keeps_lists_outside_the_sdn():
    index = ofac.build_index([US_SANCTIONS, FCC_COVERED])
    names = {e.name for e in index["entries"]}
    # 1260H, UFLPA and an FCC Covered List company that is on no other US list
    assert "New Guomai Digital Culture Co., Ltd." in names
    assert "Huyanghe Huafu Hongsheng Cotton Industry Co. Ltd." in names
    assert "China Mobile International USA Inc" in names


def test_entity_in_both_files_is_kept_once_with_every_dataset():
    index = ofac.build_index([US_SANCTIONS, FCC_COVERED])
    hik = [e for e in index["entries"] if e.id == "NK-HYQpJVFfjnrATqKwpZpit7"]
    assert len(hik) == 1
    assert "US FCC Covered List" in hik[0].datasets
    assert "US DoD Chinese military companies" in hik[0].datasets
    assert len(index["entries"]) == 4


def test_match_exact_finds_fcc_only_company(monkeypatch):
    def fake_fetch(url, timeout=0, headers=None):
        text = FCC_COVERED if "us_fcc_covered_list" in url else US_SANCTIONS
        return SimpleNamespace(status_code=200, text=text)

    monkeypatch.setattr(ofac, "fetch_with_curl", fake_fetch)
    monkeypatch.setattr(ofac, "_cache", None)
    hits = ofac.match_exact("China Mobile International USA Inc")
    assert [h["datasets"] for h in hits] == [["US FCC Covered List"]]
    assert ofac.match_exact("Hikvision")[0]["id"] == "NK-HYQpJVFfjnrATqKwpZpit7"
    assert len(ofac.SANCTIONS_CSV_URLS) == 2
