import { useRouter } from "next/router";
import { getGlobalExplorerLayout } from "@/features/layouts/components/GlobalLayout";
import { Container } from "@/features/layouts/components/container/Container";
import { useTranslation } from "react-i18next";
import { Button, Pagination, Select } from "@gouvfr-lasuite/ui-components";
import { Icon, Spinner } from "@gouvfr-lasuite/ui-components";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import {
  addToast,
  ToasterItem,
} from "@/features/ui/components/toaster/Toaster";
import { errorToString } from "@/features/api/APIError";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useOperatorMetricKeys,
  useOperatorMetrics,
  useOperatorOrganizations,
  useOperatorServices,
} from "@/hooks/useQueries";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  AggregatedMetric,
  getAllOperatorMetrics,
  GroupedMetricsResponse,
  MetricsOrderBy,
  MetricsParams,
  MetricsResponse,
} from "@/features/api/Repository";

type Unit = "" | "MB" | "GB" | "TB";
type Aggregation = "" | "sum" | "avg";

const UNITS: Unit[] = ["MB", "GB", "TB"];

const UNIT_DIVISORS: Record<Exclude<Unit, "">, number> = {
  MB: 1024 ** 2,
  GB: 1024 ** 3,
  TB: 1024 ** 4,
};

// One page of bars, kept to what a chart can still be read at. The axis sits at
// the bottom of the chart, so a page that needs scrolling is a page whose scale
// is off screen while you read it.
const PAGE_SIZE = 25;

const BAR_HEIGHT = 32;
const MIN_CHART_HEIGHT = 240;

// A single series gets a single colour: one colour per bar would read as six
// categories that do not exist.
const BAR_COLOR = "#000091";

// The y axis reserves this much room, so labels are cut to what fits rather
// than wrapping onto two lines. The tooltip still carries the full name.
const LABEL_WIDTH = 180;
const LABEL_MAX_CHARS = 20;

const ORDER_BY_VALUES: MetricsOrderBy[] = ["organization", "value", "-value"];

type Filters = {
  service: string;
  key: string;
  organizations: string[];
  accountType: string;
  aggregation: Aggregation;
  unit: Unit;
  orderBy: MetricsOrderBy;
};

const EMPTY_FILTERS: Filters = {
  service: "",
  key: "",
  organizations: [],
  accountType: "",
  aggregation: "",
  unit: "",
  orderBy: "organization",
};

const firstValue = (value: string | string[] | undefined) =>
  (Array.isArray(value) ? value[0] : value) ?? "";

const truncateLabel = (label: string) =>
  label.length > LABEL_MAX_CHARS
    ? `${label.slice(0, LABEL_MAX_CHARS - 1)}…`
    : label;

/**
 * One CSV field.
 *
 * Always quoted, so a comma, a newline or a semicolon inside an organization
 * name cannot shift the following columns. A leading =, +, - or @ is prefixed
 * with a quote: spreadsheets read those as formulas, and the names here come
 * from an external dataset.
 */
const csvField = (value: string | number) => {
  const text = String(value ?? "");
  const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
};

const csvRows = (rows: (string | number)[][]) =>
  rows.map((row) => row.map(csvField).join(",")).join("\r\n");

const downloadCsv = (filename: string, csv: string) => {
  // The BOM is what makes Excel read the file as UTF-8 rather than latin-1,
  // which is the difference between "Méteren" and "MÃ©teren".
  const blob = new Blob([`﻿${csv}`], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

export default function MetricsPage() {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const { t, i18n } = useTranslation();

  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [organizationSearch, setOrganizationSearch] = useState("");

  // Filters live in the URL so a chart can be linked to and survives a reload.
  // Read once, when the router hands us the real query, then write on change.
  // This is state and not a ref on purpose: the writing effect below must not
  // run in the same commit as this one, where it would still see empty filters
  // and erase the very query we are reading.
  const [isInitialized, setIsInitialized] = useState(false);
  useEffect(() => {
    if (!router.isReady || isInitialized) {
      return;
    }

    const query = router.query;
    const organizations = firstValue(query.organizations);
    const aggregation = firstValue(query.agg);
    const unit = firstValue(query.unit);
    const orderBy = firstValue(query.order_by);
    const pageParam = Number.parseInt(firstValue(query.page), 10);

    setFilters({
      service: firstValue(query.service),
      key: firstValue(query.key),
      organizations: organizations ? organizations.split(",") : [],
      accountType: firstValue(query.account_type),
      // Anything else in the URL is somebody's typo, not a filter.
      aggregation: (["sum", "avg"].includes(aggregation)
        ? aggregation
        : "") as Aggregation,
      unit: (UNITS.includes(unit as Unit) ? unit : "") as Unit,
      orderBy: (ORDER_BY_VALUES.includes(orderBy as MetricsOrderBy)
        ? orderBy
        : "organization") as MetricsOrderBy,
    });
    setPage(pageParam > 0 ? pageParam : 1);
    setIsInitialized(true);
  }, [router.isReady, router.query, isInitialized]);

  useEffect(() => {
    if (!isInitialized) {
      return;
    }
    const query: Record<string, string> = { operator_id: operatorId };
    if (filters.service) query.service = filters.service;
    if (filters.key) query.key = filters.key;
    if (filters.organizations.length > 0) {
      query.organizations = filters.organizations.join(",");
    }
    if (filters.accountType) query.account_type = filters.accountType;
    if (filters.aggregation) query.agg = filters.aggregation;
    if (filters.unit) query.unit = filters.unit;
    // "organization" is the default, so it stays out of the URL.
    if (filters.orderBy !== "organization") query.order_by = filters.orderBy;
    if (page > 1) query.page = page.toString();

    router.replace({ pathname: router.pathname, query }, undefined, {
      shallow: true,
    });
    // `router` is deliberately not a dependency: its identity changes on every
    // navigation, so this effect would loop against the replace it just made.
  }, [filters, page, operatorId, isInitialized]);

  // Any filter change invalidates the page we were on. A Select that re-emits
  // the value it already holds — which happens when its options arrive and it
  // remounts — is not a change, and must not send a deep link back to page 1.
  const updateFilters = useCallback(
    (update: Partial<Filters>) => {
      const keys = Object.keys(update) as (keyof Filters)[];
      const changed = keys.some((key) => {
        const next = update[key];
        const current = filters[key];
        return Array.isArray(next) && Array.isArray(current)
          ? next.length !== current.length ||
              next.some((value, index) => value !== current[index])
          : next !== current;
      });
      if (!changed) {
        return;
      }
      setFilters((previous) => ({ ...previous, ...update }));
      setPage(1);
    },
    [filters]
  );

  const { data: operatorServices } = useOperatorServices(operatorId);

  // Only the keys this operator has data for: a hardcoded list offers keys that
  // can only draw an empty chart.
  const { data: metricKeys } = useOperatorMetricKeys(operatorId, filters.service);

  // A Select drops a value it cannot find among its options, and calls onChange
  // with nothing. Both of these lists arrive after the first render, so a value
  // restored from the URL has to be carried until its list catches up.
  const serviceOptions = useMemo(() => {
    // Service ids are numbers in the API and strings in the URL.
    const options = (operatorServices?.results || []).map((service) => ({
      label: service.name,
      value: String(service.id),
    }));
    if (
      filters.service &&
      !options.some((option) => option.value === filters.service)
    ) {
      options.unshift({ label: filters.service, value: filters.service });
    }
    return [
      { label: t("metrics.filters.service_placeholder"), value: "" },
      ...options,
    ];
  }, [operatorServices, filters.service, t]);

  const keyOptions = useMemo(() => {
    const options = (metricKeys?.results || []).map(({ key }) => ({
      label: key,
      value: key,
    }));
    if (filters.key && !options.some((option) => option.value === filters.key)) {
      options.unshift({ label: filters.key, value: filters.key });
    }
    return [
      { label: t("metrics.filters.key_placeholder"), value: "" },
      ...options,
    ];
  }, [metricKeys, filters.key, t]);

  // The account types the selected key has data for. A type is required: a
  // service can report a key both per account and for the whole organization,
  // and adding those up would count the same usage twice.
  const keyAccountTypes = useMemo(
    () =>
      metricKeys?.results.find(({ key }) => key === filters.key)
        ?.account_types,
    [metricKeys, filters.key]
  );

  // One type leaves nothing to choose; a type the key has no data for (after
  // a key change) is dropped.
  useEffect(() => {
    if (!isInitialized || !keyAccountTypes) {
      return;
    }
    if (keyAccountTypes.includes(filters.accountType)) {
      return;
    }
    setFilters((previous) => ({
      ...previous,
      accountType: keyAccountTypes.length === 1 ? keyAccountTypes[0] : "",
    }));
  }, [isInitialized, keyAccountTypes, filters.accountType]);

  const accountTypeOptions = useMemo(() => {
    const types = keyAccountTypes ? [...keyAccountTypes] : [];
    if (filters.accountType && !types.includes(filters.accountType)) {
      types.unshift(filters.accountType);
    }
    return [
      { label: t("metrics.filters.account_type_placeholder"), value: "" },
      ...types.map((type) => ({
        label: t(`metrics.account_types.${type}`, { defaultValue: type }),
        value: type,
      })),
    ];
  }, [keyAccountTypes, filters.accountType, t]);

  const searchTimeout = useRef<NodeJS.Timeout | null>(null);
  useEffect(() => {
    return () => {
      if (searchTimeout.current) {
        clearTimeout(searchTimeout.current);
      }
    };
  }, []);

  const onOrganizationSearch = useCallback((value: string | undefined) => {
    if (searchTimeout.current) {
      clearTimeout(searchTimeout.current);
    }
    searchTimeout.current = setTimeout(
      () => setOrganizationSearch((value ?? "").trim()),
      300
    );
  }, []);

  // The dropdown shows a page of organizations at a time, so it searches the
  // API rather than filtering a list it never received in full.
  const { data: organizations } = useOperatorOrganizations(operatorId, {
    search: organizationSearch,
  });

  // A selected organization has to keep its name once a search stops returning
  // it, or the filter would show a bare UUID.
  const [organizationNames, setOrganizationNames] = useState<
    Record<string, string>
  >({});
  useEffect(() => {
    if (!organizations?.results) {
      return;
    }
    setOrganizationNames((previous) => {
      const next = { ...previous };
      for (const organization of organizations.results) {
        next[organization.id] = organization.name;
      }
      return next;
    });
  }, [organizations]);

  const organizationOptions = useMemo(() => {
    const options = (organizations?.results || []).map((organization) => ({
      label: organization.name,
      value: organization.id,
    }));
    const listed = new Set(options.map((option) => option.value));
    // Keep the current selection reachable (and unselectable) whatever the search.
    const selected = filters.organizations
      .filter((id) => !listed.has(id))
      .map((id) => ({ label: organizationNames[id] ?? id, value: id }));
    return [...selected, ...options];
  }, [organizations, filters.organizations, organizationNames]);

  // One organization is a drill-down into its accounts; none or several only
  // compare as one bar per organization.
  const isGroupedByOrganization =
    filters.organizations.length !== 1 && !filters.aggregation;

  const metricsParams: MetricsParams | null = useMemo(() => {
    if (!filters.service || !filters.key || !filters.accountType) return null;

    return {
      key: filters.key,
      service: filters.service,
      organizations:
        filters.organizations.length > 0 ? filters.organizations : undefined,
      account_type: filters.accountType,
      agg: filters.aggregation || undefined,
      group_by: isGroupedByOrganization ? "organization" : undefined,
      order_by: filters.orderBy,
      page,
      page_size: PAGE_SIZE,
    };
  }, [filters, isGroupedByOrganization, page]);

  const {
    data: metricsData,
    isLoading: isMetricsLoading,
    isError: isMetricsError,
  } = useOperatorMetrics(operatorId, metricsParams);

  const isAggregated = !!metricsData && "aggregation" in metricsData;
  const isGrouped = !!metricsData && "grouped_by" in metricsData;

  const locale = i18n.language;

  const formatValue = useCallback(
    (value: number) =>
      new Intl.NumberFormat(
        locale,
        // A byte count read in TB is a fraction: rounding it to two decimals
        // would print every small value as "0".
        value !== 0 && Math.abs(value) < 1
          ? { maximumSignificantDigits: 3 }
          : { maximumFractionDigits: 2 }
      ).format(value),
    [locale]
  );

  const formatWithUnit = useCallback(
    (value: number) =>
      filters.unit ? `${formatValue(value)} ${filters.unit}` : formatValue(value),
    [filters.unit, formatValue]
  );

  // The export walks every page, so it reports how far it has got rather than
  // leaving the button silent through twenty round trips.
  const [exportProgress, setExportProgress] = useState<number | null>(null);
  const isExporting = exportProgress !== null;

  const onExportCsv = useCallback(async () => {
    if (!metricsParams || isExporting) {
      return;
    }
    setExportProgress(0);
    try {
      // metricsParams still carries the on-screen page and page size; the
      // export overrides both, walking from page 1 at the largest page the API
      // serves.
      const data = await getAllOperatorMetrics(
        operatorId,
        metricsParams,
        (loaded, total) =>
          setExportProgress(total > 0 ? Math.round((loaded / total) * 100) : 100)
      );

      // The raw stored value, not the unit-converted and locale-formatted one
      // on the chart: a CSV is for recomputing from, and "1 234,5" in a French
      // locale is two columns to a spreadsheet reading commas.
      let rows: (string | number)[][];
      if ("aggregation" in data) {
        rows = [
          ["key", "service_id", "aggregation", "value", "count"],
          [
            data.key,
            data.service_id,
            data.aggregation,
            data.value,
            data.count,
          ],
        ];
      } else if ("grouped_by" in data) {
        rows = [
          ["organization_id", "organization", "value"],
          ...data.results.map((item) => [
            item.organization.id,
            item.organization.name,
            item.value,
          ]),
        ];
      } else {
        rows = [
          [
            "organization_id",
            "organization",
            "account_id",
            "account_email",
            "account_external_id",
            "account_type",
            "key",
            "value",
            "timestamp",
          ],
          ...data.results.map((metric) => [
            metric.organization.id,
            metric.organization.name,
            metric.account?.id ?? "",
            metric.account?.email ?? "",
            metric.account?.external_id ?? "",
            metric.account?.type ?? "",
            metric.key,
            metric.value,
            metric.timestamp,
          ]),
        ];
      }

      const stamp = new Date().toISOString().slice(0, 10);
      downloadCsv(
        `metrics-${filters.key}-${filters.service}-${stamp}.csv`,
        csvRows(rows)
      );
    } catch (error) {
      // A page can fail mid-walk. Without this the promise rejects out of an
      // onClick handler: nothing is downloaded and the button just returns to
      // its normal label, which reads as success.
      addToast(
        <ToasterItem type="error">
          <span>{errorToString(error)}</span>
        </ToasterItem>
      );
    } finally {
      setExportProgress(null);
    }
  }, [metricsParams, isExporting, operatorId, filters.key, filters.service]);

  // A column of "1 200 000 000" is unreadable as an axis; "1,2 Md" is.
  const formatTick = useCallback(
    (value: number) =>
      new Intl.NumberFormat(locale, {
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value),
    [locale]
  );

  const resultsCount = metricsData?.count ?? 0;

  const pagesCount = isAggregated ? 1 : Math.ceil(resultsCount / PAGE_SIZE);

  // A page past the end is a 404 from the paginator, which leaves no data to
  // size the pager from, so the pager is hidden and the only way out of the
  // error would be to edit the URL. Deep links carry the page, so this is one
  // stale bookmark away. Fall back to the first page, which always exists.
  useEffect(() => {
    if (isMetricsError && page > 1) {
      setPage(1);
    }
  }, [isMetricsError, page]);

  const chartData = useMemo(() => {
    if (!metricsData) return [];

    const convert = (raw: string) => {
      const parsed = parseFloat(raw);
      return filters.unit ? parsed / UNIT_DIVISORS[filters.unit] : parsed;
    };

    if (isAggregated) {
      const aggregated = metricsData as AggregatedMetric;
      return [
        {
          name: t(
            `metrics.filters.aggregation_options.${aggregated.aggregation}`
          ),
          value: convert(aggregated.value),
        },
      ];
    }

    if (isGrouped) {
      return (metricsData as GroupedMetricsResponse).results.map((item) => ({
        name: item.organization.name,
        value: convert(item.value),
      }));
    }

    return (metricsData as MetricsResponse).results.map((metric) => ({
      name: metric.account
        ? metric.account.email || metric.account.external_id
        : metric.organization.name,
      value: convert(metric.value),
    }));
  }, [metricsData, isAggregated, isGrouped, t, filters.unit]);

  const chartHeight = Math.max(
    MIN_CHART_HEIGHT,
    chartData.length * BAR_HEIGHT + 60
  );

  const hasFilters = !!filters.service && !!filters.key && !!filters.accountType;

  const serviceHasNoKeys =
    !!filters.service && metricKeys && metricKeys.results.length === 0;

  return (
    <Container
      titleNode={
        <>
          {/* Metrics is a top level page, so it is its own root. */}
          <Breadcrumbs
            items={[
              {
                content: (
                  <span className="c__breadcrumbs__button">
                    <Icon name="bar_chart" />
                    {t("metrics.title")}
                  </span>
                ),
              },
            ]}
          />
          <div className="dc__container__content__subtitle">
            {t("metrics.subtitle")}
          </div>
        </>
      }
    >
      <div className="dc__metrics__filters">
        <Select
          label={t("metrics.filters.service")}
          value={filters.service}
          onChange={(e) =>
            // The keys are per service, so the current one may not exist here.
            updateFilters({
              service: (e.target.value as string) || "",
              key: "",
              accountType: "",
            })
          }
          options={serviceOptions}
        />

        <Select
          label={t("metrics.filters.key")}
          value={filters.key}
          onChange={(e) =>
            // The account types are per key, so the current one may not apply.
            updateFilters({ key: (e.target.value as string) || "", accountType: "" })
          }
          disabled={!filters.service || serviceHasNoKeys}
          text={serviceHasNoKeys ? t("metrics.filters.key_empty") : undefined}
          options={keyOptions}
        />

        {/* The operator can hold tens of thousands of organizations, so the
            dropdown's own search box queries the API rather than filtering a
            list it never received in full. The kit filters the options it holds
            by the same text on top of that, which only ever narrows a result
            the server already matched.

            Rendering waits for the first page: the searchable Select memoizes
            its visible options on (selection, search text) alone (ui-components
            1.1.1, select/multi-searchable), so options that land after it mounts
            are never picked up, and opening it would show an empty menu until
            you typed. Mounting it with the list already in hand avoids that
            without a remount, which would eat the text being typed. */}
        {organizations ? (
          <Select
            label={t("metrics.filters.organizations")}
            multi
            searchable
            onSearchInputChange={(e) => onOrganizationSearch(e.target.value)}
            value={filters.organizations}
            onChange={(e) =>
              updateFilters({ organizations: (e.target.value as string[]) || [] })
            }
            options={organizationOptions}
          />
        ) : (
          <Select
            label={t("metrics.filters.organizations")}
            multi
            disabled
            options={[]}
          />
        )}

        <Select
          label={t("metrics.filters.account_type")}
          value={filters.accountType}
          onChange={(e) =>
            updateFilters({ accountType: (e.target.value as string) || "" })
          }
          disabled={!filters.key}
          options={accountTypeOptions}
        />

        <Select
          label={t("metrics.filters.aggregation")}
          value={filters.aggregation}
          onChange={(e) =>
            updateFilters({
              aggregation: ((e.target.value as string) || "") as Aggregation,
            })
          }
          options={[
            { label: t("metrics.filters.aggregation_options.none"), value: "" },
            {
              label: t("metrics.filters.aggregation_options.sum"),
              value: "sum",
            },
            {
              label: t("metrics.filters.aggregation_options.avg"),
              value: "avg",
            },
          ]}
        />

        <Select
          label={t("metrics.filters.unit")}
          value={filters.unit}
          onChange={(e) =>
            updateFilters({ unit: ((e.target.value as string) || "") as Unit })
          }
          options={[
            { label: t("metrics.filters.unit_options.none"), value: "" },
            ...UNITS.map((unit) => ({ label: unit, value: unit })),
          ]}
        />

        {/* An aggregation is one number, so there is nothing to order. */}
        <Select
          label={t("metrics.filters.order_by")}
          value={filters.orderBy}
          disabled={!!filters.aggregation}
          onChange={(e) =>
            updateFilters({
              orderBy: ((e.target.value as string) ||
                "organization") as MetricsOrderBy,
            })
          }
          options={ORDER_BY_VALUES.map((value) => ({
            label: t(`metrics.filters.order_by_options.${value}`),
            value,
          }))}
        />
      </div>

      {/* What the bars are: "no aggregation" still sums each organization. */}
      {hasFilters && !!metricsData && !isMetricsError && (
        <div className="dc__metrics__results-count">
          <span>
            {isAggregated
              ? t("metrics.chart.mode_aggregated", { count: resultsCount })
              : isGrouped
                ? t("metrics.chart.mode_grouped", { count: resultsCount })
                : t("metrics.chart.mode_accounts", { count: resultsCount })}
          </span>
          {/* Exports every row the filters match, not the page on screen. */}
          <Button
            size="small"
            color="brand"
            variant="tertiary"
            icon={<Icon name="download" />}
            disabled={isExporting}
            onClick={onExportCsv}
          >
            {isExporting
              ? t("metrics.export.in_progress", { percent: exportProgress })
              : t("metrics.export.csv")}
          </Button>
        </div>
      )}

      <div className="dc__metrics__chart-container">
        {!hasFilters ? (
          <div className="dc__metrics__chart-container__placeholder">
            {t("metrics.chart.select_filters")}
          </div>
        ) : isMetricsError ? (
          <div className="dc__metrics__chart-container__placeholder">
            {t("metrics.chart.error")}
          </div>
        ) : isMetricsLoading ? (
          <div className="dc__metrics__chart-container__placeholder">
            <Spinner />
          </div>
        ) : chartData.length === 0 ? (
          <div className="dc__metrics__chart-container__placeholder">
            {t("metrics.chart.no_data")}
          </div>
        ) : isAggregated ? (
          <div className="dc__metrics__aggregated-chart">
            <div className="dc__metrics__aggregated-chart__value">
              {chartData[0] !== undefined ? formatWithUnit(chartData[0].value) : ""}
            </div>
            <div className="dc__metrics__aggregated-chart__label">
              {t("metrics.chart.aggregated_value")} ({chartData[0]?.name})
            </div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={chartHeight}>
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 8, right: 32, left: 0, bottom: 24 }}
            >
              {/* Vertical lines only: they carry the scale, the rows carry the labels. */}
              <CartesianGrid horizontal={false} strokeDasharray="3 3" />
              <XAxis
                type="number"
                label={{
                  value: filters.unit
                    ? `${t("metrics.chart.value_axis")} (${filters.unit})`
                    : t("metrics.chart.value_axis"),
                  position: "insideBottom",
                  offset: -12,
                }}
                tickFormatter={formatTick}
              />
              <YAxis
                type="category"
                dataKey="name"
                width={LABEL_WIDTH}
                tick={{ fontSize: 12 }}
                tickFormatter={truncateLabel}
              />
              <Tooltip
                formatter={(value: number) => [
                  formatWithUnit(value),
                  t("metrics.chart.value_axis"),
                ]}
                labelFormatter={(label) => label}
              />
              <Bar dataKey="value" fill={BAR_COLOR} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {pagesCount > 1 && (
        <div className="dc__metrics__pagination">
          <Pagination
            page={page}
            pagesCount={pagesCount}
            pageSize={PAGE_SIZE}
            onPageChange={setPage}
          />
        </div>
      )}
    </Container>
  );
}

MetricsPage.getLayout = getGlobalExplorerLayout;
