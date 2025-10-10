export const Container = ({
  children,
  title,
  subtitle,
  titleNode,
}: {
  children: React.ReactNode;
  title?: string;
  subtitle?: string;
  titleNode?: React.ReactNode;
}) => {
  return (
    <div className="dc__container__wrapper">
      <div className="dc__container">
        <div className="dc__container__content">
          <div className="dc__container__content__header">
            {titleNode}
            {title && (
              <div className="dc__container__content__title">{title}</div>
            )}
            {subtitle && (
              <div className="dc__container__content__subtitle">{subtitle}</div>
            )}
          </div>
          <div className="dc__container__content__body">{children}</div>
        </div>
      </div>
    </div>
  );
};
