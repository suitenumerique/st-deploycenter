import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/features/auth/Auth";

interface FeedbackWidgetProps {
  widget?: string;
}

export function FeedbackWidget({ widget = "feedback" }: FeedbackWidgetProps) {
  const { t } = useTranslation();
  const { user } = useAuth();

  const apiUrl = process.env.NEXT_PUBLIC_FEEDBACK_WIDGET_API_URL;
  const widgetPath = process.env.NEXT_PUBLIC_FEEDBACK_WIDGET_PATH;
  const channel = process.env.NEXT_PUBLIC_FEEDBACK_WIDGET_CHANNEL;

  const title: string = t("feedback.title");
  const placeholder: string = t("feedback.placeholder");
  const emailPlaceholder: string = t("feedback.email_placeholder");
  const submitText: string = t("feedback.submit");
  const successText: string = t("feedback.success");
  const successText2: string = t("feedback.success2");
  const closeLabel: string = t("feedback.close");

  useEffect(() => {
    if (!channel || !apiUrl || !widgetPath) return;

    if (typeof window !== "undefined" && widgetPath) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any)._stmsg_widget = (window as any)._stmsg_widget || [];

      const loaderScript = `${widgetPath}loader.js`;
      const feedbackScript = `${widgetPath}feedback.js`;

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any)._stmsg_widget.push([
        "loader",
        "init",
        {
          params: {
            title,
            api: apiUrl,
            channel,
            placeholder,
            emailPlaceholder,
            submitText,
            successText,
            successText2,
            closeLabel,
            ...(user?.email && { email: user.email }),
          },
          script: feedbackScript,
          widget,
          label: title,
          closeLabel,
        },
      ]);

      if (!document.querySelector(`script[src="${loaderScript}"]`)) {
        const script = document.createElement("script");
        script.async = true;
        script.src = loaderScript;
        const firstScript = document.getElementsByTagName("script")[0];
        if (firstScript && firstScript.parentNode) {
          firstScript.parentNode.insertBefore(script, firstScript);
        }
      }
    }
  }, [
    title,
    channel,
    apiUrl,
    widgetPath,
    widget,
    placeholder,
    emailPlaceholder,
    submitText,
    successText,
    successText2,
    closeLabel,
    user?.email,
  ]);

  return null;
}
