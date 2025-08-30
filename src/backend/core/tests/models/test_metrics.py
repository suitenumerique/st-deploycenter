"""Tests for the Metric model with unique constraint."""

from django.db import IntegrityError
from django.test import TestCase

from core import factories, models


class MetricModelTest(TestCase):
    """Test cases for the Metric model with unique constraint."""

    def setUp(self):
        """Set up test data."""
        self.organization = factories.OrganizationFactory()
        self.service = factories.ServiceFactory()

    def test_metric_creation(self):
        """Test that a metric can be created successfully."""
        metric = factories.MetricFactory(
            organization=self.organization,
            service=self.service,
            key="test_metric",
            value="100.50",
        )

        self.assertEqual(metric.key, "test_metric")
        self.assertEqual(float(metric.value), 100.50)
        self.assertEqual(metric.organization, self.organization)
        self.assertEqual(metric.service, self.service)

        # Test standard primary key
        self.assertIsNotNone(metric.id)
        self.assertIsInstance(metric.id, int)  # AutoField

    def test_unique_constraint(self):
        """Test that the unique constraint works correctly."""
        # Create first metric
        factories.MetricFactory(
            organization=self.organization,
            service=self.service,
            key="unique_metric",
            value="100.00",
        )

        # Try to create another metric with same service, organization, and key
        # This should fail due to unique constraint
        with self.assertRaises(IntegrityError):
            factories.MetricFactory(
                organization=self.organization,
                service=self.service,
                key="unique_metric",
                value="200.00",
            )

    def test_different_service_allows_duplicate(self):
        """Test that different services allow duplicate metrics."""
        service2 = factories.ServiceFactory()

        # Create first metric
        metric1 = factories.MetricFactory(
            organization=self.organization,
            service=self.service,
            key="duplicate_metric",
            value="100.00",
        )

        # Create second metric with same organization and key but different service
        metric2 = factories.MetricFactory(
            organization=self.organization,
            service=service2,
            key="duplicate_metric",
            value="150.00",
        )

        self.assertEqual(metric2.key, "duplicate_metric")
        self.assertEqual(float(metric2.value), 150.00)
        self.assertNotEqual(metric1.id, metric2.id)

    def test_different_organization_allows_duplicate(self):
        """Test that different organizations allow duplicate metrics."""
        organization2 = factories.OrganizationFactory()

        # Create first metric
        metric1 = factories.MetricFactory(
            organization=self.organization,
            service=self.service,
            key="duplicate_metric",
            value="100.00",
        )

        # Create second metric with same service and key but different organization
        metric2 = factories.MetricFactory(
            organization=organization2,
            service=self.service,
            key="duplicate_metric",
            value="150.00",
        )

        self.assertEqual(metric2.key, "duplicate_metric")
        self.assertEqual(float(metric2.value), 150.00)
        self.assertNotEqual(metric1.id, metric2.id)

    def test_metric_string_representation(self):
        """Test the string representation of a metric."""
        metric = factories.MetricFactory(
            organization=self.organization,
            service=self.service,
            key="test_metric",
            value="100.00",
        )

        expected = (
            f"test_metric: 100.00 for {self.service.name} - {self.organization.name}"
        )
        self.assertEqual(str(metric), expected)

    def test_metric_service_validation(self):
        """Test that metric validation works correctly."""
        metric = models.Metric(
            key="test_metric",
            value="100.00",
            service=None,  # Missing required service
            organization=self.organization,
        )

        with self.assertRaises(IntegrityError):
            metric.save()

    def test_standard_primary_key_filtering(self):
        """Test filtering by standard primary key."""
        metric = factories.MetricFactory(
            organization=self.organization,
            service=self.service,
            key="filter_test",
            value="100.00",
        )

        # Filter by standard primary key
        filtered_metric = models.Metric.objects.filter(id=metric.id).first()
        self.assertEqual(filtered_metric, metric)

        # Test that the standard id field works
        self.assertIsNotNone(metric.id)
        self.assertIsInstance(metric.id, int)  # AutoField
