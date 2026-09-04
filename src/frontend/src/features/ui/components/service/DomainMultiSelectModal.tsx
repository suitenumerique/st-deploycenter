import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon, Spinner } from "@gouvfr-lasuite/ui-kit";
import { Button, Input, Modal, ModalSize } from "@openfun/cunningham-react";
import { MutateOptions } from "@tanstack/react-query";
import { Organization } from "@/features/api/Repository";
import { errorToString } from "@/features/api/APIError";
import { useAuth } from "@/features/auth/Auth";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { DOMAIN_RE } from "@/features/ui/components/service/domainName";
import { useMutationUpdateOrganizationProconnectDomains } from "@/hooks/useQueries";

/**
 * The ProConnect domains manager.
 *
 * Combines routing (which of the organization's routable domains go to this FI)
 * with domain management:
 * - each row shows the domain and where it comes from (routé / DILA / suggéré /
 *   manuel / demandé / écarté)
 * - everyone, superusers included, adds a domain the same way: it goes to
 *   "requested". One write path, one set of behaviours to reason about.
 * - everyone can route any domain the organization may route (the checkboxes),
 *   which the API enforces independently
 * - only superusers get the per-row actions: validate/reject a request, delete a
 *   manual domain, discard a suggestion, restore a discard. A superuser wanting a
 *   domain routed immediately asks for it, then validates its row.
 *
 * Routing edits are saved via `onSave`; domain-management edits are persisted
 * immediately (they mutate the organization's proconnect_domains buckets).
 *
 * Which domains may be routed is decided by the backend
 * (`organization.proconnect_routable`), never re-derived here.
 */
export type DomainMultiSelectModalProps = {
  isOpen: boolean;
  onClose: () => void;
  organization: Organization;
  instanceName: string;
  idpId?: string;
  // Whether the subscription is active — a routed domain is only actually live
  // (en ligne) when it is; otherwise it's configured but offline.
  isActive: boolean;
  // The domains currently routed to this provider.
  routed: string[];
  onSave: (
    domains: string[],
    options?: MutateOptions<unknown, unknown, unknown, unknown>
  ) => void;
};

const PREFIX = "organizations.services.types.proconnect.modal";

const badgeStyle: React.CSSProperties = {
  padding: "2px 8px",
  borderRadius: "4px",
  fontSize: "11px",
  background: "var(--c--theme--colors--greyscale-100)",
  border: "1px solid var(--c--theme--colors--greyscale-200)",
  whiteSpace: "nowrap",
};

// Collectivité types that are in scope of the RPNT service-public.gouv.fr declaration.
const COLLECTIVITE_TYPES = ["commune", "epci", "departement", "region"];

type Buckets = Organization["proconnect_domains"];
const BUCKET_ORDER = [
  "dpnt",
  "candidates",
  "manual",
  "requested",
  "discarded",
] as const;

/**
 * Whether a domain is already in the *deployed* ProConnect allowlist.
 * - "unknown": we don't know the deployed allowlist (`proconnect_prevalidated`
 *   is null, or says nothing about this idp).
 * - "prevalidated": listed → routable now.
 * - "not_yet": allowlist known but this domain isn't in it yet (routing would be
 *   rejected until the next allowlist deploy).
 */
type Prevalidation = "unknown" | "prevalidated" | "not_yet";

// Pre-validation is per-idp: look up this modal's provider (idpId) in the map.
const prevalidationStatus = (
  organization: Organization,
  idpId: string | undefined,
  domain: string
): Prevalidation => {
  const list = idpId ? organization.proconnect_prevalidated?.[idpId] : undefined;
  if (!list) return "unknown";
  return list.includes(domain) ? "prevalidated" : "not_yet";
};

const PREVALIDATION_COLORS: Record<Prevalidation, { bg: string; color: string }> =
  {
    prevalidated: {
      bg: "var(--c--theme--colors--success-100)",
      color: "var(--c--theme--colors--success-700)",
    },
    not_yet: {
      bg: "var(--c--theme--colors--warning-100)",
      color: "var(--c--theme--colors--warning-700)",
    },
    unknown: {
      bg: "var(--c--theme--colors--greyscale-100)",
      color: "var(--c--theme--colors--greyscale-600)",
    },
  };

/** Per-domain provenance breakdown, for display only. */
const domainRows = (pd: Buckets, routed: string[]) => {
  const routedSet = new Set(routed);
  const all = new Set<string>(routed);
  BUCKET_ORDER.forEach((key) => pd[key].forEach((d) => all.add(d)));
  return [...all].sort().map((domain) => {
    const sources = routedSet.has(domain) ? ["routed"] : [];
    BUCKET_ORDER.forEach((key) => {
      if (pd[key].includes(domain)) sources.push(key);
    });
    return { domain, sources };
  });
};

export const DomainMultiSelectModal = (props: DomainMultiSelectModalProps) => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isSuperUser = user?.is_superuser ?? false;
  const { operatorId } = useOperatorContext();
  const { mutate: updateProconnectDomains, isPending: isBucketPending } =
    useMutationUpdateOrganizationProconnectDomains();

  const [selected, setSelected] = useState<string[]>(props.routed);
  const [newDomain, setNewDomain] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [showSpinner, setShowSpinner] = useState(false);
  const [saveErrorMessage, setSaveErrorMessage] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [bucketError, setBucketError] = useState<string | null>(null);
  const spinnerTimeout = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    setSelected(props.routed);
  }, [props.routed]);

  useEffect(() => {
    return () => clearTimeout(spinnerTimeout.current);
  }, []);

  const pd = props.organization.proconnect_domains;
  const rows = domainRows(pd, props.routed);
  // The routable set is the backend's call, including how a discard interacts
  // with a live or DILA domain.
  const routable = new Set(props.organization.proconnect_routable);
  const manual = pd.manual;
  const requested = pd.requested;
  const discarded = pd.discarded;

  const saveDomains = (payload: {
    manual?: string[];
    requested?: string[];
    discarded?: string[];
  }) => {
    setBucketError(null);
    updateProconnectDomains(
      {
        operatorId,
        organizationId: props.organization.id,
        payload,
      },
      // Surface the backend detail (e.g. the domain it rejected as malformed)
      // instead of a generic failure message.
      { onError: (error) => setBucketError(errorToString(error)) }
    );
  };

  const handleDiscard = (domain: string) => {
    // Discarding removes the domain from the routable pool, so drop any pending
    // routing selection for it (otherwise Save would route a discarded domain).
    setSelected((prev) => prev.filter((d) => d !== domain));
    saveDomains({ discarded: [...discarded, domain] });
  };

  const handleRestore = (domain: string) =>
    saveDomains({ discarded: discarded.filter((d) => d !== domain) });

  const toggle = (domain: string) =>
    setSelected((prev) =>
      prev.includes(domain)
        ? prev.filter((d) => d !== domain)
        : [...prev, domain]
    );

  // Everyone asks, superusers included: one path into "requested", and a superuser
  // who wants it routed straight away validates it on its own row. Branching the
  // write on the caller's role gave two behaviours to debug for one button, and
  // "requested" is the only bucket the API opens to every operator member anyway.
  const handleAsk = () => {
    // Guard the Enter-key path too (the button is disabled, but the input isn't),
    // so a pending bucket mutation isn't clobbered by one built from a stale snapshot.
    if (isBucketPending) {
      return;
    }
    setAddError(null);
    // The banner shows saveErrorMessage first, so a stale one from an earlier
    // failed save would hide the add error we are about to set.
    setSaveErrorMessage(null);
    const domain = newDomain.trim().toLowerCase();
    if (!DOMAIN_RE.test(domain)) {
      setAddError(t(`${PREFIX}.invalid`));
      return;
    }
    if (requested.includes(domain)) {
      setAddError(t(`${PREFIX}.already_asked`));
      return;
    }
    // Already held in some other bucket (or live): asking again would do nothing,
    // and whatever the domain needs — restoring a discard, deleting a manual — is
    // an action on its row. The branch is on the domain's state, not on the user.
    if (rows.some((row) => row.domain === domain)) {
      setAddError(t(`${PREFIX}.duplicate`));
      return;
    }
    saveDomains({ requested: [...requested, domain] });
    setNewDomain("");
  };

  const handleValidateAsk = (domain: string) =>
    saveDomains({
      manual: [...manual, domain],
      requested: requested.filter((d) => d !== domain),
    });

  const handleRejectAsk = (domain: string) =>
    saveDomains({ requested: requested.filter((d) => d !== domain) });

  const handleRemoveManual = (domain: string) => {
    saveDomains({ manual: manual.filter((d) => d !== domain) });
    setSelected((prev) => prev.filter((d) => d !== domain));
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsPending(true);
    setSaveErrorMessage(null);
    spinnerTimeout.current = setTimeout(() => setShowSpinner(true), 600);
    props.onSave([...selected].sort(), {
      onSuccess: () => {
        clearTimeout(spinnerTimeout.current);
        setIsPending(false);
        setShowSpinner(false);
        props.onClose();
      },
      onError: (error) => {
        clearTimeout(spinnerTimeout.current);
        setIsPending(false);
        setShowSpinner(false);
        // Surface the backend detail (e.g. ProConnect
        // "attached_email_domain_not_allowed" with the
        // offending domains) instead of a generic message.
        setSaveErrorMessage(errorToString(error));
      },
    });
  };

  const renderRowActions = (domain: string, sources: string[]) => {
    if (!isSuperUser) {
      return null;
    }
    // A currently-routed domain is live: it can't be deleted or discarded until it
    // is un-routed (uncheck it and Save first). This prevents dropping a domain
    // from the buckets while the subscription still routes it.
    const isRouted = sources.includes("routed");
    if (sources.includes("discarded")) {
      return (
        <Button
          type="button"
          size="small"
          color="secondary"
          className="dc__domain-selector__item__delete"
          icon={<Icon name="undo" />}
          title={t(`${PREFIX}.actions.restore`)}
          disabled={isBucketPending}
          onClick={() => handleRestore(domain)}
        />
      );
    }
    if (sources.includes("requested")) {
      return (
        <div style={{ display: "flex", gap: "0.5rem", marginLeft: "auto" }}>
          <Button
            type="button"
            size="small"
            icon={<Icon name="check" />}
            title={t(`${PREFIX}.actions.validate`)}
            disabled={isBucketPending}
            onClick={() => handleValidateAsk(domain)}
          />
          <Button
            type="button"
            size="small"
            color="secondary"
            icon={<Icon name="delete" />}
            title={t(`${PREFIX}.actions.reject`)}
            disabled={isBucketPending}
            onClick={() => handleRejectAsk(domain)}
          />
        </div>
      );
    }
    if (sources.includes("manual")) {
      return (
        <Button
          type="button"
          size="small"
          color="secondary"
          className="dc__domain-selector__item__delete"
          icon={<Icon name="delete" />}
          title={t(
            `${PREFIX}.actions.${
              isRouted ? "unroute_before_delete" : "delete"
            }`
          )}
          disabled={isBucketPending || isRouted}
          onClick={() => handleRemoveManual(domain)}
        />
      );
    }
    // DILA (dpnt) domains are authoritative and cannot be discarded.
    if (sources.includes("candidates") && !sources.includes("dpnt")) {
      return (
        <Button
          type="button"
          size="small"
          color="secondary"
          className="dc__domain-selector__item__delete"
          icon={<Icon name="close" />}
          title={t(
            `${PREFIX}.actions.${
              isRouted ? "unroute_before_discard" : "discard"
            }`
          )}
          disabled={isBucketPending || isRouted}
          onClick={() => handleDiscard(domain)}
        />
      );
    }
    return null;
  };

  return (
    <Modal
      size={ModalSize.LARGE}
      title={t(`${PREFIX}.title`, { instance: props.instanceName })}
      closeOnEsc={!isPending}
      closeOnClickOutside={!isPending}
      isOpen={props.isOpen}
      onClose={isPending ? () => {} : props.onClose}
      rightActions={
        <>
          <Button
            type="button"
            onClick={props.onClose}
            color="secondary"
            disabled={isPending}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            form="domain-multiselect-form"
            disabled={isPending}
            icon={showSpinner ? <Spinner /> : undefined}
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="dc__service__attribute__modal__content">
        <p className="dc__service__attribute__modal__content__help">
          {t(`${PREFIX}.description`)}
        </p>
        <form id="domain-multiselect-form" onSubmit={handleSubmit}>
          <div className="dc__domain-selector">
            <div className="dc__domain-selector__list">
              {rows.map((row) => {
                const isRoutable = routable.has(row.domain);
                const prevalidation = prevalidationStatus(
                  props.organization,
                  props.idpId,
                  row.domain
                );
                const pillColors = PREVALIDATION_COLORS[prevalidation];
                const isEnLigne =
                  row.sources.includes("routed") && props.isActive;
                // Discarded domains are excluded from the allowlist entirely, so
                // their status is moot; and a live (en ligne) domain doesn't need
                // an "unknown" pre-validation pill (it is already live).
                const showPill =
                  !row.sources.includes("discarded") &&
                  !(isEnLigne && prevalidation === "unknown");
                // A live domain not declared on service-public.gouv.fr (no DILA
                // source) should be declared — only for collectivité org types.
                const needsDilaDeclaration =
                  isEnLigne &&
                  !row.sources.includes("dpnt") &&
                  COLLECTIVITE_TYPES.includes(props.organization.type);
                // A "not yet pre-validated" domain can't be routed (it would be
                // rejected), so its checkbox is disabled — unless it's already
                // selected, so a live domain can still be un-routed.
                const notYetBlocked =
                  prevalidation === "not_yet" && !selected.includes(row.domain);
                return (
                  <div key={row.domain} className="dc__domain-selector__item">
                    <input
                      type="checkbox"
                      id={`domain-${row.domain}`}
                      checked={selected.includes(row.domain)}
                      disabled={!isRoutable || notYetBlocked}
                      onChange={() => toggle(row.domain)}
                    />
                    {/* The visible domain labels the checkbox, so each control
                        has a unique accessible name. */}
                    <label
                      htmlFor={`domain-${row.domain}`}
                      className="dc__domain-selector__item__name"
                    >
                      {row.domain}
                    </label>
                    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                      {row.sources
                        .filter(
                          // A live (routed + active) domain is beyond "candidate"
                          // — don't show that origin badge alongside "en ligne".
                          (source) =>
                            !(
                              source === "candidates" &&
                              row.sources.includes("routed") &&
                              props.isActive
                            )
                        )
                        .map((source) => (
                          <span key={source} style={badgeStyle}>
                            {source === "routed"
                              ? t(
                                  `${PREFIX}.sources.routed_${
                                    props.isActive ? "online" : "offline"
                                  }`
                                )
                              : t(`${PREFIX}.sources.${source}`, {
                                  defaultValue: source,
                                })}
                          </span>
                        ))}
                      {showPill && (
                        <span
                          style={{
                            ...badgeStyle,
                            background: pillColors.bg,
                            color: pillColors.color,
                            border: "none",
                          }}
                          title={
                            prevalidation === "not_yet"
                              ? t(`${PREFIX}.prevalidation.not_yet_title`)
                              : undefined
                          }
                        >
                          {t(`${PREFIX}.prevalidation.${prevalidation}`)}
                        </span>
                      )}
                      {needsDilaDeclaration && (
                        <span
                          style={{
                            ...badgeStyle,
                            background:
                              "var(--c--theme--colors--warning-100)",
                            color: "var(--c--theme--colors--warning-700)",
                            border: "none",
                          }}
                          title={t(`${PREFIX}.dila_declaration.title`)}
                        >
                          {t(`${PREFIX}.dila_declaration.label`)}
                        </span>
                      )}
                    </div>
                    {renderRowActions(row.domain, row.sources)}
                  </div>
                );
              })}
              {rows.length === 0 && (
                <p className="dc__domain-selector__empty">
                  {t(`${PREFIX}.empty`)}
                </p>
              )}
            </div>
            <div className="dc__domain-selector__add">
              <Input
                label=""
                placeholder={t(`${PREFIX}.ask_placeholder`)}
                value={newDomain}
                disabled={isBucketPending}
                onChange={(e) => setNewDomain(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleAsk();
                  }
                }}
              />
              <Button
                type="button"
                color="secondary"
                onClick={handleAsk}
                disabled={isBucketPending || !newDomain.trim().includes(".")}
              >
                {t(`${PREFIX}.ask_button`)}
              </Button>
            </div>
            {(saveErrorMessage || addError || bucketError) && (
              <p className="dc__domain-selector__error">
                {saveErrorMessage ??
                  addError ??
                  bucketError ??
                  t("api.error.unexpected")}
              </p>
            )}
          </div>
        </form>
      </div>
    </Modal>
  );
};
