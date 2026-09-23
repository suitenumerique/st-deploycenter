import { DropdownMenu, Spinner, UserMenu } from "@gouvfr-lasuite/ui-components";
import { Button } from "@gouvfr-lasuite/ui-components";
import { useAuth, logout } from "@/features/auth/Auth";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchAPI } from "@/features/api/fetchApi";
import { useOperatorContext } from "../GlobalLayout";
import Link from "next/link";

export const HeaderIcon = () => {
  const {
    operator,
    operatorQuery: { isLoading: isOperatorLoading },
  } = useOperatorContext();
  return (
    <div className="drive__header__left">
      <Link href="/" className="drive__header__logo" />
      <Link
        href={operator ? `/operators/${operator.id}` : "/"}
        className="drive__header__operator"
      >
        {operator?.name}
        {isOperatorLoading && <Spinner />}
      </Link>
    </div>
  );
};

// The library's own profile menu: avatar trigger, identity block, logout, and a
// full-screen variant on mobile. It renders nothing when there is no user.
// Its avatar splits full_name ?? email, so neither may reach it as null: a
// superuser logged in through the Django admin has no email (the session is
// shared, the admin being served on the same domain).
export const HeaderRight = () => {
  const { user } = useAuth();
  return (
    <UserMenu
      user={
        user
          ? { full_name: user.full_name || undefined, email: user.email ?? "" }
          : null
      }
      logout={logout}
    />
  );
};

export const LanguagePicker = () => {
  const [isOpen, setIsOpen] = useState(false);
  const { i18n } = useTranslation();
  const { user } = useAuth();
  // We must set the language to lowercase because django does not use "en-US", but "en-us".
  const [selectedValues, setSelectedValues] = useState([
    user?.language || i18n.language.toLowerCase(),
  ]);
  const languages = [
    { label: "Français", value: "fr-fr" },
    { label: "English", value: "en-us" },
  ];

  // Make sure the language of the ui is in the same language as the user.
  useEffect(() => {
    if (user?.language) {
      i18n.changeLanguage(user.language).catch((err) => {
        console.error("Error changing language", err);
      });
    }
  }, [user?.language]);

  return (
    <DropdownMenu
      options={languages}
      isOpen={isOpen}
      onOpenChange={setIsOpen}
      onSelectValue={(value) => {
        setSelectedValues([value]);
        i18n.changeLanguage(value).catch((err) => {
          console.error("Error changing language", err);
        });
        if (user) {
          fetchAPI(`users/${user.id}/`, {
            method: "PATCH",
            body: JSON.stringify({ language: value }),
          });
        }
      }}
      selectedValues={selectedValues}
    >
      <Button
        onClick={() => setIsOpen(!isOpen)}
        variant="tertiary"
        className="c__language-picker"
        icon={
          <span className="material-icons">
            {isOpen ? "arrow_drop_up" : "arrow_drop_down"}
          </span>
        }
        iconPosition="right"
      >
        <span className="material-icons">translate</span>
        <span className="c__language-picker__label">
          {languages.find((lang) => lang.value === selectedValues[0])?.label}
        </span>
      </Button>
    </DropdownMenu>
  );
};
