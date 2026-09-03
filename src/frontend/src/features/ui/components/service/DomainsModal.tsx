import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon, IconSize, Spinner } from "@gouvfr-lasuite/ui-kit";
import { Button, Input, Modal, ModalSize, Select } from "@openfun/cunningham-react";
import { MutateOptions } from "@tanstack/react-query";
import { errorToString } from "@/features/api/APIError";
import { CopyableValue } from "@/features/ui/components/copy/CopyableValue";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { DOMAIN_RE } from "@/features/ui/components/service/domainName";
import { useDomainsChecks } from "@/hooks/useQueries";
import {
  DomainCheck,
  DomainWebsite,
  DomainWebsiteConfig,
  WEBSITE_MODE_DNS_A,
  WEBSITE_MODE_DNS_CNAME,
  WEBSITE_MODE_NONE,
  WEBSITE_MODE_PARKING,
  WEBSITE_MODE_REDIRECT_301,
  WEBSITE_MODE_REDIRECT_302,
} from "@/features/api/Repository";

const PREFIX = "organizations.services.types.domains";

/**
 * The Domains service manager: the organization's own domain names, and what serves
 * each one's website (a parking page we generate, an external server pointed at by
 * an A/CNAME record, or an HTTP redirection). Saved together on submit, as the
 * subscription metadata ({domains, website}).
 *
 * On open it also asks the backend to check each domain: whether it is delegated to
 * our nameservers, and whether its extension is RPNT 1.2 conformant.
 *
 * Unrelated to the ProConnect card's domain modal, which manages routing to an
 * identity provider.
 */
export type DomainsModalProps = {
  isOpen: boolean;
  onClose: () => void;
  organizationId: string;
  instanceName: string;
  domains: string[];
  website: DomainWebsiteConfig;
  onSave: (
    domains: string[],
    website: DomainWebsiteConfig,
    options?: MutateOptions<unknown, unknown, unknown, unknown>
  ) => void;
};

const RPNT_REFERENCE_URL =
  "https://suiteterritoriale.anct.gouv.fr/conformite/referentiel#1.2";

// Presentation only: the label each mode gets, in the order the list shows them.
// "none" is a state a domain sits at, not something to offer.
const MODE_LABELS: [string, string][] = [
  [WEBSITE_MODE_PARKING, "parking"],
  [WEBSITE_MODE_DNS_A, "dns_a"],
  [WEBSITE_MODE_DNS_CNAME, "dns_cname"],
  [WEBSITE_MODE_REDIRECT_301, "redirect_301"],
  [WEBSITE_MODE_REDIRECT_302, "redirect_302"],
];

// A mode the domain cannot use is greyed rather than hidden when seeing it is the
// point — a parking page is what the collectivité would get on a conformant
// extension. The rest simply disappear.
const SHOWN_WHEN_DISALLOWED = [WEBSITE_MODE_PARKING];

/** The delegation and RPNT 1.2 verdicts of one domain. */
const DomainChecks = (props: { check?: DomainCheck; isLoading: boolean }) => {
  const { t } = useTranslation();
  const { check, isLoading } = props;
  const nameserversLabel = () => {
    if (!check) {
      return null;
    }
    if (check.nameservers_valid) {
      return t(`${PREFIX}.modal.checks.dns_valid`);
    }
    if (check.error) {
      return t(`${PREFIX}.modal.checks.dns_error.${check.error}`, {
        defaultValue: t(`${PREFIX}.modal.checks.dns_error.error`),
      });
    }
    return t(`${PREFIX}.modal.checks.dns_mismatch`, {
      nameservers: check.nameservers.join(", "),
    });
  };

  const label = nameserversLabel();

  return (
    <div className="dc__domains-modal__item__checks">
      {isLoading && !check && (
        <span className="dc__domains-modal__check">
          <Spinner size="sm" />
          {t(`${PREFIX}.modal.checks.pending`)}
        </span>
      )}
      {label && (
        <span
          className={`dc__domains-modal__check dc__domains-modal__check--${
            check?.nameservers_valid ? "ok" : "warning"
          }`}
        >
          <Icon
            name={check?.nameservers_valid ? "check_circle" : "warning"}
            size={IconSize.SMALL}
          />
          {label}
        </span>
      )}
      {check && (
        <span
          className={`dc__domains-modal__check dc__domains-modal__check--${
            check.rpnt_1_2_valid ? "ok" : "warning"
          }`}
        >
          <Icon
            name={check.rpnt_1_2_valid ? "check_circle" : "warning"}
            size={IconSize.SMALL}
          />
          {t(
            check.rpnt_1_2_valid
              ? `${PREFIX}.modal.checks.rpnt_valid`
              : `${PREFIX}.modal.checks.rpnt_invalid`
          )}
          <a
            href={RPNT_REFERENCE_URL}
            target="_blank"
            rel="noopener noreferrer"
            title={t(`${PREFIX}.modal.checks.rpnt_link`)}
          >
            <Icon name="info" size={IconSize.SMALL} />
          </a>
        </span>
      )}
    </div>
  );
};

export const DomainsModal = (props: DomainsModalProps) => {
  const { t } = useTranslation();
  const { operatorId } = useOperatorContext();
  const [domains, setDomains] = useState<string[]>(props.domains);
  const [website, setWebsite] = useState<DomainWebsiteConfig>(props.website);
  const [newDomain, setNewDomain] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [saveErrorMessage, setSaveErrorMessage] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const [showSpinner, setShowSpinner] = useState(false);
  const spinnerTimeout = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Each domain is checked once and its verdict kept: adding one only resolves
  // that one, and the badges of the others stay put.
  const {
    checkOf,
    expectedNameservers,
    modesWithTarget,
    isCheckPending,
    checksFailed,
    retryChecks,
  } = useDomainsChecks(operatorId, props.organizationId, domains, props.isOpen);

  useEffect(() => {
    setDomains(props.domains);
  }, [props.domains]);

  useEffect(() => {
    setWebsite(props.website);
  }, [props.website]);

  useEffect(() => {
    return () => clearTimeout(spinnerTimeout.current);
  }, []);

  // Which modes a domain may use is the backend's call, read off the check. Until
  // it answers we offer them all rather than guess: the save is validated anyway.
  const modeOptions = (domain: string) => {
    const allowed = checkOf(domain)?.allowed_modes;
    return MODE_LABELS.filter(
      ([mode]) =>
        !allowed || allowed.includes(mode) || SHOWN_WHEN_DISALLOWED.includes(mode)
    ).map(([mode, key]) => ({
      label: t(`${PREFIX}.modal.modes.${key}`),
      value: mode,
      disabled: !!allowed && !allowed.includes(mode),
    }));
  };

  const needsTarget = (mode: string) => modesWithTarget.includes(mode);

  const entryOf = (domain: string): DomainWebsite =>
    // No stored config and no check yet: leave the select empty rather than
    // pre-selecting a mode the domain may not be allowed to use.
    website[domain] ?? { mode: checkOf(domain)?.default_mode ?? "" };

  const setEntry = (domain: string, entry: DomainWebsite) =>
    setWebsite((prev) => ({ ...prev, [domain]: entry }));

  const handleAdd = () => {
    setAddError(null);
    // The banner shows saveErrorMessage first, so a stale one from an earlier
    // failed save would hide the add error we are about to set.
    setSaveErrorMessage(null);
    const domain = newDomain.trim().toLowerCase();
    if (!DOMAIN_RE.test(domain)) {
      setAddError(t(`${PREFIX}.modal.invalid`));
      return;
    }
    if (domains.includes(domain)) {
      setAddError(t(`${PREFIX}.modal.duplicate`));
      return;
    }
    // No entry: the check will say what this domain defaults to, and a domain the
    // payload does not mention gets the backend's default anyway.
    setDomains((prev) => [...prev, domain].sort());
    setNewDomain("");
  };

  const handleRemove = (domain: string) => {
    setDomains((prev) => prev.filter((d) => d !== domain));
    setWebsite((prev) => {
      const next = { ...prev };
      delete next[domain];
      return next;
    });
  };

  const handleModeChange = (domain: string, mode: string) =>
    setEntry(
      domain,
      needsTarget(mode)
        ? { mode, target: entryOf(domain).target ?? "" }
        : { mode }
    );

  const handleTargetChange = (domain: string, target: string) =>
    setEntry(domain, { ...entryOf(domain), target });

  const targetLabel = (mode: string) => {
    if (mode === WEBSITE_MODE_DNS_A) {
      return `${PREFIX}.modal.website.target_addresses`;
    }
    if (mode === WEBSITE_MODE_DNS_CNAME) {
      return `${PREFIX}.modal.website.target_cname`;
    }
    return `${PREFIX}.modal.website.target_redirect`;
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    // Sent as typed: the backend validates every mode and target, and stores the
    // canonical form it derives. A domain with no mode yet is left out entirely, so
    // it gets the backend's default for its extension.
    const payload: DomainWebsiteConfig = {};
    for (const domain of domains) {
      const entry = entryOf(domain);
      if (!entry.mode) {
        continue;
      }
      payload[domain] = needsTarget(entry.mode)
        ? { mode: entry.mode, target: (entry.target ?? "").trim() }
        : { mode: entry.mode };
    }

    setIsPending(true);
    setSaveErrorMessage(null);
    spinnerTimeout.current = setTimeout(() => setShowSpinner(true), 600);
    props.onSave([...domains].sort(), payload, {
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
        // Surface the backend detail (e.g. a domain already declared by another
        // organization) instead of a generic message.
        setSaveErrorMessage(errorToString(error));
      },
    });
  };

  return (
    <Modal
      size={ModalSize.LARGE}
      title={`${t(`${PREFIX}.modal.title`)} (${props.instanceName})`}
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
            form="domains-form"
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
          {t(`${PREFIX}.modal.description`)}
        </p>
        <form id="domains-form" onSubmit={handleSubmit}>
          <div className="dc__domain-selector">
            {/* The checks are advisory — a failed batch must not block saving,
                but it must not read as "nothing to report" either. */}
            {checksFailed && (
              <div className="dc__service__warning">
                <Icon name="warning" size={IconSize.SMALL} />
                {t(`${PREFIX}.modal.checks.batch_failed`)}
                <Button
                  type="button"
                  size="small"
                  color="tertiary"
                  onClick={retryChecks}
                >
                  {t(`${PREFIX}.modal.checks.retry`)}
                </Button>
              </div>
            )}
            <div className="dc__domain-selector__list dc__domains-modal__list">
              {domains.map((domain) => {
                const entry = entryOf(domain);
                return (
                  <div key={domain} className="dc__domains-modal__item">
                    <div className="dc__domains-modal__item__header">
                      <span className="dc__domain-selector__item__name">
                        {domain}
                      </span>
                      <Button
                        type="button"
                        size="small"
                        color="secondary"
                        className="dc__domain-selector__item__delete"
                        icon={<Icon name="delete" />}
                        title={t(`${PREFIX}.modal.delete_label`)}
                        onClick={() => handleRemove(domain)}
                      />
                    </div>
                    <DomainChecks
                      check={checkOf(domain)}
                      isLoading={isCheckPending(domain)}
                    />
                    <div className="dc__domains-modal__item__website">
                      <Select
                        label={t(`${PREFIX}.modal.website.label`)}
                        options={modeOptions(domain)}
                        // "none" is what a domain we cannot park sits at until it
                        // is pointed somewhere; it is a state, not a choice, so
                        // the select shows nothing rather than offering it. Same
                        // for a domain the check has not answered on yet.
                        value={
                          entry.mode && entry.mode !== WEBSITE_MODE_NONE
                            ? entry.mode
                            : undefined
                        }
                        clearable={false}
                        onChange={(e) =>
                          handleModeChange(domain, e.target.value as string)
                        }
                      />
                      {needsTarget(entry.mode) && (
                        <Input
                          label={t(targetLabel(entry.mode))}
                          placeholder={
                            entry.mode === WEBSITE_MODE_DNS_A
                              ? t(
                                  `${PREFIX}.modal.website.target_addresses_placeholder`
                                )
                              : undefined
                          }
                          value={entry.target ?? ""}
                          onChange={(e) =>
                            handleTargetChange(domain, e.target.value)
                          }
                        />
                      )}
                    </div>
                  </div>
                );
              })}
              {domains.length === 0 && (
                <p className="dc__domain-selector__empty">
                  {t(`${PREFIX}.modal.no_domains`)}
                </p>
              )}
            </div>
            <div className="dc__domain-selector__add">
              <Input
                label=""
                placeholder={t(`${PREFIX}.modal.add_placeholder`)}
                value={newDomain}
                onChange={(e) => setNewDomain(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleAdd();
                  }
                }}
              />
              <Button
                type="button"
                color="secondary"
                onClick={handleAdd}
                disabled={!newDomain.trim().includes(".")}
              >
                {t(`${PREFIX}.modal.add_button`)}
              </Button>
            </div>
            {(saveErrorMessage || addError) && (
              <p className="dc__domain-selector__error">
                {saveErrorMessage ?? addError}
              </p>
            )}
            {/* Only once the backend has told us which ones: these get pasted into
                a registrar, so showing a guess would be worse than showing none. */}
            {expectedNameservers.length > 0 && (
              <div className="dc__domains-modal__nameservers">
                <div className="dc__service__info">
                  <Icon name="info" size={IconSize.SMALL} />
                  <span>{t(`${PREFIX}.modal.nameservers`)}</span>
                </div>
                <div className="dc__domains-modal__nameservers__inputs">
                  {expectedNameservers.map((nameserver) => (
                    <CopyableValue key={nameserver} value={nameserver} />
                  ))}
                </div>
              </div>
            )}
          </div>
        </form>
      </div>
    </Modal>
  );
};
