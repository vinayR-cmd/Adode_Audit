"""
analyze.py — deterministic fast-path helper for the entity-trust-audit skill.

Answers: when an assistant has the text, does it know WHO said it, and can it
tell this brand apart from every other thing with the same name?

Checks JSON-LD presence/validity/coverage, Organization-class identity markup,
sameAs anchoring to independent identity graphs, and structural signs of name
ambiguity. Ambiguity itself cannot be settled offline — this script reports the
evidence and defers the verdict to the agent's own web search.

Usage:
    python analyze.py --bundle bundle.json
    python analyze.py --url https://example.com
"""

import re
import sys
from urllib.parse import urlparse

import common
from common import finding, not_verified, opportunity

SKILL = "entity-trust-audit"

# schema.org has dozens of Organization and LocalBusiness subtypes
# (NewsMediaOrganization, Dentist, AutoRepair, ...). Matching a fixed list alone
# produces false "no identity markup" findings on sites that are correctly
# marked up with a subtype, so identity is decided by _is_identity() below.
IDENTITY_TYPES = {"Organization", "Corporation", "LocalBusiness", "NGO",
                  "EducationalOrganization", "GovernmentOrganization",
                  "MedicalOrganization", "SportsOrganization", "Person",
                  "OnlineBusiness", "Store", "Restaurant", "Hotel", "Airline",
                  "Brand", "ProfessionalService", "FoodEstablishment",
                  "LegalService", "RealEstateAgent", "TravelAgency", "Dentist",
                  "Physician", "Pharmacy", "VeterinaryCare", "AutoRepair",
                  "HomeAndConstructionBusiness", "AutomotiveBusiness",
                  "FinancialService", "InsuranceAgency", "Library", "Museum",
                  "School", "CollegeOrUniversity", "Hospital", "Church",
                  "ChildCare", "EmploymentAgency", "GovernmentOffice",
                  "SportsTeam", "MusicGroup", "PerformingGroup",
                  "ResearchOrganization", "PoliticalParty", "Consortium",
                  "WorkersUnion", "FundingScheme", "Cooperative"}
# Only suffixes that always denote an entity. NOT "Service": GovernmentService,
# TaxiService and friends are services a body offers, not the body itself.
_IDENTITY_SUFFIXES = ("Organization", "Business")


def _is_identity(t):
    """True for any schema.org type that names an entity, not a page or thing."""
    t = str(t or "").split("/")[-1].split("#")[-1]
    return t in IDENTITY_TYPES or t.endswith(_IDENTITY_SUFFIXES)


def _types_of(obj):
    t = obj.get("@type")
    return [str(x) for x in (t if isinstance(t, list) else ([t] if t else []))]
AUTHORITY_ANCHORS = ("wikipedia.org", "wikidata.org", "linkedin.com/company",
                     "linkedin.com/in", "crunchbase.com", "bloomberg.com",
                     "opencorporates.com", "sec.gov", "companieshouse.gov.uk",
                     "g2.com", "capterra.com", "trustpilot.com", "bbb.org",
                     "glassdoor.com", "github.com", "orcid.org", "isni.org")
SOCIAL_ONLY = ("facebook.com", "twitter.com", "x.com", "instagram.com",
               "youtube.com", "tiktok.com", "pinterest.com")

# Words that make a brand name collide with common language / other entities.
GENERIC_TOKENS = {
    "apple", "delta", "shell", "orange", "amazon", "square", "stripe", "slack",
    "monday", "arc", "atlas", "beacon", "bridge", "core", "eco", "element",
    "flow", "forge", "fusion", "global", "group", "harbor", "impact", "lift",
    "link", "loop", "match", "nova", "north", "orbit", "peak", "pulse", "prime",
    "pure", "rise", "root", "scale", "sense", "shift", "signal", "spark",
    "spring", "summit", "swift", "vertex", "vision", "wave", "zenith", "one",
    "smart", "digital", "solutions", "systems", "labs", "studio", "media",
    "health", "care", "clinic", "law", "capital", "partners", "consulting",
}


def _brand_candidates(bundle, home_parsed, objects):
    names = []
    for o in objects:
        if any(_is_identity(t) for t in _types_of(o)):
            if isinstance(o.get("name"), str):
                names.append(o["name"])
    site_name = common.meta_content(home_parsed["metas"], prop="og:site_name")
    if site_name:
        names.append(site_name)
    title = home_parsed.get("title") or ""
    if title:
        names.append(re.split(r"\s[|\-–—:]\s", title)[0].strip()[:60])
    host = urlparse(bundle.get("start_url", "")).netloc
    names.append(common.registrable(host).split(".")[0])
    seen, out = set(), []
    for nme in names:
        key = (nme or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(nme.strip())
    return out


def analyze(bundle):
    findings, nv, opps = [], [], []
    obs = {}
    sample = common.html_pages(bundle)
    if not sample:
        nv.append(not_verified("entity_trust", "no analyzable HTML page in the sample",
                               bundle.get("start_url")))
        return _wrap(findings, nv, opps, obs)

    home = sample[0]
    home_parsed = common.get_parsed(home)

    all_objects, all_errors = [], []
    pages_with_schema, pages_with_microdata, broken_pages = [], [], []
    for p in sample:
        parsed = common.get_parsed(p)
        objs, errs = common.parse_jsonld(parsed["jsonld_raw"])
        if parsed["jsonld_raw"]:
            pages_with_schema.append(p["final_url"])
        if parsed["microdata_itemtypes"]:
            pages_with_microdata.append(p["final_url"])
        if errs:
            broken_pages.append((p["final_url"], errs[0]))
            all_errors.extend(errs)
        all_objects.extend(objs)

    n = len(sample)
    types = common.jsonld_types(all_objects)
    obs["jsonld_types"] = sorted(types)
    obs["pages_with_jsonld"] = len(pages_with_schema)
    obs["pages_with_microdata"] = len(pages_with_microdata)
    obs["pages_sampled"] = n

    identity_objs = [o for o in all_objects
                     if any(_is_identity(t) for t in _types_of(o))]
    obs["identity_types_found"] = sorted({t for o in identity_objs
                                          for t in _types_of(o)})

    # --------------------------------------------------- structured data at all
    if not pages_with_schema and not pages_with_microdata:
        findings.append(finding(
            title="No structured data anywhere in the sample",
            severity="high", category="discoverability",
            mechanism="Identity resolution: without machine-readable markup, an "
                      "assistant must infer from prose who published a claim. That "
                      "inference is weaker than a declared entity, so the brand is "
                      "more likely to be described vaguely, merged with a similarly "
                      "named entity, or left uncited.",
            evidence="0 of %d sampled pages contain a JSON-LD block or microdata "
                     "itemtype. Checked: %s"
                     % (n, "; ".join(p["final_url"] for p in sample[:5])),
            action_summary="Publish an Organization (or LocalBusiness) JSON-LD block "
                           "sitewide, plus a page-type schema on key templates.",
            how="Start with @type Organization on every page: name, url, logo, "
                "description, and sameAs to your Wikidata/LinkedIn/Crunchbase entries.",
            confidence="high", root_cause="no-structured-data", check="jsonld_presence",
            pages=[p["final_url"] for p in sample[:5]]))
    else:
        # ------------------------------------------------------ broken markup
        if broken_pages:
            findings.append(finding(
                title="JSON-LD is present but does not parse",
                severity="high", category="discoverability",
                mechanism="Identity resolution: invalid JSON-LD is discarded wholesale "
                          "by consumers, so the site pays the authoring cost and gets "
                          "none of the identity benefit — and the failure is silent.",
                evidence="; ".join("%s -> %s" % (u, e) for u, e in broken_pages[:4]),
                action_summary="Fix the malformed JSON-LD (validate every template).",
                how="Run each template through a schema validator; trailing commas and "
                    "un-escaped quotes from templating are the usual causes.",
                confidence="high", root_cause="broken-jsonld", check="jsonld_valid",
                pages=[u for u, _ in broken_pages]))

        # ---------------------------------------------------------- coverage
        coverage = len(set(pages_with_schema)) / float(n)
        if 0 < coverage < 0.5:
            findings.append(finding(
                title="Structured data covers only part of the site",
                severity="medium", category="discoverability",
                mechanism="Identity resolution: pages without markup are attributed "
                          "only by domain guess. Uneven coverage is usually one "
                          "template missing the include, so some content types are "
                          "systematically unattributed.",
                evidence="%d of %d sampled pages carry JSON-LD (%.0f%%). Without: %s"
                         % (len(set(pages_with_schema)), n, coverage * 100,
                            "; ".join(p["final_url"] for p in sample
                                      if p["final_url"] not in pages_with_schema)[:400]),
                action_summary="Move the schema block into the shared base template.",
                confidence="high", root_cause="schema-coverage",
                check="jsonld_coverage",
                pages=[p["final_url"] for p in sample
                       if p["final_url"] not in pages_with_schema][:8]))

        # ------------------------------------------------- identity entity
        if not identity_objs:
            findings.append(finding(
                title="Structured data never declares the publishing organisation",
                severity="high", category="discoverability",
                mechanism="Identity resolution: page-level types (Article, Product, "
                          "WebPage) describe content but not the publisher. Without an "
                          "Organization node, there is no entity for an assistant to "
                          "attach reputation or citations to.",
                evidence="JSON-LD @types found across %d pages: %s — none is an "
                         "organisation/person identity type."
                         % (n, ", ".join(sorted(types)) or "none"),
                action_summary="Add an Organization node (name, url, logo, sameAs) and "
                               "reference it as publisher/provider from page schemas.",
                confidence="high", root_cause="no-identity-entity",
                check="identity_markup",
                pages=[p["final_url"] for p in sample[:5]]))

    # -------------------------------------------------------------- sameAs
    same_as = []
    for o in identity_objs:
        sa = o.get("sameAs")
        vals = sa if isinstance(sa, list) else ([sa] if sa else [])
        same_as.extend(str(v) for v in vals if v)
    profile_links = []
    for p in sample:
        for href, _t in common.get_parsed(p)["links"]:
            low = href.lower()
            if any(a in low for a in AUTHORITY_ANCHORS):
                profile_links.append(href)

    authority_hits = [u for u in same_as if any(a in u.lower() for a in AUTHORITY_ANCHORS)]
    social_only = [u for u in same_as if any(s in u.lower() for s in SOCIAL_ONLY)]
    obs["sameAs"] = same_as[:12]
    obs["authority_profile_links_on_page"] = sorted(set(profile_links))[:8]

    if identity_objs and not same_as:
        findings.append(finding(
            title="Organisation markup has no sameAs links",
            severity="medium", category="discoverability",
            mechanism="Entity disambiguation: sameAs is the explicit join between this "
                      "site and the identity graphs (Wikidata, LinkedIn, Crunchbase) "
                      "assistants resolve names against. Without it, the brand is a "
                      "string on a website rather than a known entity.",
            evidence="Organisation node(s) found (%s) but no sameAs property. "
                     "Independent-profile links found in page HTML: %s"
                     % (", ".join(sorted({str(o.get("name", "?"))[:40]
                                          for o in identity_objs})),
                        ", ".join(sorted(set(profile_links))[:3]) or "none"),
            action_summary="Add sameAs URLs for every independent profile the brand "
                           "already owns.",
            confidence="high", root_cause="no-sameas", check="sameas"))
    elif same_as and not authority_hits and social_only:
        findings.append(finding(
            title="sameAs points only to social profiles, not identity graphs",
            severity="low", category="discoverability",
            mechanism="Entity disambiguation: social profiles are self-asserted and "
                      "weakly linked in entity graphs. Wikidata/LinkedIn-company/"
                      "registry entries are what actually resolve a name to an entity.",
            evidence="sameAs values: %s" % ", ".join(same_as[:6]),
            action_summary="Add Wikidata, LinkedIn company and industry-registry URLs "
                           "to sameAs.",
            confidence="medium", root_cause="weak-sameas", check="sameas_quality"))

    # --------------------------------------------------------- name ambiguity
    names = _brand_candidates(bundle, home_parsed, all_objects)
    obs["brand_name_candidates"] = names[:4]
    primary = names[0] if names else ""
    tokens = [t for t in re.split(r"[\s\-_]+", primary.lower()) if t]
    generic = [t for t in tokens if t in GENERIC_TOKENS]
    if primary and (generic or (len(tokens) == 1 and len(primary) <= 6)):
        if authority_hits:
            obs["ambiguity"] = ("name looks collision-prone (%r) but sameAs anchors to "
                                "%s — disambiguated" % (primary, authority_hits[0]))
        else:
            # Collision risk cannot be settled from the site alone: a script that
            # asserted it would false-positive on well-known brands. Emit it as an
            # opportunity plus an explicit unverified check, and let the agent's own
            # web search decide whether it becomes a finding.
            opps.append(opportunity(
                title="Anchor the brand name against same-name entities",
                category="discoverability",
                rationale="Primary name %r%s, and no sameAs link to an identity graph "
                          "(Wikidata/LinkedIn/registry) was found on the sampled pages. "
                          "Whether the name is actually contested is NOT established "
                          "here — it needs a web search."
                          % (primary,
                             " contains the common token(s) %s" % ", ".join(generic)
                             if generic else " is a single short token"),
                action="Search the bare name first. If other entities dominate the "
                       "results, claim a Wikidata item and LinkedIn company page, link "
                       "both from sameAs, and use a qualified name ('<Name>, the "
                       "<category> company') in on-page prose.", effort="medium"))
            nv.append(not_verified(
                "name_ambiguity",
                "whether the name collides with other entities cannot be determined "
                "from the site alone; confirm with a web search before treating this "
                "as a defect", primary))

    if identity_objs:
        missing_props = sorted({k for k in ("name", "url", "logo", "description")
                                if not any(o.get(k) for o in identity_objs)})
        if missing_props:
            opps.append(opportunity(
                title="Complete the Organization node",
                category="discoverability",
                rationale="Organisation markup exists but omits %s, which are the "
                          "properties that render a rich, attributable entity."
                          % ", ".join(missing_props),
                action="Add %s to the Organization JSON-LD." % ", ".join(missing_props),
                effort="low"))

    return _wrap(findings, nv, opps, obs)


def _wrap(findings, nv, opps, obs):
    return {"skill": SKILL, "findings": findings, "not_verified": nv,
            "opportunities": opps, "observations": obs}


if __name__ == "__main__":
    common.emit(analyze(common.load_bundle_from_args(sys.argv[1:])))
