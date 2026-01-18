import { Badge, Icon, IconSize } from "@gouvfr-lasuite/ui-kit";

export type RpntBadgeProps = {
  rpnt?: string[];
  siret?: string | null;
};

/**
 * RPNT badge component that displays the RPNT compliance status.
 * If siret is provided, the badge is wrapped in a link to Suite Territoriale.
 */
export const RpntBadge = ({ rpnt, siret }: RpntBadgeProps) => {
  let badgeType: "success" | "warning" | "danger";
  let iconName: "check" | "warning" | "close";

  if (!rpnt || rpnt.length === 0) {
    badgeType = "danger";
    iconName = "close";
  } else if (rpnt.includes("a")) {
    badgeType = "success";
    iconName = "check";
  } else if (rpnt.includes("1.a") || rpnt.includes("2.a")) {
    badgeType = "warning";
    iconName = "warning";
  } else {
    badgeType = "danger";
    iconName = "close";
  }

  const badge = (
    <Badge type={badgeType}>
      <Icon name={iconName} size={IconSize.SMALL} />
    </Badge>
  );

  if (siret) {
    return (
      <a
        href={`https://suiteterritoriale.anct.gouv.fr/bienvenue/${siret}`}
        target="_blank"
        rel="noopener noreferrer"
        style={{ display: "inline-flex", alignItems: "center", textDecoration: "none" }}
      >
        {badge}
      </a>
    );
  }

  return badge;
};
