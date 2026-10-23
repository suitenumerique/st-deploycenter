import { useTranslation } from "react-i18next";
import { Button, Icon, IconSize } from "@gouvfr-lasuite/ui-components";

/**
 * The url comes from the service config, so only a web link is ever followed.
 */
export const isWebUrl = (url?: string): url is string =>
  !!url && /^https?:\/\//i.test(url);

/**
 * The link to a service's documentation (`help_center_url` in its config), laid
 * out like the "go to the service" link of a card. Nothing when there is none.
 */
export const ServiceHelpLink = ({ url }: { url?: string }) => {
  const { t } = useTranslation();
  if (!isWebUrl(url)) {
    return null;
  }
  return (
    <div className="dc__service__block__goto">
      <a target="_blank" rel="noopener noreferrer" href={url}>
        {t("organizations.services.help_center")}
      </a>
      <Button
        variant="secondary"
        color="neutral"
        size="nano"
        href={url}
        target="_blank"
        icon={<Icon name="open_in_new" size={IconSize.X_SMALL} />}
      ></Button>
    </div>
  );
};
