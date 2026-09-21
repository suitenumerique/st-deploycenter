import Link from "next/link";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import { Icon } from "@gouvfr-lasuite/ui-components";
import { useAuth } from "@/features/auth/Auth";

type NavItem = {
  label: string;
  href: string;
  icon: { type: "material"; name: string } | { type: "image"; src: string };
  isActive: (pathname: string) => boolean;
  badge?: string;
};

export const LeftPanel = () => {
  const { t } = useTranslation();
  const router = useRouter();
  const { user } = useAuth();
  const operatorId = router.query.operator_id as string;
  const isSuperUser = user?.is_superuser ?? false;

  const items: NavItem[] = operatorId
    ? [
        {
          label: t("left_panel.organizations"),
          href: `/operators/${operatorId}`,
          icon: { type: "image", src: "/assets/icons/organization.svg" },
          isActive: (pathname) =>
            pathname === "/operators/[operator_id]" ||
            pathname.startsWith("/operators/[operator_id]/organizations"),
        },
        ...(isSuperUser
          ? [
              {
                label: t("left_panel.metrics"),
                href: `/operators/${operatorId}/metrics`,
                icon: { type: "material" as const, name: "bar_chart" },
                isActive: (pathname: string) =>
                  pathname.startsWith("/operators/[operator_id]/metrics"),
                badge: t("left_panel.beta"),
              },
            ]
          : []),
      ]
    : [];

  return (
    <nav className="dc__left-panel" aria-label={t("left_panel.aria_label")}>
      <ul className="dc__left-panel__nav">
        {items.map((item) => {
          const active = item.isActive(router.pathname);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                className={`dc__left-panel__nav__link${
                  active ? " dc__left-panel__nav__link--active" : ""
                }`}
                aria-current={active ? "page" : undefined}
              >
                <span className="dc__left-panel__nav__link__icon">
                  {item.icon.type === "image" ? (
                    <img src={item.icon.src} alt="" />
                  ) : (
                    <Icon name={item.icon.name} />
                  )}
                </span>
                <span>{item.label}</span>
                {item.badge && (
                  <span className="dc__left-panel__nav__link__badge">
                    {item.badge}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
};
