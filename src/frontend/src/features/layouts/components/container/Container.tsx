export const Container = ({
  children,
  title,
  subtitle,
}: {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
}) => {
  return (
    <div className="dc__container__wrapper">
      <div className="dc__container">
        <div className="dc__container__content">
          {title && <div className="dc__container__content__title">{title}</div>}
          {subtitle && <div className="dc__container__content__subtitle">{subtitle}</div>}
          {children}
        </div>
      </div>
    </div>
  );
};
