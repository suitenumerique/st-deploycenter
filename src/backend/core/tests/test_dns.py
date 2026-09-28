"""Tests for the authoritative DNS lookups (core/services/dns.py).

The network is replaced by an in-process hierarchy of authoritative servers, so
these run offline and exercise the real resolver from the root down.
"""

import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rdataclass
import dns.rdatatype
import dns.rrset
import pytest
from recursive_resolver.roots import get_root_addresses

from core.services import dns as dns_service

# Nameserver hostname -> address.
HOSTS = {
    "a.nic.fr.": "81.0.0.1",
    "a.nic.cloud.": "81.0.0.2",
    "a.gtld.net.": "81.0.0.3",
    "a.gtld.com.": "81.0.0.4",
    "nsa.scaleway.com.": "81.0.1.1",
    "nsb.scaleway.com.": "81.0.1.2",
    "nsc.scaleway.com.": "81.0.1.3",
    "nsd.scaleway.com.": "81.0.1.4",
    "nsele1.online.net.": "81.0.2.1",
    "nsele2.online.net.": "81.0.2.2",
    "ns0.dom.scw.cloud.": "81.0.3.1",
    "ns1.dom.scw.cloud.": "81.0.3.2",
    "ns1.lst-domaines.fr.": "81.0.4.1",
    "ns2.lst-domaines.fr.": "81.0.4.2",
}

SCALEWAY = [
    "nsa.scaleway.com.",
    "nsb.scaleway.com.",
    "nsc.scaleway.com.",
    "nsd.scaleway.com.",
]

# Zone -> its nameservers. houdelaincourt.fr as delegated in production: four
# levels of nameservers living outside the zone they serve, none with glue.
ZONES = {
    "fr.": ["a.nic.fr."],
    "cloud.": ["a.nic.cloud."],
    "net.": ["a.gtld.net."],
    "com.": ["a.gtld.com."],
    "scaleway.com.": SCALEWAY,
    "online.net.": SCALEWAY,
    "scw.cloud.": ["nsele1.online.net.", "nsele2.online.net."],
    "lst-domaines.fr.": ["ns0.dom.scw.cloud.", "ns1.dom.scw.cloud."],
    "houdelaincourt.fr.": ["ns1.lst-domaines.fr.", "ns2.lst-domaines.fr."],
}


def _name(text):
    return dns.name.from_text(text)


def _zones_served_by(address):
    if address in get_root_addresses():
        yield dns.name.root
    for zone, nameservers in ZONES.items():
        if any(HOSTS[ns] == address for ns in nameservers):
            yield _name(zone)


def _answer(query, address):
    """What the fake authoritative server at ``address`` answers to ``query``."""
    question = query.question[0]
    qname, qtype = question.name, question.rdtype
    response = dns.message.make_response(query)

    served = [z for z in _zones_served_by(address) if qname.is_subdomain(z)]
    if not served:
        response.set_rcode(dns.rcode.REFUSED)
        return response
    zone = max(served, key=len)

    # The closest cut below our zone on the way to qname: a referral.
    cuts = [
        _name(child)
        for child in ZONES
        if _name(child) != zone
        and _name(child).is_subdomain(zone)
        and qname.is_subdomain(_name(child))
    ]
    if cuts:
        child = min(cuts, key=len)
        nameservers = ZONES[child.to_text()]
        response.authority.append(
            dns.rrset.from_text_list(child, 3600, "IN", "NS", nameservers)
        )
        for ns in nameservers:
            if _name(ns).is_subdomain(child):
                response.additional.append(
                    dns.rrset.from_text(ns, 3600, "IN", "A", HOSTS[ns])
                )
        return response

    response.flags |= dns.flags.AA
    text = qname.to_text()
    if qtype == dns.rdatatype.NS and text in ZONES:
        response.answer.append(
            dns.rrset.from_text_list(qname, 3600, "IN", "NS", ZONES[text])
        )
    elif qtype == dns.rdatatype.A and text in HOSTS:
        response.answer.append(dns.rrset.from_text(qname, 3600, "IN", "A", HOSTS[text]))
    else:
        response.set_rcode(dns.rcode.NXDOMAIN)
        response.authority.append(
            dns.rrset.from_text(
                zone,
                3600,
                "IN",
                "SOA",
                f"ns.{zone} hostmaster.{zone} 1 3600 900 604800 300",
            )
        )
    return response


@pytest.fixture(name="fake_dns")
def fake_dns_fixture(monkeypatch):
    """Route every query the resolver sends to the fake hierarchy; count them."""
    sent = []

    def udp_with_fallback(query, where, **kwargs):  # pylint: disable=unused-argument
        sent.append((query.question[0].name.to_text(), where))
        return _answer(query, where), False

    monkeypatch.setattr(dns.query, "udp_with_fallback", udp_with_fallback)
    return sent


def test_nameservers_through_a_chain_of_glueless_delegations(fake_dns):
    """Each nameserver hostname is looked up once, not once per level.

    Re-resolving them at every level of the chain multiplies the queries and runs
    the resolver out of its query budget: the check reported an error for a domain
    correctly delegated to us.
    """
    results = dns_service.nameservers_batch(["houdelaincourt.fr"])

    assert results == {
        "houdelaincourt.fr": (["ns1.lst-domaines.fr", "ns2.lst-domaines.fr"], None)
    }
    lookups = [name for name, _ in fake_dns if name == "nsa.scaleway.com."]
    # One walk: the root, the .com referral, then the scaleway.com answer.
    assert len(lookups) == 3


@pytest.mark.usefixtures("fake_dns")
def test_nameservers_are_not_remembered_across_checks(monkeypatch):
    """A delegation changed at the registrar shows up on the next check."""
    assert dns_service.nameservers_batch(["houdelaincourt.fr"]) == {
        "houdelaincourt.fr": (["ns1.lst-domaines.fr", "ns2.lst-domaines.fr"], None)
    }

    monkeypatch.setitem(
        ZONES, "houdelaincourt.fr.", ["nsa.scaleway.com.", "nsb.scaleway.com."]
    )
    assert dns_service.nameservers_batch(["houdelaincourt.fr"]) == {
        "houdelaincourt.fr": (["nsa.scaleway.com", "nsb.scaleway.com"], None)
    }
