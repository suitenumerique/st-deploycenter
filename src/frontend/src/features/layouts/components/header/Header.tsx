import { DropdownMenu, Spinner } from "@gouvfr-lasuite/ui-kit";
import { Button } from "@openfun/cunningham-react";
import { useAuth, logout } from "@/features/auth/Auth";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchAPI } from "@/features/api/fetchApi";
import { useOperatorContext } from "../GlobalLayout";

export const HeaderIcon = () => {
  const {
    operator,
    operatorQuery: { isLoading: isOperatorLoading },
  } = useOperatorContext();
  return (
    <div className="drive__header__left">
      <div className="drive__header__logo" />
      <div className="drive__header__operator">
        {operator?.name}
        {isOperatorLoading && <Spinner />}
      </div>
    </div>
  );
};

export const HeaderRight = () => {
  const { user } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const { t } = useTranslation();
  return (
    <>
      {user ? (
        <DropdownMenu
          options={[
            {
              label: t("logout"),
              icon: <span className="material-icons">logout</span>,
              callback: logout,
            },
          ]}
          isOpen={isOpen}
          onOpenChange={setIsOpen}
        >
          <Button
            color="primary-text"
            onClick={() => setIsOpen(!isOpen)}
            icon={
              <span className="material-icons">
                {isOpen ? "arrow_drop_up" : "arrow_drop_down"}
              </span>
            }
            iconPosition="right"
          >
            {t("my_account")}
          </Button>
        </DropdownMenu>
      ) : (
        <>
          {/* <LoginButton /> */}
          {/* <LanguagePicker /> */}
        </>
      )}
    </>
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
        color="primary-text"
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
