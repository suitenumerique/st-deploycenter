import Link from "next/link";
import { useRouter } from "next/router";
import { useTranslation } from "react-i18next";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import { useAuth } from "@/features/auth/Auth";
import { LogoutButton } from "@/features/auth/components/LogoutButton";
import { LoginButton } from "@/features/auth/components/LoginButton";

type NavItem = {
  label: string;
  href: string;
  icon: { type: "material"; name: string } | { type: "image"; src: string };
  isActive: (pathname: string) => boolean;
};

export const LeftPanel = () => {
  const { t } = useTranslation();
  const router = useRouter();
  const { user } = useAuth();
  const operatorId = router.query.operator_id as string;

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
        {
          label: t("left_panel.metrics"),
          href: `/operators/${operatorId}/metrics`,
          icon: { type: "material", name: "bar_chart" },
          isActive: (pathname) =>
            pathname.startsWith("/operators/[operator_id]/metrics"),
        },
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
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="dc__left-panel__auth">
        {user ? <LogoutButton /> : <LoginButton />}
      </div>
    </nav>
  );
};
