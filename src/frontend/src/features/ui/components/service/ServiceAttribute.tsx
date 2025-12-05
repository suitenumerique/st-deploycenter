export const ServiceAttribute = ({
    name,
    value,
    children,
    interactive,
    onClick,
  }: {
    name: string;
    value?: string | null;
    children?: React.ReactNode;
    interactive?: boolean;
    onClick?: () => void;
  }) => {
    return (
      <div className="dc__service__attribute">
        <div className="dc__service__attribute__top">
          <div className="dc__service__attribute__top__name">{name}</div>
          <button
            className="dc__service__attribute__top__value"
            onClick={onClick}
            disabled={!interactive}
            type="button"
          >
            {value}
          </button>
        </div>
        {children}
      </div>
    );
  };