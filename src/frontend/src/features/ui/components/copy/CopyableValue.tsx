import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import { Button } from "@openfun/cunningham-react";

/**
 * A read-only value in a fixed-width font with a copy button (e.g. a nameserver to
 * paste into a registrar's console). Clicking the field also selects it, so the
 * value stays copyable if the clipboard API is unavailable.
 */
export const CopyableValue = ({
  value,
  label,
  width,
}: {
  value: string;
  // Accessible name, when the value alone isn't explicit enough.
  label?: string;
  // Field width in characters; defaults to the value's own length.
  width?: number;
}) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const timeout = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    return () => clearTimeout(timeout.current);
  }, []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // Clipboard blocked (insecure context, permission denied): the field is
      // selectable, so let the user copy it by hand rather than lying with a
      // "Copié" confirmation.
      return;
    }
    setCopied(true);
    clearTimeout(timeout.current);
    timeout.current = setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="dc__copyable">
      <input
        type="text"
        className="dc__copyable__value"
        style={{ width: `${width ?? value.length}ch` }}
        aria-label={label ?? value}
        value={value}
        readOnly
        onFocus={(e) => e.target.select()}
        onClick={(e) => e.currentTarget.select()}
      />
      <Button
        type="button"
        size="small"
        color="tertiary"
        className="dc__copyable__button"
        onClick={handleCopy}
        title={t(copied ? "common.copied" : "common.copy")}
        aria-label={t(copied ? "common.copied" : "common.copy")}
        icon={
          <Icon name={copied ? "check" : "content_copy"} size={IconSize.SMALL} />
        }
      />
    </div>
  );
};
