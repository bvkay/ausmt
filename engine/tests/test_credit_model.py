"""the contributor-credit model (engine credit citation path): the suppression kill, the citation-author
assembly, the verbatim creators[]/contributors[] seam, the DataCite HostingInstitution export, the
funders grant_id pass-through, and the mth5 project_lead derivation + ORCID url.

These are PURE (no mt_metadata/mth5 stack): they exercise the survey.yaml -> SMETA mappers, the mtcat
export builder, and normalize._survey_meta_get directly. Each behaviour-change test names, in its
docstring, the pre-change value that makes it RED (the suppression kill and the creators-drive-the-
citation change were both git-stash RED-proven against origin/main).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "extract"))

from extract import build_portal as bp                      # noqa: E402
from ausmt_science.ingest.normalize import _survey_meta_get  # noqa: E402


# --------------------------------------------------------------- the suppression kill (headline RED-prove)

def test_citation_names_all_creators_even_with_lead_and_pis():
    """RED-prove the suppression kill : a survey carrying BOTH a lead_investigator AND
    principal_investigators AND creators[] must cite ALL creators, in order. Pre-change cite.au was always
    org_name (the retired lead suppressed the PIs and creators were never read), so it named none of the
    creators - this fails on origin/main and passes after the change."""
    y = {"organisation": {"name": "University of X"},
         "lead_investigator": {"name": "Thiel, Stephan", "orcid": "0000-0002-1825-0097"},
         "principal_investigators": [{"name": "Robertson, Kate"}, {"name": "Duan, Jingming"}],
         "creators": [{"name": "Thiel, Stephan", "name_type": "person", "orcid": "0000-0002-1825-0097"},
                      {"name": "Robertson, Kate", "name_type": "person"},
                      {"name": "Geological Survey of South Australia", "name_type": "organisation"}]}
    sm = bp.survey_meta_from_yaml(y)
    assert sm["cite"]["au"] == ("Thiel, Stephan; Robertson, Kate; "
                                "Geological Survey of South Australia"), sm["cite"]["au"]
    assert sm["cite"]["au"] != "University of X"   # NOT the org-year synthesis, and NOT the lead alone


def test_no_retired_credit_key_is_read_into_smeta():
    """A survey that still carries BOTH retired
    keys and no creators serves NO investigators facet at all and cites the organisation and the year.
    Pre-change survey_meta_from_yaml folded the retired keys into a back-compat 'investigators' SMETA key
    (and _investigators_of existed to build it), so the retired values were still read and served."""
    y = {"organisation": {"name": "University of X"},
         "lead_investigator": {"name": "Lead Person", "orcid": "0000-0002-1825-0097"},
         "principal_investigators": [{"name": "PI Two"}, {"name": "PI Three"}]}
    sm = bp.survey_meta_from_yaml(y)
    assert "investigators" not in sm, sorted(sm)
    assert not hasattr(bp, "_investigators_of"), "the retired-key reader is gone"
    assert sm["cite"]["au"] == "University of X", sm["cite"]["au"]


# --------------------------------------------------------------- citation-author precedence

def test_citation_prefers_verbatim_cite_au_over_org_when_no_creators():
    """ middle rung: a hand-authored verbatim cite.au wins over the org-year synthesis when no
    creators are present. The retired lead/PI keys never enter this chain."""
    y = {"organisation": {"name": "Custodian Org"}, "cite": {"au": "Verbatim, Author"},
         "lead_investigator": {"name": "Ignored Lead"}}
    assert bp.survey_meta_from_yaml(y)["cite"]["au"] == "Verbatim, Author"


def test_citation_falls_back_to_org_year_when_no_creators_or_cite():
    """ fallback (unchanged default): no creators and no hand-authored cite -> the org name. A survey
    that carries only a lead_investigator still renders the org citation (the retired field is not the
    citation author)."""
    y = {"organisation": {"name": "Custodian Org"}, "lead_investigator": {"name": "A Lead"}}
    assert bp.survey_meta_from_yaml(y)["cite"]["au"] == "Custodian Org"


# --------------------------------------------------------------- the verbatim creators/contributors seam

def test_creators_and_contributors_served_verbatim_order_preserved():
    """Pinned seam: creators[]/contributors[] ride into SMETA verbatim, ORDER PRESERVED, only
    the validated keys, keys OMITTED when the source row omits them (an orcid-less row carries no orcid
    key, not a null). Pre-change SMETA had no creators/contributors keys at all."""
    y = {"organisation": {"name": "Org"},
         "creators": [{"name": "First, A", "name_type": "person", "orcid": "0000-0002-1825-0097"},
                      {"name": "Second Org", "name_type": "organisation", "ror": "https://ror.org/00892tw58"}],
         "contributors": [{"name": "Lead, L", "name_type": "person", "role": "ProjectLeader"},
                          {"name": "Zonge Engineering", "name_type": "organisation",
                           "role": "DataCollector"}]}
    sm = bp.survey_meta_from_yaml(y)
    assert sm["creators"] == [
        {"name": "First, A", "name_type": "person", "orcid": "0000-0002-1825-0097"},
        {"name": "Second Org", "name_type": "organisation", "ror": "https://ror.org/00892tw58"}]
    assert sm["contributors"] == [
        {"name": "Lead, L", "name_type": "person", "role": "ProjectLeader"},
        {"name": "Zonge Engineering", "name_type": "organisation", "role": "DataCollector"}]


def test_credit_lists_absent_keys_omitted_and_junk_rows_dropped():
    """Absent -> absent (byte-identical for the pre-migration corpus): a survey with neither list serves
    neither key. Non-mapping rows and rows without a real name are dropped, never crashing."""
    assert "creators" not in bp.survey_meta_from_yaml({"organisation": {"name": "Org"}})
    assert "contributors" not in bp.survey_meta_from_yaml({"organisation": {"name": "Org"}})
    y = {"creators": ["not-a-mapping", {"name_type": "person"}, {"name": "Kept, One", "name_type": "person"}]}
    assert bp.survey_meta_from_yaml(y)["creators"] == [{"name": "Kept, One", "name_type": "person"}]


# --------------------------------------------------------------- DataCite export: AusMT HostingInstitution

def _mtcat_survey_entry(meta):
    stations = [(Path("a.edi"), {"survey": "S", "ausmt_id": "au.s.A1", "id": "A1",
                                 "lat": -30.0, "lon": 137.0, "type": "BBMT"})]
    doc = bp.mtcat_document({"S": meta}, stations, generated_at="2026-01-01T00:00:00Z")
    return doc["surveys"][0]


def test_datacite_export_adds_ausmt_hosting_institution():
    """: the mtcat (DataCite/federation) export appends AusMT as the HostingInstitution to every
    record's contributors, after the survey's own contributors, verbatim. Pre-change mtcat carried no
    contributors field at all."""
    entry = _mtcat_survey_entry({"org": "Org", "access": "open",
                                 "contributors": [{"name": "Lead, L", "name_type": "person",
                                                   "role": "ProjectLeader"}]})
    assert entry["contributors"] == [
        {"name": "Lead, L", "name_type": "person", "role": "ProjectLeader"},
        {"name": "AusMT", "name_type": "organisation", "role": "HostingInstitution"}]


def test_datacite_hosting_institution_added_even_with_no_survey_contributors():
    """: AusMT hosts every survey, so the HostingInstitution row is emitted even when the survey declares
    no contributors of its own."""
    entry = _mtcat_survey_entry({"org": "Org", "access": "open"})
    assert entry["contributors"] == [
        {"name": "AusMT", "name_type": "organisation", "role": "HostingInstitution"}]


def test_hosting_institution_is_export_only_never_in_surveys_json_seam():
    """: AusMT is EXPORT-only - it must never leak into the surveys.json (SMETA) contributors seam,
    which stays the verbatim curator surface."""
    y = {"organisation": {"name": "Org"},
         "contributors": [{"name": "Lead, L", "name_type": "person", "role": "ProjectLeader"}]}
    sm = bp.survey_meta_from_yaml(y)
    assert all(c["name"] != "AusMT" for c in sm["contributors"])
    assert not any(c.get("role") == "HostingInstitution" for c in sm["contributors"])


# --------------------------------------------------------------- funders grant_id pass-through

def test_funders_carry_grant_id_when_present_only():
    """ (mth5 follow-up): _funders_of threads grant_id from the survey funding row when it declares a
    real one, and OMITS it otherwise (the corpus carries grant_id: null, so no placeholder grant id ever
    reaches the mth5 producer). Pre-change _funders_of emitted only {name, pid}."""
    y = {"funding": [{"organisation": "ARC", "organisation_ror": None, "grant_id": "DP000000"},
                     {"organisation": "AuScope", "grant_id": None}]}
    funders = bp._funders_of(y)
    assert funders[0]["grant_id"] == "DP000000"
    assert "grant_id" not in funders[1]


# --------------------------------------------------------------- mth5 project_lead + ORCID url

def test_orcid_url_canonicalises_or_none():
    assert bp._orcid_url("0000-0002-1825-0097") == "https://orcid.org/0000-0002-1825-0097"
    assert bp._orcid_url("https://orcid.org/0000-0002-1825-009X") == "https://orcid.org/0000-0002-1825-009X"
    assert bp._orcid_url("0000-0002-1825-009x") == "https://orcid.org/0000-0002-1825-009X"
    assert bp._orcid_url(None) is None
    assert bp._orcid_url("not-an-orcid") is None


def test_project_lead_prefers_projectleader_contributor_then_creator_and_never_a_retired_facet():
    """The mth5 project_lead is the lead-most credited party: a ProjectLeader contributor first, else the
    lead creator. inverts the third rung: the retired investigators facet is not a fallback, so a
    SMETA carrying only that stale key yields None. Pre-change it returned {"name": "Inv, I"}."""
    proj = bp._mth5_project_lead({
        "creators": [{"name": "Creator, C", "orcid": "0000-0002-1825-0097"}],
        "contributors": [{"name": "Member, M", "role": "ProjectMember"},
                         {"name": "Leader, L", "role": "ProjectLeader", "orcid": "0000-0002-1825-009X"}],
        "investigators": [{"name": "Inv, I"}]})
    assert proj == {"name": "Leader, L", "orcid": "0000-0002-1825-009X"}
    # no ProjectLeader contributor -> the lead creator
    assert bp._mth5_project_lead({"creators": [{"name": "Creator, C"}],
                                  "investigators": [{"name": "Inv, I"}]})["name"] == "Creator, C"
    # neither creators nor a ProjectLeader -> None; the retired facet is not read
    assert bp._mth5_project_lead({"investigators": [{"name": "Inv, I"}]}) is None
    assert bp._mth5_project_lead({}) is None


# --------------------------------------------------------------- EDI/XML export attribution (normalize)

def test_edi_export_attribution_reads_creators_over_a_stale_retired_facet():
    """ (scope: the EDI/EMTF-XML export attribution): _survey_meta_get assembles the citation-author
    line from creators[] when present. A stale investigators key in a hand-built SMETA never competes."""
    authors, _title, _doi = _survey_meta_get({
        "org": "Custodian Org",
        "creators": [{"name": "Thiel, Stephan"}, {"name": "Geological Survey of South Australia"}],
        "investigators": [{"name": "Someone Else"}]})
    assert authors == "Thiel, Stephan; Geological Survey of South Australia", authors


def test_edi_export_attribution_falls_straight_to_the_org_without_creators():
    """With no creators the export author falls STRAIGHT to the custodian org. The retired
    investigators fallback is gone, so a stale facet in a hand-built SMETA is ignored rather than named.
    Pre-change this returned "A. R, B. S". Never the portal brand."""
    a1, _, _ = _survey_meta_get({"org": "Org", "investigators": [{"name": "A. R"}, {"name": "B. S"}]})
    assert a1 == "Org"
    a2, _, _ = _survey_meta_get({"org": "Custodian Org"})
    assert a2 == "Custodian Org"
