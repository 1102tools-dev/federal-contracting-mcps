"""Example suite: the round-10 canonical regression set (~12 calls).

Re-stamps every load-bearing live finding from the 2026-08 campaign. Each
probe is documented in testing.md ("Round 10"). Run via paced_probe.py.
"""

ENT = "/entity-information/v3/entities"
EXC = "/entity-information/v4/exclusions"
OPP = "/opportunities/v2/search"
AWD = "/contract-awards/v1/search"
ASSIST = "/prod/assistance/v1/subawards/search"
W = {"postedFrom": "05/01/2026", "postedTo": "06/30/2026"}


def run(p) -> None:
    # offset is a zero-based PAGE index on Opportunities and Contract Awards
    sup = p.call("opps offset superset", OPP, {**W, "limit": 4, "offset": 0})
    _, rows = p.first_list(sup)
    ids = [p.fp(r) for r in rows]
    pair_body = p.call("opps offset pair", OPP, {**W, "limit": 2, "offset": 1})
    _, prows = p.first_list(pair_body)
    pair = [p.fp(r) for r in prows]
    p.check("opps offset page-index", verdict=(pair == ids[2:4]))

    sup = p.call("awards offset superset", AWD, {"fiscalYear": 2024, "limit": 4, "offset": 0})
    _, rows = p.first_list(sup)
    ids = [p.fp(r) for r in rows]
    pair_body = p.call("awards offset pair", AWD, {"fiscalYear": 2024, "limit": 2, "offset": 1})
    _, prows = p.first_list(pair_body)
    pair = [p.fp(r) for r in prows]
    p.check("awards offset page-index", verdict=(pair == ids[2:4]))

    # historical floor: FY1970 has (2) records; the API accepts 4-digit years
    b = p.call("awards fy=1970", AWD, {"fiscalYear": 1970, "limit": 1})
    p.check("fy1970 reachable", total=b.get("totalRecords"))

    # dead enum values return empty result sets
    b = p.call("entities regStatus=D", ENT,
               {"registrationStatus": "D", "size": 1, "includeSections": "entityRegistration"})
    p.check("regStatus D dead", total=b.get("totalRecords"), expect=0)

    # exclusions isActive is inert on the live API
    b = p.call("exclusions isActive=true", EXC, {"isActive": "true", "size": 1})
    p.check("isActive inert", total=b.get("totalRecords"))

    # assistance agencyCode demands a four digit number
    b = p.call("assistance agencyCode=075", ASSIST,
               {"fromDate": "2024-06-01", "toDate": "2024-06-30",
                "agencyCode": "075", "pageSize": 1, "pageNumber": 0})
    p.check("agencyCode 3-digit rejected", status_expected=400)

    # SBA certification population anchors (tolerant: these drift)
    b = p.call("entities sba A6", ENT,
               {"sbaBusinessTypeCode": "A6", "registrationStatus": "A",
                "size": 1, "includeSections": "entityRegistration"})
    p.check("A6 population", total=b.get("totalRecords"), anchor_2026_08=4874)
    b = p.call("entities sba XX", ENT,
               {"sbaBusinessTypeCode": "XX", "registrationStatus": "A",
                "size": 1, "includeSections": "entityRegistration"})
    p.check("XX population", total=b.get("totalRecords"), anchor_2026_08=4551)

    print("\n=== canonical suite complete ===")
