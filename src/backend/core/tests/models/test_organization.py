"""
Unit tests for the Organization model
"""

from django.core.exceptions import ValidationError

import pytest

from core import factories
from core.models import Organization

pytestmark = pytest.mark.django_db


class TestOrganizationModel:
    """Test the Organization model."""

    # Attribute: adresse_messagerie

    def test_messagerie_domain_empty(self):
        """The messagerie domain should be None if the email is not set."""
        organization = factories.OrganizationFactory(adresse_messagerie=None)
        assert organization.adresse_messagerie_domain == None

    def test_messagerie_domain_empty_str(self):
        """The messagerie domain should be None if the email is an empty string."""
        organization = factories.OrganizationFactory(adresse_messagerie="")
        assert organization.adresse_messagerie_domain == None

    def test_messagerie_domain_classic(self):
        """The messagerie domain should extract the domain from a standard email."""
        organization = factories.OrganizationFactory(
            adresse_messagerie="contact@commune.fr"
        )
        assert organization.adresse_messagerie_domain == "commune.fr"

    def test_messagerie_domain_special_characters(self):
        """The messagerie domain should extract the domain from an email with special characters."""
        organization = factories.OrganizationFactory(
            adresse_messagerie="commune.nom2.special+bis2@wanadoo.fr"
        )
        assert organization.adresse_messagerie_domain == "wanadoo.fr"

    def test_messagerie_domain_wrong_format(self):
        """The messagerie domain should raise ValidationError if the email format is invalid."""
        with pytest.raises(ValidationError) as exc_info:
            factories.OrganizationFactory(
                adresse_messagerie="commune.nom2.special+bis2wanadoo.fr"
            )
        assert "adresse_messagerie" in exc_info.value.message_dict
        assert (
            "Saisissez une adresse e-mail valide."
            in exc_info.value.message_dict["adresse_messagerie"]
        )

    # Attribute: site_internet

    def test_site_internet_domain_empty(self):
        """The site internet domain should be None if the website is not set."""
        organization = factories.OrganizationFactory(site_internet=None)
        assert organization.site_internet_domain == None

    def test_site_internet_domain_empty_str(self):
        """The site internet domain should be None if the website is an empty string."""
        organization = factories.OrganizationFactory(site_internet="")
        assert organization.site_internet_domain == None

    def test_site_internet_domain_classic(self):
        """The site internet domain should extract the domain from a standard website."""
        organization = factories.OrganizationFactory(site_internet="https://commune.fr")
        assert organization.site_internet_domain == "commune.fr"

    def test_site_internet_domain_classic_www(self):
        """The site internet domain should extract the domain from a standard website."""
        organization = factories.OrganizationFactory(
            site_internet="https://www.commune.fr"
        )
        assert organization.site_internet_domain == "commune.fr"

    def test_site_internet_domain_classic_trailing_slash(self):
        """The site internet domain should extract the domain from a standard website."""
        organization = factories.OrganizationFactory(
            site_internet="https://www.commune.fr/"
        )
        assert organization.site_internet_domain == "commune.fr"

    def test_site_internet_domain_classic_trailing_query_params(self):
        """The site internet domain should extract the domain from a standard website."""
        organization = factories.OrganizationFactory(
            site_internet="https://www.commune.fr/?param=value"
        )
        assert organization.site_internet_domain == "commune.fr"

    def test_site_internet_domain_classic_port_query_params(self):
        """The site internet domain should extract the domain from a standard website."""
        organization = factories.OrganizationFactory(
            site_internet="https://www.commune.fr:8080/?param=value"
        )
        assert organization.site_internet_domain == "commune.fr"

    def test_site_internet_domain_classic_trailing_slash_query_params(self):
        """The site internet domain should extract the domain from a standard website."""
        organization = factories.OrganizationFactory(
            site_internet="https://www.commune.fr/?param=value"
        )
        assert organization.site_internet_domain == "commune.fr"

    def test_site_internet_domain_special_characters(self):
        """The site internet domain should extract the domain from a website with special characters."""
        with pytest.raises(ValidationError) as exc_info:
            factories.OrganizationFactory(
                site_internet="https://www.commune.nom2.special+bis2.fr"
            )
        assert "site_internet" in exc_info.value.message_dict
        assert (
            "Saisissez une URL valide." in exc_info.value.message_dict["site_internet"]
        )

    def test_site_internet_domain_wrong_format(self):
        """The site internet domain should raise ValidationError if the website format is invalid."""
        with pytest.raises(ValidationError) as exc_info:
            factories.OrganizationFactory(
                site_internet="commune.nom2.special+bis2wanadoo.fr"
            )
        assert "site_internet" in exc_info.value.message_dict
        assert (
            "Saisissez une URL valide." in exc_info.value.message_dict["site_internet"]
        )

    # Method: get_mail_domain_status

    def test_get_mail_domain_status_empty_rpnt(self):
        """RNPT is empty, we should get INVALID."""
        organization = factories.OrganizationFactory(
            rpnt=[],
            adresse_messagerie="contact@commune.fr",
            site_internet="https://www.commune.fr",
        )
        assert organization.get_mail_domain_status() == (
            None,
            Organization.MailDomainStatus.INVALID,
        )

    def test_get_mail_domain_status_unmatched_criteria(self):
        """RNPT criteria are not matched, we should get INVALID."""
        organization = factories.OrganizationFactory(
            rpnt=["2.1"],
            adresse_messagerie="contact@commune.fr",
            site_internet="https://www.commune.fr",
        )
        assert organization.get_mail_domain_status() == (
            None,
            Organization.MailDomainStatus.INVALID,
        )

    def test_get_mail_domain_status_valid_website_invalid_email(self):
        """RPNPT website and email domains are not valid. We should get the website domain as the mail domain."""
        organization = factories.OrganizationFactory(
            rpnt=["1.1"],
            adresse_messagerie="contact@wanadoo.fr",
            site_internet="https://www.commune.fr",
        )
        assert organization.get_mail_domain_status() == (
            "commune.fr",
            Organization.MailDomainStatus.NEED_EMAIL_SETUP,
        )

    def test_get_mail_domain_status_valid_website_and_email(self):
        """RPNT website and email domains are valid. We should get the email domain as the mail domain."""
        # In this RNPT situation, addresse_messagerie and site_internet should be the same, but for the
        # sake of the test, we set them to different values to make sure the code use the one from
        # addresse_messagerie.
        organization = factories.OrganizationFactory(
            rpnt=["2.1", "2.2"],
            adresse_messagerie="contact@commune.fr",
            site_internet="https://www.commune2.fr",
        )
        assert organization.get_mail_domain_status() == (
            "commune.fr",
            Organization.MailDomainStatus.VALID,
        )
