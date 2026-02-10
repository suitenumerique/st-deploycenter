import { useRouter } from "next/router";
import {
  getGlobalExplorerLayout,
  useOperatorContext,
} from "@/features/layouts/components/GlobalLayout";
import { Container } from "@/features/layouts/components/container/Container";
import { useTranslation } from "react-i18next";
import { Select } from "@openfun/cunningham-react";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import { useMemo, useState } from "react";
import {
  useOperatorMetrics,
  useOperatorOrganizations,
  useOperatorServices,
} from "@/hooks/useQueries";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import {
  AggregatedMetric,
  GroupedMetricsResponse,
  MetricsParams,
  MetricsResponse,
} from "@/features/api/Repository";

// Available metric keys - these could be fetched from an API in the future
const METRIC_KEYS = [
  "storage_used",
  "storage_quota",
  "user_count",
  "mailbox_count",
  "active_users",
  "message_count",
];

const ACCOUNT_TYPES = ["user", "mailbox"];

export default function MetricsPage() {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const { t } = useTranslation();

  useOperatorContext();

  // Filter states
  const [serviceFilter, setServiceFilter] = useState<string>("");
  const [keyFilter, setKeyFilter] = useState<string>("");
  const [organizationFilter, setOrganizationFilter] = useState<string[]>([]);
  const [accountTypeFilter, setAccountTypeFilter] = useState<string>("");
  const [aggregation, setAggregation] = useState<"" | "sum" | "avg">("");

  // Fetch operator services for the service filter
  const { data: operatorServices } = useOperatorServices(operatorId);

  // Fetch organizations for the organization filter
  const { data: organizations } = useOperatorOrganizations(operatorId, {});

  // Build metrics params only when we have required filters
  const metricsParams: MetricsParams | null = useMemo(() => {
    if (!serviceFilter || !keyFilter) return null;

    // When no organization filter is set and no aggregation, group by organization
    const shouldGroupByOrg = organizationFilter.length === 0 && !aggregation;

    return {
      key: keyFilter,
      service: serviceFilter,
      organizations:
        organizationFilter.length > 0 ? organizationFilter : undefined,
      account_type: accountTypeFilter || undefined,
      agg: aggregation || undefined,
      group_by: shouldGroupByOrg ? "organization" : undefined,
    };
  }, [
    serviceFilter,
    keyFilter,
    organizationFilter,
    accountTypeFilter,
    aggregation,
  ]);

  // Fetch metrics
  const { data: metricsData, isLoading: isMetricsLoading } = useOperatorMetrics(
    operatorId,
    metricsParams
  );

  // Determine response type
  const isAggregated = aggregation && metricsData && "aggregation" in metricsData;
  const isGroupedByOrg = metricsData && "grouped_by" in metricsData && metricsData.grouped_by === "organization";

  // Get results count
  const resultsCount = useMemo(() => {
    if (!metricsData) return 0;
    if (isAggregated) {
      return (metricsData as AggregatedMetric).count;
    }
    if (isGroupedByOrg) {
      return (metricsData as GroupedMetricsResponse).results.length;
    }
    return (metricsData as MetricsResponse).results.length;
  }, [metricsData, isAggregated, isGroupedByOrg]);

  // Prepare chart data
  const chartData = useMemo(() => {
    if (!metricsData) return [];

    if (isAggregated) {
      const aggData = metricsData as AggregatedMetric;
      return [
        {
          name: t(`metrics.filters.aggregation_options.${aggData.aggregation}`),
          value: parseFloat(aggData.value),
        },
      ];
    }

    if (isGroupedByOrg) {
      const response = metricsData as GroupedMetricsResponse;
      return response.results.map((item) => ({
        name: item.organization.name,
        value: parseFloat(item.value),
      }));
    }

    const response = metricsData as MetricsResponse;
    return response.results.map((metric) => ({
      name: metric.account
        ? metric.account.email || metric.account.external_id
        : metric.organization.name,
      value: parseFloat(metric.value),
      accountType: metric.account?.type,
      organization: metric.organization.name,
    }));
  }, [metricsData, isAggregated, isGroupedByOrg, t]);

  // Calculate dynamic chart height based on data
  const chartHeight = useMemo(() => {
    if (isAggregated) return 200;
    const minHeight = 300;
    const barHeight = 40;
    return Math.max(minHeight, chartData.length * barHeight);
  }, [chartData, isAggregated]);

  // Chart colors
  const chartColors = [
    "#000091", // Primary blue
    "#6a6af4",
    "#009099",
    "#c9191e",
    "#b34000",
    "#1f8d49",
  ];

  return (
    <Container
      titleNode={
        <>
          <Breadcrumbs
            items={[
              {
                content: <button className="c__breadcrumbs__button" onClick={() => router.push(`/operators/${operatorId}/metrics`)}>{t("metrics.title")}</button>,
              },
            ]}
          />
          <div className="dc__container__content__subtitle">
            {t("metrics.subtitle")}
          </div>
        </>
      }
    >
      {/* Filters */}
      <div className="dc__metrics__filters">
        <Select
          label={t("metrics.filters.service")}
          value={serviceFilter}
          onChange={(e) => {
            setServiceFilter((e.target.value as string) || "");
            // Reset key filter when service changes
            setKeyFilter("");
          }}
          options={[
            { label: t("metrics.filters.service_placeholder"), value: "" },
            ...(operatorServices?.results || []).map((service) => ({
              label: service.name,
              value: service.id,
            })),
          ]}
        />

        <Select
          label={t("metrics.filters.key")}
          value={keyFilter}
          onChange={(e) => setKeyFilter((e.target.value as string) || "")}
          disabled={!serviceFilter}
          options={[
            { label: t("metrics.filters.key_placeholder"), value: "" },
            ...METRIC_KEYS.map((key) => ({
              label: key,
              value: key,
            })),
          ]}
        />

        <Select
          label={t("metrics.filters.organizations")}
          value={organizationFilter.length > 0 ? organizationFilter[0] : ""}
          onChange={(e) => {
            const value = e.target.value as string;
            setOrganizationFilter(value ? [value] : []);
          }}
          options={[
            { label: t("metrics.filters.organizations_placeholder"), value: "" },
            ...(organizations?.results || []).map((org) => ({
              label: org.name,
              value: org.id,
            })),
          ]}
        />

        <Select
          label={t("metrics.filters.account_type")}
          value={accountTypeFilter}
          onChange={(e) => setAccountTypeFilter((e.target.value as string) || "")}
          options={[
            { label: t("metrics.filters.account_type_placeholder"), value: "" },
            ...ACCOUNT_TYPES.map((type) => ({
              label: t(`metrics.account_types.${type}`),
              value: type,
            })),
          ]}
        />

        <Select
          label={t("metrics.filters.aggregation")}
          value={aggregation}
          onChange={(e) =>
            setAggregation((e.target.value as "" | "sum" | "avg") || "")
          }
          options={[
            { label: t("metrics.filters.aggregation_options.none"), value: "" },
            { label: t("metrics.filters.aggregation_options.sum"), value: "sum" },
            { label: t("metrics.filters.aggregation_options.avg"), value: "avg" },
          ]}
        />
      </div>

      {/* Results count */}
      {metricsData && resultsCount > 0 && (
        <div className="dc__metrics__results-count">
          {t("metrics.chart.results_count", { count: resultsCount })}
        </div>
      )}

      {/* Chart */}
      <div className="dc__metrics__chart-container">
        {!serviceFilter || !keyFilter ? (
          <div className="dc__metrics__chart-container__placeholder">
            {t("metrics.chart.select_filters")}
          </div>
        ) : isMetricsLoading ? (
          <div className="dc__metrics__chart-container__placeholder">
            Loading...
          </div>
        ) : chartData.length === 0 ? (
          <div className="dc__metrics__chart-container__placeholder">
            {t("metrics.chart.no_data")}
          </div>
        ) : isAggregated ? (
          // Aggregated view - single value with horizontal bar
          <div className="dc__metrics__aggregated-chart">
            <div className="dc__metrics__aggregated-chart__value">
              {chartData[0]?.value.toLocaleString()}
            </div>
            <div className="dc__metrics__aggregated-chart__label">
              {t("metrics.chart.aggregated_value")} ({chartData[0]?.name})
            </div>
            <div className="dc__metrics__aggregated-chart__bar">
              <ResponsiveContainer width="100%" height={60}>
                <BarChart
                  data={chartData}
                  layout="vertical"
                  margin={{ top: 10, right: 30, left: 0, bottom: 10 }}
                >
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="name" hide />
                  <Bar dataKey="value" fill={chartColors[0]} radius={4} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        ) : (
          // Non-aggregated view - vertical bars (horizontal layout) per account
          <div className="dc__metrics__scrollable-chart">
            <ResponsiveContainer width="100%" height={chartHeight}>
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ top: 20, right: 30, left: 150, bottom: 20 }}
              >
                <XAxis
                  type="number"
                  label={{
                    value: t("metrics.chart.value_axis"),
                    position: "insideBottom",
                    offset: -10,
                  }}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={140}
                  tick={{ fontSize: 12 }}
                />
                <Tooltip
                  formatter={(value: number) => [
                    value.toLocaleString(),
                    t("metrics.chart.value_axis"),
                  ]}
                  labelFormatter={(label) => label}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {chartData.map((_, index) => (
                    <Cell
                      key={`cell-${index}`}
                      fill={chartColors[index % chartColors.length]}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </Container>
  );
}

MetricsPage.getLayout = getGlobalExplorerLayout;
