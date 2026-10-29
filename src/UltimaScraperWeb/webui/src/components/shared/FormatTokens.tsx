import { Fragment } from 'react';

import {
  FORMAT_TOKENS,
  invalidFormatTokens,
  type FormatTokenField,
} from '../../utils/formatTokens';

interface FormatTokenListProps {
  field: FormatTokenField;
  className?: string;
  /** The format(s) being edited; unknown tokens in them are called out. */
  value?: string | string[];
}

/** Every token the backend renders for a format field; hover one for its meaning. */
export function FormatTokenList({ field, className, value }: FormatTokenListProps) {
  const templates = typeof value === 'string' ? [value] : (value ?? []);
  const invalid = [...new Set(templates.flatMap(invalidFormatTokens))];
  return (
    <span className={className}>
      {invalid.length > 0 && (
        <span role="alert" style={{ display: 'block', color: 'var(--color-error)' }}>
          {invalid.map((token) => `{${token}}`).join(', ')}{' '}
          {invalid.length === 1 ? 'is not a valid token.' : 'are not valid tokens.'}
        </span>
      )}
      Available tokens:{' '}
      {FORMAT_TOKENS[field].map(({ token, description }, index) => (
        <Fragment key={token}>
          {index > 0 && ', '}
          <code title={description}>{`{${token}}`}</code>
        </Fragment>
      ))}
    </span>
  );
}
